#!/usr/bin/env python3
"""Run one local file through parsing, chunking, embedding, and Qdrant."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env", override=False)

from bothesis.agent.transports.openrouter import OpenRouterTransport
from bothesis.connector.file import FileProcessor
from bothesis.connector.protocol import (
    AccessPolicy,
    Hierarchy,
    SourceIdentity,
    SourceProvider,
)
from bothesis.document_index import (
    IndexingContext,
    ItemIndex,
)


def _parse_args() -> argparse.Namespace:
    configured_collection = os.getenv("QDRANT_COLLECTION", "").strip() or "bothesis"
    parser = argparse.ArgumentParser(
        description=(
            "Process one file with the production Docling/chunking pipeline, "
            "embed chunks through OpenRouter, and verify them in Qdrant."
        )
    )
    parser.add_argument("file", type=Path, help="Path to the source file")
    parser.add_argument(
        "--tenant-id",
        required=True,
        help="Tenant scope written to every Qdrant payload",
    )
    parser.add_argument(
        "--collection",
        default=f"{configured_collection}-e2e",
        help="Qdrant collection (default: %(default)s)",
    )
    parser.add_argument(
        "--collection-item-id",
        default="file-e2e-root",
        help="Synthetic parent collection lineage for this isolated E2E run",
    )
    parser.add_argument(
        "--item-id",
        help="Stable document ID; defaults to a UUID derived from the absolute path",
    )
    parser.add_argument(
        "--embedding-batch-size",
        type=int,
        default=32,
        help="Chunks sent per OpenRouter embedding request (default: %(default)s)",
    )
    parser.add_argument(
        "--query",
        help="Optionally run a hybrid search after the exact point verification",
    )
    return parser.parse_args()


def _required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required (backend/.env is loaded automatically)")
    return value


def _environment_boolean(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"{name} must be 'true' or 'false'")


def _content_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


async def _run(args: argparse.Namespace) -> None:
    source_path = args.file.expanduser().resolve()
    if not source_path.is_file():
        raise ValueError(f"File does not exist: {source_path}")
    if args.embedding_batch_size < 1:
        raise ValueError("--embedding-batch-size must be at least one")

    tenant_id = args.tenant_id.strip()
    collection_name = args.collection.strip()
    collection_item_id = args.collection_item_id.strip()
    if not all((tenant_id, collection_name, collection_item_id)):
        raise ValueError("tenant and lineage values must not be blank")

    content_sha256 = _content_sha256(source_path)
    item_id = (args.item_id or "").strip() or str(
        uuid5(NAMESPACE_URL, source_path.as_uri())
    )
    source = SourceIdentity(
        connector_id="file-e2e",
        provider=SourceProvider.FILE,
        external_id=item_id,
        external_version=content_sha256,
        etag=content_sha256,
    )
    hierarchy = Hierarchy(
        parent_id=collection_item_id,
        root_id=collection_item_id,
        ancestor_ids=[collection_item_id],
        depth=1,
    )
    access = AccessPolicy.from_reader_ids([f"tenant:{tenant_id}"])

    print(f"[1/4] Processing {source_path.name}")
    processed = await asyncio.to_thread(
        FileProcessor().process_path,
        source_path,
        item_id=item_id,
        source=source,
        access=access,
        hierarchy=hierarchy,
        metadata={"content_sha256": content_sha256, "ingestion_mode": "e2e"},
    )
    if not processed.chunks:
        raise ValueError("File processing produced no chunks")
    print(
        f"      extracted={len(processed.text)} chars, "
        f"chunks={len(processed.chunks)}, mime={processed.mime_type or 'unknown'}"
    )

    openrouter_api_key = _required_environment("OPENROUTER_API_KEY")
    embedding_model = _required_environment("EMBEDDING_MODEL")
    qdrant_url = _required_environment("QDRANT_URL")
    embedder = OpenRouterTransport(
        api_key=openrouter_api_key,
        embedding_model=embedding_model,
        base_url=os.getenv(
            "OPEN_ROUTER_BASE_URL", OpenRouterTransport.DEFAULT_BASE_URL
        ).strip(),
    )
    index = ItemIndex(
        collection_name=collection_name,
        url=qdrant_url,
        api_key=os.getenv("QDRANT_API_KEY", "").strip() or None,
        prefer_grpc=_environment_boolean("QDRANT_PREFER_GRPC"),
        timeout=60,
        embedder=embedder,
        embedding_batch_size=args.embedding_batch_size,
    )

    try:
        print(f"[2/4] Indexing with tenant={tenant_id}")
        chunk_count = await index.index_item_content(
            processed.item,
            processed.chunks,
            context=IndexingContext(
                tenant_id=tenant_id,
                collection_item_id=collection_item_id,
                parent_item_id=collection_item_id,
                document_type=processed.item.document_kind.value,
                connector_key=SourceProvider.FILE.value,
            ),
        )

        print(f"[3/4] Indexed {chunk_count} chunks with {embedder.embedding_model}")
        retrieved = await index.get_item_content(
            item_id,
            tenant_id=tenant_id,
            collection_item_id=collection_item_id,
            limit=max(100, chunk_count),
        )
        expected_ids = {chunk.id for chunk in processed.chunks}
        retrieved_ids = {chunk.id for chunk in retrieved}
        if retrieved_ids != expected_ids or chunk_count != len(expected_ids):
            raise RuntimeError(
                f"Qdrant verification mismatch: expected {len(expected_ids)}, "
                f"retrieved {len(retrieved_ids)}"
            )
        if any(chunk.item_id != item_id for chunk in retrieved):
            raise RuntimeError("Qdrant Item lineage verification failed")

        print(f"[4/4] Verified {len(retrieved)} active indexed chunks")
        if args.query:
            query = args.query.strip()
            if not query:
                raise ValueError("--query must not be blank")
            results = await index.search_item_content(
                query,
                limit=min(5, chunk_count),
                tenant_id=tenant_id,
                collection_item_ids=(collection_item_id,),
            )
            if not results:
                raise RuntimeError("Hybrid search returned no active chunks")
            print(f"      hybrid search verified {len(results)} result(s)")

        print(
            f"PASS item_id={item_id} collection={collection_name} chunks={chunk_count}"
        )
    finally:
        await index.aclose()


def main() -> int:
    try:
        asyncio.run(_run(_parse_args()))
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI reports any terminal failure
        print(f"FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
