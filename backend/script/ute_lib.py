#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import logging
import os
import queue
import threading
import time
from pathlib import PurePosixPath
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import boto3
import requests
from bs4 import BeautifulSoup
from botocore.config import Config
from botocore.exceptions import ClientError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================
# CONFIG
# ============================================================

SEED_URLS = [
    "https://aao.hcmute.edu.vn/",
]

ALLOWED_HOSTS = {
    "aao.hcmute.edu.vn",
}

# Chỉ download các loại file này.
FILE_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".csv",
    ".txt",
    ".epub",
    ".zip",
    ".rar",
    ".7z",
}

FILE_CONTENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/zip",
    "application/x-rar-compressed",
    "application/x-7z-compressed",
    "text/csv",
    "text/plain",
    "application/epub+zip",
}

R2_ACCOUNT_ID = os.environ["R2_ACCOUNT_ID"]
R2_ACCESS_KEY_ID = os.environ["R2_ACCESS_KEY_ID"]
R2_SECRET_ACCESS_KEY = os.environ["R2_SECRET_ACCESS_KEY"]
R2_BUCKET = os.environ["R2_BUCKET"]

R2_PREFIX = os.getenv("R2_PREFIX", "raw")

WORKERS = int(os.getenv("WORKERS", "4"))
REQUESTS_PER_SECOND = float(
    os.getenv("REQUESTS_PER_SECOND", "2")
)

CONNECT_TIMEOUT = 15
READ_TIMEOUT = 120

PART_SIZE = 8 * 1024 * 1024

USER_AGENT = "HCMUTE-R2-File-Crawler/1.0"


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

log = logging.getLogger("crawler")


# ============================================================
# R2
# ============================================================

s3 = boto3.client(
    "s3",
    endpoint_url=(
        f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    ),
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
    config=Config(
        signature_version="s3v4",
        retries={
            "max_attempts": 5,
            "mode": "standard",
        },
    ),
)


# ============================================================
# STATE
# ============================================================

url_queue: queue.Queue[str | None] = queue.Queue()

visited: set[str] = set()
visited_lock = threading.Lock()

rate_lock = threading.Lock()
last_request_at = 0.0

thread_local = threading.local()


# ============================================================
# HTTP
# ============================================================

def get_session() -> requests.Session:
    session = getattr(thread_local, "session", None)

    if session:
        return session

    session = requests.Session()

    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=1,
        status_forcelist=[
            429,
            500,
            502,
            503,
            504,
        ],
        allowed_methods=["GET"],
        respect_retry_after_header=True,
    )

    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=WORKERS * 2,
        pool_maxsize=WORKERS * 2,
    )

    session.mount("http://", adapter)
    session.mount("https://", adapter)

    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
    })

    thread_local.session = session

    return session


def rate_limit() -> None:
    global last_request_at

    if REQUESTS_PER_SECOND <= 0:
        return

    interval = 1 / REQUESTS_PER_SECOND

    with rate_lock:
        now = time.monotonic()
        wait = interval - (now - last_request_at)

        if wait > 0:
            time.sleep(wait)

        last_request_at = time.monotonic()


# ============================================================
# URL
# ============================================================

def normalize_url(url: str) -> str | None:
    try:
        parsed = urlsplit(url)
    except Exception:
        return None

    if parsed.scheme not in {"http", "https"}:
        return None

    host = (parsed.hostname or "").lower()

    if host not in ALLOWED_HOSTS:
        return None

    return urlunsplit((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path or "/",
        parsed.query,
        "",
    ))


def enqueue(url: str) -> None:
    normalized = normalize_url(url)

    if not normalized:
        return

    with visited_lock:
        if normalized in visited:
            return

        visited.add(normalized)

    url_queue.put(normalized)


def url_looks_like_file(url: str) -> bool:
    path = urlsplit(url).path.lower()

    suffix = PurePosixPath(path).suffix

    return suffix in FILE_EXTENSIONS


# ============================================================
# RESPONSE TYPE
# ============================================================

def content_type(
    response: requests.Response,
) -> str:
    return (
        response.headers
        .get("content-type", "")
        .split(";", 1)[0]
        .strip()
        .lower()
    )


def response_is_html(
    response: requests.Response,
) -> bool:
    return content_type(response) in {
        "text/html",
        "application/xhtml+xml",
    }


def response_is_file(
    response: requests.Response,
    url: str,
) -> bool:
    if url_looks_like_file(url):
        return True

    if content_type(response) in FILE_CONTENT_TYPES:
        return True

    disposition = response.headers.get(
        "content-disposition",
        "",
    ).lower()

    return "attachment" in disposition


# ============================================================
# R2 KEY
# ============================================================

def build_r2_key(url: str) -> str:
    parsed = urlsplit(url)

    host = parsed.hostname or "unknown"

    path = parsed.path.strip("/")

    if not path:
        path = "download"

    if parsed.query:
        query_hash = hashlib.sha256(
            parsed.query.encode()
        ).hexdigest()[:12]

        suffix = PurePosixPath(path).suffix

        if suffix:
            path = (
                path[:-len(suffix)]
                + f"__{query_hash}"
                + suffix
            )
        else:
            path = f"{path}__{query_hash}"

    return (
        f"{R2_PREFIX.strip('/')}/"
        f"{host}/"
        f"{path}"
    )


def r2_exists(key: str) -> bool:
    try:
        s3.head_object(
            Bucket=R2_BUCKET,
            Key=key,
        )

        return True

    except ClientError as exc:
        status = (
            exc.response
            .get("ResponseMetadata", {})
            .get("HTTPStatusCode")
        )

        if status == 404:
            return False

        raise


