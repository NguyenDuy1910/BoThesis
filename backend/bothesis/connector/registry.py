"""Registry for provider-neutral connector implementations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bothesis.connector import ConnectorDefinition
from bothesis.connector.adapter import CheckpointedSourceConnectorAdapter
from bothesis.connector.base import StaticCredentialsProvider
from bothesis.connector.confluence.connector import ConfluenceConnector
from bothesis.connector.file.file_connector import FileConnector
from bothesis.connector.protocol import ConnectorScope


class ConnectorRegistry:
    """Register and resolve connector implementations by stable connector key."""

    def __init__(self, definitions: tuple[ConnectorDefinition, ...] = ()) -> None:
        self._definitions: dict[str, ConnectorDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: ConnectorDefinition) -> None:
        key = definition.key.strip().casefold()
        if not key or len(key) > 64:
            raise ValueError("connector key is invalid")
        if key in self._definitions:
            raise ValueError(f"connector is already registered: {key}")
        self._definitions[key] = definition

    def get(self, connector_key: str) -> ConnectorDefinition:
        key = connector_key.strip().casefold()
        try:
            return self._definitions[key]
        except KeyError as exc:
            raise LookupError(f"connector is not registered: {key}") from exc

    def list(self) -> tuple[ConnectorDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))

    @classmethod
    def default(cls) -> ConnectorRegistry:
        """Return the process's built-in connector registrations."""

        return cls(
            (
                ConnectorDefinition(
                    key="confluence",
                    display_name="Confluence",
                    authentication_type="credentials",
                    capabilities=("knowledge_ingestion",),
                    factory=cls._confluence_factory,
                ),
                ConnectorDefinition(
                    key="file",
                    display_name="Managed files",
                    authentication_type="none",
                    capabilities=("knowledge_ingestion", "file_upload"),
                    factory=cls._file_factory,
                ),
            )
        )

    @staticmethod
    def _file_factory(
        connection: Mapping[str, Any],
        source: Mapping[str, Any],
        credentials: Mapping[str, Any],
    ) -> FileConnector:
        del credentials
        return FileConnector({**dict(connection), **dict(source)})

    @staticmethod
    def _confluence_factory(
        connection: Mapping[str, Any],
        source: Mapping[str, Any],
        credentials: Mapping[str, Any],
    ) -> CheckpointedSourceConnectorAdapter:
        config = {**dict(connection), **dict(source)}
        wiki_base = str(config.get("wiki_base") or "").strip()
        if not wiki_base:
            raise ValueError("Confluence wiki_base is required")
        runtime = ConfluenceConnector(
            wiki_base,
            is_cloud=ConnectorRegistry._config_bool(config, "is_cloud", True),
            space=str(config.get("space") or ""),
            page_id=str(config.get("page_id") or ""),
            index_recursively=ConnectorRegistry._config_bool(
                config, "index_recursively", False
            ),
            cql_query=(str(config["cql_query"]) if config.get("cql_query") else None),
            batch_size=int(config.get("batch_size") or 50),
            labels_to_skip=[str(value) for value in config.get("labels_to_skip") or []],
            timezone_offset=float(config.get("timezone_offset") or 0),
        )
        runtime.set_credentials_provider(
            StaticCredentialsProvider(
                tenant_id=str(config.get("_tenant_id") or "default"),
                provider_key=str(config.get("_integration_connection_id") or "confluence"),
                credentials=dict(credentials),
            )
        )
        page_id = str(config.get("page_id") or "").strip()
        space = str(config.get("space") or "").strip()
        scope_type = "page" if page_id else "space" if space else "site"
        scope_value = page_id or space or "confluence"
        return CheckpointedSourceConnectorAdapter(
            source="confluence",
            connector=runtime,
            scopes=[
                ConnectorScope(
                    scope_type=scope_type,
                    scope_value=scope_value,
                    display_name=space or page_id or "Confluence",
                )
            ],
        )

    @staticmethod
    def _config_bool(config: Mapping[str, Any], key: str, default: bool) -> bool:
        value = config.get(key, default)
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be a boolean")
        return value


__all__ = ["ConnectorRegistry"]
