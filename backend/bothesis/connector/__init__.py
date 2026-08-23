"""BoThesis source adapters and validated ingestion hand-off contracts.

Each sub-package (confluence, jira, file, google_drive) implements the connector
contracts defined in ``connector.base`` and produces canonical items defined in
``bothesis.connector.protocol``.
"""

from .adapter import CheckpointedSourceConnectorAdapter
from .pipeline import ConnectorPipeline, ConnectorPipelineConfig
from bothesis.connector.protocol import AnyContentPart, AnyItem, ItemChange

__all__ = [
    "ConnectorPipeline",
    "ConnectorPipelineConfig",
    "CheckpointedSourceConnectorAdapter",
    "AnyContentPart",
    "AnyItem",
    "ItemChange",
]
