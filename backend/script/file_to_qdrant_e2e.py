#!/usr/bin/env python3
"""Run one local file through parsing, chunking, embedding, and Qdrant."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
from pathlib import Path
import sys
from uuid import NAMESPACE_URL, uuid5

from dotenv import load_dotenv
from qdrant_client import models as qmodels


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env", override=False)

from bothesis.agent.transports.openrouter import OpenRouterTransport  # noqa: E402
from bothesis.connector.file import FileProcessor  # noqa: E402
from bothesis.connector.protocol import (  # noqa: E402
    AccessPolicy,
    Hierarchy,
    SourceIdentity,
    SourceProvider,
)
from bothesis.document_index import (  # noqa: E402
    BM25_MODEL,
    BM25_OPTIONS,
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
)
from bothesis.document_index.payload import (  # noqa: E402
    QdrantPayloadContext,
    build_qdrant_records,
)
from bothesis.document_index.vector_store import VectorStore  # noqa: E402


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
        "--integration-connection-id",
        default="file-e2e-connection",
        help="Synthetic file connection lineage",
    )
    parser.add_argument(
        "--ingestion-source-id",
        default="file-e2e-source",
        help="Synthetic ingestion-source lineage",
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


async def _ensure_collection(
    store: VectorStore,
    *,
    vector_size: int,
) -> bool:
    if await store.client.collection_exists(store.collection_name):
        collection = await store.client.get_collection(store.collection_name)
        vectors = collection.config.params.vectors
        sparse_vectors = collection.config.params.sparse_vectors or {}
        dense = vectors.get(DENSE_VECTOR_NAME) if isinstance(vectors, dict) else None
        if dense is None or dense.size != vector_size:
            actual_size = dense.size if dense is not None else "missing"
            raise ValueError(
                f"Qdrant collection {store.collection_name!r} has "
                f"{DENSE_VECTOR_NAME!r} size {actual_size}; expected {vector_size}"
            )
        if dense.distance != qmodels.Distance.COSINE:
            raise ValueError(
                f"Qdrant collection {store.collection_name!r} must use Cosine "
                f"distance for {DENSE_VECTOR_NAME!r}"
            )
        if SPARSE_VECTOR_NAME not in sparse_vectors:
            raise ValueError(
                f"Qdrant collection {store.collection_name!r} is missing "
                f"{SPARSE_VECTOR_NAME!r}"
            )
        return False
    await store.client.create_collection(
        collection_name=store.collection_name,
        vectors_config={
            DENSE_VECTOR_NAME: qmodels.VectorParams(
                size=vector_size,
                distance=qmodels.Distance.COSINE,
            )
        },
        sparse_vectors_config={
            SPARSE_VECTOR_NAME: qmodels.SparseVectorParams(
                modifier=qmodels.Modifier.IDF,
            )
        },
    )
    return True


async def _run(args: argparse.Namespace) -> None:
    source_path = args.file.expanduser().resolve()
    if not source_path.is_file():
        raise ValueError(f"File does not exist: {source_path}")
    if args.embedding_batch_size < 1:
        raise ValueError("--embedding-batch-size must be at least one")

    tenant_id = args.tenant_id.strip()
    collection_name = args.collection.strip()
    collection_item_id = args.collection_item_id.strip()
    integration_connection_id = args.integration_connection_id.strip()
    ingestion_source_id = args.ingestion_source_id.strip()
    if not all(
        (
            tenant_id,
            collection_name,
            collection_item_id,
            integration_connection_id,
            ingestion_source_id,
        )
    ):
        raise ValueError("tenant and lineage values must not be blank")

    content_sha256 = _content_sha256(source_path)
    item_id = (args.item_id or "").strip() or str(
        uuid5(NAMESPACE_URL, source_path.as_uri())
    )
    source = SourceIdentity(
        connector_id=integration_connection_id,
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

    print(f"[1/5] Processing {source_path.name}")
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
    store = VectorStore(
        collection_name=collection_name,
        url=qdrant_url,
        api_key=os.getenv("QDRANT_API_KEY", "").strip() or None,
        prefer_grpc=_environment_boolean("QDRANT_PREFER_GRPC"),
        timeout=60,
    )

    try:
        print(f"[2/5] Building bounded payloads with tenant={tenant_id}")
        records = await build_qdrant_records(
            processed.chunks,
            processed.item,
            QdrantPayloadContext(
                tenant_id=tenant_id,
                integration_connection_id=integration_connection_id,
                ingestion_source_id=ingestion_source_id,
                collection_item_id=collection_item_id,
                parent_item_id=collection_item_id,
                document_type=processed.item.document_kind.value,
                connector_key=SourceProvider.FILE.value,
                embedding_model=embedder.embedding_model,
            ),
        )

        print(
            f"[3/5] Embedding {len(records)} chunks with {embedder.embedding_model}"
        )
        vectors: list[list[float]] = []
        texts = [record.payload.contextual_text for record in records]
        for start in range(0, len(texts), args.embedding_batch_size):
            vectors.extend(
                await embedder.embed_documents(
                    texts[start : start + args.embedding_batch_size]
                )
            )
        if len(vectors) != len(records) or any(not vector for vector in vectors):
            raise ValueError("Every contextual chunk requires one embedding")
        vector_sizes = {len(vector) for vector in vectors}
        if len(vector_sizes) != 1:
            raise ValueError("OpenRouter returned inconsistent embedding dimensions")
        vector_size = vector_sizes.pop()

        created = await _ensure_collection(store, vector_size=vector_size)
        print(
            f"[4/5] {'Created' if created else 'Using'} Qdrant collection "
            f"{collection_name} (dense size={vector_size})"
        )
        await store.set_payload(
            payload={"is_deleted": True},
            points=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="tenant_id",
                        match=qmodels.MatchValue(value=tenant_id),
                    ),
                    qmodels.FieldCondition(
                        key="item_id",
                        match=qmodels.MatchValue(value=item_id),
                    ),
                ]
            ),
        )
        points = [
            qmodels.PointStruct(
                id=record.point_id,
                vector={
                    DENSE_VECTOR_NAME: vector,
                    SPARSE_VECTOR_NAME: qmodels.Document(
                        text=record.payload.contextual_text,
                        model=BM25_MODEL,
                        options=BM25_OPTIONS,
                    ),
                },
                payload=record.payload.for_qdrant(),
            )
            for record, vector in zip(records, vectors, strict=True)
        ]
        await store.upsert_points(points)

        retrieved = await store.client.retrieve(
            collection_name=collection_name,
            ids=[record.point_id for record in records],
            with_payload=True,
            with_vectors=False,
        )
        expected_ids = {record.point_id for record in records}
        retrieved_ids = {str(point.id) for point in retrieved}
        if retrieved_ids != expected_ids:
            raise RuntimeError(
                f"Qdrant verification mismatch: expected {len(expected_ids)}, "
                f"retrieved {len(retrieved_ids)}"
            )
        for point in retrieved:
            payload = point.payload or {}
            if (
                payload.get("tenant_id") != tenant_id
                or payload.get("item_id") != item_id
                or payload.get("integration_connection_id") != integration_connection_id
                or payload.get("ingestion_source_id") != ingestion_source_id
                or payload.get("is_deleted") is not False
            ):
                raise RuntimeError(f"Qdrant lineage verification failed: {point.id}")

        print(f"[5/5] Verified {len(retrieved)} active Qdrant points")
        if args.query:
            query = args.query.strip()
            if not query:
                raise ValueError("--query must not be blank")
            query_vector = await embedder.embed_query(query)
            results = await store.semantic_search(
                query_vector,
                query_text=query,
                query_filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="tenant_id",
                            match=qmodels.MatchValue(value=tenant_id),
                        ),
                        qmodels.FieldCondition(
                            key="item_id",
                            match=qmodels.MatchValue(value=item_id),
                        ),
                        qmodels.FieldCondition(
                            key="is_deleted",
                            match=qmodels.MatchValue(value=False),
                        ),
                    ]
                ),
                limit=min(5, len(records)),
                candidate_limit=max(20, min(5, len(records))),
                log_label="file-to-qdrant-e2e",
            )
            if not results:
                raise RuntimeError("Hybrid search returned no active chunks")
            print(f"      hybrid search verified {len(results)} result(s)")

        print(
            "PASS "
            f"item_id={item_id} collection={collection_name} "
            f"chunks={len(records)} vector_size={vector_size}"
        )
    finally:
        await embedder.aclose()
        await store.aclose()


def main() -> int:
    try:
        asyncio.run(_run(_parse_args()))
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