# ============================================================
# DOWNLOAD -> R2
# ============================================================

def ascii_metadata_value(url: str) -> str:
    # S3/R2 chỉ cho phép ASCII trong x-amz-meta-*.
    # Percent-encode để reversible (unquote ra URL gốc).
    return quote(url, safe="/:?&=#@+,;%")


def upload_file(
    url: str,
    response: requests.Response,
) -> None:
    key = build_r2_key(url)

    if r2_exists(key):
        log.info("SKIP    %s", url)
        return

    log.info("UPLOAD  %s", url)

    upload_id = None

    try:
        result = s3.create_multipart_upload(
            Bucket=R2_BUCKET,
            Key=key,
            ContentType=(
                content_type(response)
                or "application/octet-stream"
            ),

            # Chỉ giữ original source link.
            Metadata={
                "source-url": ascii_metadata_value(url),
            },
        )

        upload_id = result["UploadId"]

        parts = []
        part_number = 1

        while True:
            chunk = response.raw.read(PART_SIZE)

            if not chunk:
                break

            result = s3.upload_part(
                Bucket=R2_BUCKET,
                Key=key,
                UploadId=upload_id,
                PartNumber=part_number,
                Body=chunk,
            )

            parts.append({
                "PartNumber": part_number,
                "ETag": result["ETag"],
            })

            part_number += 1

        # Empty file.
        if not parts:
            s3.abort_multipart_upload(
                Bucket=R2_BUCKET,
                Key=key,
                UploadId=upload_id,
            )

            upload_id = None

            s3.put_object(
                Bucket=R2_BUCKET,
                Key=key,
                Body=b"",
                Metadata={
                    "source-url": ascii_metadata_value(url),
                },
            )

            return

        s3.complete_multipart_upload(
            Bucket=R2_BUCKET,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={
                "Parts": parts,
            },
        )

        upload_id = None

        log.info(
            "DONE    r2://%s/%s",
            R2_BUCKET,
            key,
        )

    except Exception:
        if upload_id:
            try:
                s3.abort_multipart_upload(
                    Bucket=R2_BUCKET,
                    Key=key,
                    UploadId=upload_id,
                )
            except Exception:
                pass

        raise


# ============================================================
# HTML -> ONLY DISCOVER <a href>
# ============================================================

def crawl_html(
    page_url: str,
    html: bytes,
) -> None:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    # Gom link từ <a href>, <iframe src>, <embed src>.
    # Portal ASP.NET đôi khi nhúng file qua iframe/embed.
    candidates: list[str] = []

    for tag in soup.find_all("a", href=True):
        candidates.append(tag["href"])

    for tag in soup.find_all(["iframe", "embed"], src=True):
        candidates.append(tag["src"])

    for raw in candidates:
        href = raw.strip()

        if not href:
            continue

        if href.startswith((
            "#",
            "javascript:",
            "mailto:",
            "tel:",
        )):
            continue

        # Telerik/ASP.NET resource handlers: không phải nội dung.
        if href.split("?", 1)[0].lower().endswith(
            (".axd",)
        ):
            continue

        url = urljoin(
            page_url,
            href,
        )

        enqueue(url)


# ============================================================
# PROCESS
# ============================================================

def process_url(url: str) -> None:
    # Nếu URL đã nhìn ra là file (theo đuôi) và đã có trên R2,
    # skip trước khi GET để khỏi tải lại và khỏi gây tải cho server.
    if url_looks_like_file(url) and r2_exists(build_r2_key(url)):
        log.info("SKIP    %s", url)
        return

    rate_limit()

    session = get_session()

    log.info("GET     %s", url)

    with session.get(
        url,
        stream=True,
        timeout=(
            CONNECT_TIMEOUT,
            READ_TIMEOUT,
        ),
        allow_redirects=True,
    ) as response:

        response.raise_for_status()

        response.raw.decode_content = False

        final_url = response.url

        # -------------------------
        # FILE
        # -------------------------

        if response_is_file(
            response,
            final_url,
        ):
            upload_file(
                url=url,
                response=response,
            )

            return

        # -------------------------
        # HTML
        # -------------------------

        if response_is_html(response):
            # Không crawl redirect ra ngoài domain.
            if not normalize_url(final_url):
                return

            html = response.content

            crawl_html(
                final_url,
                html,
            )

            return

        # -------------------------
        # EVERYTHING ELSE
        # -------------------------

        log.debug(
            "IGNORE  %s [%s]",
            final_url,
            content_type(response),
        )


# ============================================================
# WORKER
# ============================================================

def worker() -> None:
    while True:
        url = url_queue.get()

        try:
            if url is None:
                return

            try:
                process_url(url)

            except Exception as exc:
                log.warning(
                    "FAILED  %s | %s",
                    url,
                    exc,
                )

        finally:
            url_queue.task_done()


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    log.info(
        "HCMUTE file crawler -> R2"
    )

    log.info(
        "Bucket: r2://%s/%s",
        R2_BUCKET,
        R2_PREFIX,
    )

    threads = []

    for _ in range(WORKERS):
        thread = threading.Thread(
            target=worker,
            daemon=True,
        )

        thread.start()

        threads.append(thread)

    for seed in SEED_URLS:
        enqueue(seed)

    try:
        url_queue.join()

    finally:
        for _ in threads:
            url_queue.put(None)

        for thread in threads:
            thread.join()

    log.info("DONE")


if __name__ == "__main__":
    main()