"""BoThesis source adapters and validated ingestion hand-off contracts.

Each sub-package (confluence, jira, file, google_drive) implements the connector
contracts defined in ``connector.base`` and produces canonical items defined in
``bothesis.knowledge.protocol``.
"""

from .adapter import CheckpointedSourceConnectorAdapter
from .pipeline import ConnectorPipeline, ConnectorPipelineConfig
from .qdrant import QdrantChunkPayload, QdrantChunkRecord, QdrantPayloadContext
from bothesis.knowledge.protocol import AnyContentPart, AnyItem, ItemChange

__all__ = [
    "ConnectorPipeline",
    "ConnectorPipelineConfig",
    "CheckpointedSourceConnectorAdapter",
    "QdrantChunkPayload",
    "QdrantChunkRecord",
    "QdrantPayloadContext",
    "AnyContentPart",
    "AnyItem",
    "ItemChange",
]
