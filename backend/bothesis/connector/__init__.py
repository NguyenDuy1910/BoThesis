"""BoThesis source adapters and validated ingestion hand-off contracts.

Each sub-package (confluence, jira, file, google_drive) implements the connector
contracts defined in ``connector.base`` and produces canonical document
models defined in ``connector.models``.
"""

from .adapter import CheckpointedSourceConnectorAdapter
from .pipeline import ConnectorPipeline, ConnectorPipelineConfig
from .qdrant import QdrantChunkPayload, QdrantChunkRecord, QdrantPayloadContext

__all__ = [
    "ConnectorPipeline",
    "ConnectorPipelineConfig",
    "CheckpointedSourceConnectorAdapter",
    "QdrantChunkPayload",
    "QdrantChunkRecord",
    "QdrantPayloadContext",
]
