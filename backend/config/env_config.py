"""Single source of truth for BoThesis process configuration.

Every environment variable the application depends on is read here, once, and
handed to the rest of the system as validated values. No module outside this
one should call ``os.getenv`` for application settings.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache

from bothesis.services import (
    DEFAULT_MAX_UPLOAD_BYTES,
    DEFAULT_PREVIEW_MAX_DIMENSION,
    DEFAULT_PREVIEW_MAX_PAGES,
    DEFAULT_PREVIEW_MAX_SOURCE_BYTES,
    DEFAULT_PREVIEW_WEBP_QUALITY,
    DEFAULT_PROCESSING_MAX_BYTES,
    DEFAULT_UPLOAD_URL_SECONDS,
)

OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
LANGFUSE_DEFAULT_BASE_URL = "https://cloud.langfuse.com"
AWS_S3_PROVIDER = "aws_s3"
CLOUDFLARE_R2_PROVIDER = "cloudflare_r2"


def text(name: str, default: str) -> str:
    """Read a required string, falling back to a non-blank default."""

    value = (os.getenv(name) or "").strip()
    return value or default


def optional_text(*names: str) -> str | None:
    """Read the first non-blank value across equivalent variable names."""

    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return None


def boolean(name: str, *, default: bool = False) -> bool:
    """Read one strict JSON boolean so misconfiguration fails loudly."""

    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must be a JSON boolean") from exc
    if not isinstance(value, bool):
        raise RuntimeError(f"{name} must be a JSON boolean")
    return value


def integer(*names: str, default: int) -> int:
    """Read the first defined integer across equivalent variable names."""

    for name in names:
        raw_value = os.getenv(name)
        if raw_value is None or not raw_value.strip():
            continue
        try:
            return int(raw_value.strip())
        except ValueError as exc:
            raise RuntimeError(f"{name} must be an integer") from exc
    return default


def optional_number(name: str) -> float | None:
    """Read one optional floating point setting."""

    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return None
    try:
        return float(raw_value.strip())
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc


def number(name: str, *, default: float) -> float:
    """Read one floating point setting."""

    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        return float(raw_value.strip())
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc


# ---------------------------------------------------------------------------
# Configuration groups
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ServerConfig:
    """Uvicorn bootstrap settings."""

    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"

    @classmethod
    def from_environment(cls) -> ServerConfig:
        return cls(
            host=text("BOTHESIS_HOST", "127.0.0.1"),
            port=integer("BOTHESIS_PORT", default=8000),
            log_level=text("BOTHESIS_LOG_LEVEL", "INFO").upper(),
        )


@dataclass(frozen=True, slots=True)
class IdentityConfig:
    """Trust settings for resolving the caller at the HTTP boundary."""

    allow_insecure_development_identity: bool = False

    @classmethod
    def from_environment(cls) -> IdentityConfig:
        return cls(
            allow_insecure_development_identity=boolean(
                "BOTHESIS_ALLOW_INSECURE_DEV_IDENTITY"
            )
        )


@dataclass(frozen=True, slots=True)
class ObjectStorageConfig:
    """Durable document storage settings for AWS S3 or Cloudflare R2."""

    provider: str = AWS_S3_PROVIDER
    bucket: str | None = None
    region: str | None = None
    endpoint_url: str | None = None
    addressing_style: str = "auto"
    account_id: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None
    timeout_seconds: float = 20.0
    max_pool_connections: int = 20

    def __post_init__(self) -> None:
        if self.provider not in {AWS_S3_PROVIDER, CLOUDFLARE_R2_PROVIDER}:
            raise RuntimeError(
                "BOTHESIS_OBJECT_STORAGE_PROVIDER must be aws_s3 or cloudflare_r2"
            )

    @property
    def uses_cloudflare_r2(self) -> bool:
        return self.provider == CLOUDFLARE_R2_PROVIDER

    def require_bucket(self) -> str:
        """Fail with the provider's own message when storage is incomplete.

        Validation stays out of ``__post_init__`` so the process can start
        without object storage and only fail when a request needs it.
        """

        if self.uses_cloudflare_r2:
            configured = any(
                (
                    self.account_id,
                    self.endpoint_url,
                    self.access_key_id,
                    self.secret_access_key,
                )
            )
            if configured and not self.bucket:
                raise RuntimeError(
                    "BOTHESIS_R2_BUCKET is required when Cloudflare R2 is configured"
                )
            if not self.bucket:
                raise RuntimeError("BOTHESIS_OBJECT_STORAGE_BUCKET is required")
            if not (self.account_id or self.endpoint_url):
                raise RuntimeError(
                    "BOTHESIS_R2_ACCOUNT_ID or BOTHESIS_R2_ENDPOINT_URL is required"
                )
            if not (self.access_key_id and self.secret_access_key):
                raise RuntimeError(
                    "BOTHESIS_R2_ACCESS_KEY_ID and "
                    "BOTHESIS_R2_SECRET_ACCESS_KEY are required"
                )
            return self.bucket
        if self.endpoint_url and not self.bucket:
            raise RuntimeError(
                "BOTHESIS_S3_BUCKET is required when AWS S3 is configured"
            )
        if not self.bucket:
            raise RuntimeError("BOTHESIS_OBJECT_STORAGE_BUCKET is required")
        return self.bucket

    @classmethod
    def from_environment(cls) -> ObjectStorageConfig:
        provider = text(
            "BOTHESIS_OBJECT_STORAGE_PROVIDER", AWS_S3_PROVIDER
        ).lower()
        if provider == CLOUDFLARE_R2_PROVIDER:
            return cls(
                provider=provider,
                bucket=optional_text(
                    "BOTHESIS_R2_BUCKET", "BOTHESIS_OBJECT_STORAGE_BUCKET"
                ),
                account_id=optional_text("BOTHESIS_R2_ACCOUNT_ID"),
                endpoint_url=optional_text("BOTHESIS_R2_ENDPOINT_URL"),
                access_key_id=optional_text("BOTHESIS_R2_ACCESS_KEY_ID"),
                secret_access_key=optional_text("BOTHESIS_R2_SECRET_ACCESS_KEY"),
                timeout_seconds=number("BOTHESIS_R2_TIMEOUT_SECONDS", default=20.0),
                max_pool_connections=integer(
                    "BOTHESIS_R2_MAX_POOL_CONNECTIONS", default=20
                ),
            )
        return cls(
            provider=provider,
            bucket=optional_text(
                "BOTHESIS_S3_BUCKET", "BOTHESIS_OBJECT_STORAGE_BUCKET"
            ),
            region=optional_text(
                "BOTHESIS_S3_REGION", "AWS_REGION", "AWS_DEFAULT_REGION"
            ),
            endpoint_url=optional_text(
                "BOTHESIS_S3_ENDPOINT_URL", "BOTHESIS_OBJECT_STORAGE_ENDPOINT"
            ),
            addressing_style=text("BOTHESIS_S3_ADDRESSING_STYLE", "auto"),
            timeout_seconds=number("BOTHESIS_S3_TIMEOUT_SECONDS", default=20.0),
            max_pool_connections=integer(
                "BOTHESIS_S3_MAX_POOL_CONNECTIONS", default=20
            ),
        )


@dataclass(frozen=True, slots=True)
class VectorIndexConfig:
    """Qdrant connection and embedding batch settings."""

    url: str | None = None
    api_key: str | None = None
    collection: str | None = None
    prefer_grpc: bool = False
    timeout_seconds: int = 20
    embedding_batch_size: int = 32

    @classmethod
    def from_environment(cls) -> VectorIndexConfig:
        return cls(
            url=optional_text("QDRANT_URL"),
            api_key=optional_text("QDRANT_API_KEY"),
            collection=optional_text("QDRANT_COLLECTION"),
            prefer_grpc=boolean("QDRANT_PREFER_GRPC"),
            embedding_batch_size=integer(
                "BOTHESIS_DOCUMENT_EMBEDDING_BATCH_SIZE", default=32
            ),
        )


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Model transport endpoints and the models used around retrieval."""

    openrouter_base_url: str = OPENROUTER_DEFAULT_BASE_URL
    openrouter_api_key: str | None = None
    openai_base_url: str = OPENAI_DEFAULT_BASE_URL
    openai_api_key: str | None = None
    chat_model: str | None = None
    embedding_model: str | None = None
    contextualization_enabled: bool = True
    contextualization_model: str | None = None
    reranker_model: str | None = None

    @classmethod
    def from_environment(cls) -> ModelConfig:
        return cls(
            openrouter_base_url=text(
                "OPEN_ROUTER_BASE_URL", OPENROUTER_DEFAULT_BASE_URL
            ),
            openrouter_api_key=optional_text("OPENROUTER_API_KEY"),
            openai_base_url=text("OPENAI_BASE_URL", OPENAI_DEFAULT_BASE_URL),
            openai_api_key=optional_text("OPENAI_API_KEY"),
            chat_model=optional_text("OPENAI_MODEL"),
            embedding_model=optional_text("EMBEDDING_MODEL"),
            contextualization_enabled=boolean(
                "BOTHESIS_CONTEXTUALIZATION_ENABLED", default=True
            ),
            contextualization_model=optional_text("BOTHESIS_CONTEXTUALIZATION_MODEL"),
            reranker_model=optional_text("BOTHESIS_RERANKER_MODEL"),
        )


@dataclass(frozen=True, slots=True)
class RetrievalConfig:
    """Hybrid retrieval, reranking, and context budget limits."""

    hybrid_candidate_limit: int = 20
    final_top_k: int = 6
    context_characters: int = 8_000
    reranking_enabled: bool = True

    def __post_init__(self) -> None:
        if (
            min(
                self.hybrid_candidate_limit,
                self.final_top_k,
                self.context_characters,
            )
            < 1
        ):
            raise ValueError("retrieval limits must be at least one")

    @classmethod
    def from_environment(cls) -> RetrievalConfig:
        return cls(
            hybrid_candidate_limit=integer(
                "BOTHESIS_RETRIEVAL_CANDIDATE_COUNT",
                "BOTHESIS_HYBRID_CANDIDATE_LIMIT",
                default=20,
            ),
            final_top_k=integer("BOTHESIS_FINAL_RETRIEVAL_TOP_K", default=6),
            context_characters=integer(
                "BOTHESIS_RETRIEVAL_CONTEXT_CHARACTERS", default=8_000
            ),
            reranking_enabled=boolean("BOTHESIS_RERANKING_ENABLED", default=True),
        )


@dataclass(frozen=True, slots=True)
class AgentRuntimeConfig:
    """Turn, tool, and history budgets applied to one agent run."""

    max_model_turns: int = 3
    max_tool_rounds: int = 2
    max_tool_calls: int = 6
    max_history_messages: int = 24
    max_history_characters: int = 24_000
    recent_history_messages: int = 6
    tool_timeout_seconds: float = 30.0

    @classmethod
    def from_environment(cls) -> AgentRuntimeConfig:
        return cls(
            max_model_turns=integer("BOTHESIS_MAX_MODEL_TURNS", default=3),
            max_tool_rounds=integer("BOTHESIS_MAX_TOOL_ROUNDS", default=2),
            max_tool_calls=integer("BOTHESIS_MAX_TOOL_CALLS", default=6),
            max_history_messages=integer("BOTHESIS_MAX_HISTORY_MESSAGES", default=24),
            max_history_characters=integer(
                "BOTHESIS_MAX_HISTORY_CHARACTERS", default=24_000
            ),
            recent_history_messages=integer(
                "BOTHESIS_RECENT_HISTORY_MESSAGES", default=6
            ),
            tool_timeout_seconds=number(
                "BOTHESIS_TOOL_TIMEOUT_SECONDS", default=30.0
            ),
        )


@dataclass(frozen=True, slots=True)
class UploadConfig:
    """Native upload size limits and presigned URL lifetimes."""

    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    processing_max_bytes: int = DEFAULT_PROCESSING_MAX_BYTES
    upload_url_seconds: int = DEFAULT_UPLOAD_URL_SECONDS
    citation_url_seconds: int = 300

    @classmethod
    def from_environment(cls) -> UploadConfig:
        return cls(
            max_upload_bytes=integer(
                "BOTHESIS_DOCUMENT_MAX_UPLOAD_BYTES",
                default=DEFAULT_MAX_UPLOAD_BYTES,
            ),
            processing_max_bytes=integer(
                "BOTHESIS_DOCUMENT_MAX_PROCESSING_BYTES",
                default=DEFAULT_PROCESSING_MAX_BYTES,
            ),
            upload_url_seconds=integer(
                "BOTHESIS_DOCUMENT_UPLOAD_URL_SECONDS",
                default=DEFAULT_UPLOAD_URL_SECONDS,
            ),
            citation_url_seconds=integer(
                "BOTHESIS_DOCUMENT_CITATION_URL_SECONDS", default=300
            ),
        )


@dataclass(frozen=True, slots=True)
class PreviewConfig:
    """Rendering limits for stored document previews."""

    max_source_bytes: int = DEFAULT_PREVIEW_MAX_SOURCE_BYTES
    max_pages: int = DEFAULT_PREVIEW_MAX_PAGES
    max_dimension: int = DEFAULT_PREVIEW_MAX_DIMENSION
    webp_quality: int = DEFAULT_PREVIEW_WEBP_QUALITY
    url_seconds: int = 300

    @classmethod
    def from_environment(cls) -> PreviewConfig:
        return cls(
            max_source_bytes=integer(
                "BOTHESIS_PREVIEW_MAX_SOURCE_BYTES",
                default=DEFAULT_PREVIEW_MAX_SOURCE_BYTES,
            ),
            max_pages=integer(
                "BOTHESIS_PREVIEW_MAX_PAGES", default=DEFAULT_PREVIEW_MAX_PAGES
            ),
            max_dimension=integer(
                "BOTHESIS_PREVIEW_MAX_DIMENSION",
                default=DEFAULT_PREVIEW_MAX_DIMENSION,
            ),
            webp_quality=integer(
                "BOTHESIS_PREVIEW_WEBP_QUALITY",
                default=DEFAULT_PREVIEW_WEBP_QUALITY,
            ),
            url_seconds=integer("BOTHESIS_PREVIEW_URL_SECONDS", default=300),
        )


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    """Concurrency limits applied to the Temporal ingestion worker."""

    max_concurrent_activities: int = 4
    activity_rate_limit: float | None = None
    graceful_shutdown_seconds: int = 30
    indexing_timeout_seconds: int = 60

    def __post_init__(self) -> None:
        if self.max_concurrent_activities < 1:
            raise RuntimeError(
                "BOTHESIS_TEMPORAL_MAX_CONCURRENT_ACTIVITIES must be at least one"
            )
        if self.activity_rate_limit is not None and self.activity_rate_limit <= 0:
            raise ValueError("Temporal Activity rate limit must be positive")

    @classmethod
    def from_environment(cls) -> WorkerConfig:
        return cls(
            max_concurrent_activities=integer(
                "BOTHESIS_TEMPORAL_MAX_CONCURRENT_ACTIVITIES", default=4
            ),
            activity_rate_limit=optional_number(
                "BOTHESIS_TEMPORAL_ACTIVITY_RATE_LIMIT"
            ),
        )


@dataclass(frozen=True, slots=True)
class IntegrationConfig:
    """Secrets protecting stored connector credentials."""

    credential_encryption_key: str | None = None

    @classmethod
    def from_environment(cls) -> IntegrationConfig:
        return cls(
            credential_encryption_key=optional_text(
                "BOTHESIS_INTEGRATION_ENCRYPTION_KEY"
            )
        )


@dataclass(frozen=True, slots=True)
class ObservabilityConfig:
    """Langfuse tracing endpoints and credentials."""

    langfuse_base_url: str = LANGFUSE_DEFAULT_BASE_URL
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None

    @classmethod
    def from_environment(cls) -> ObservabilityConfig:
        return cls(
            langfuse_base_url=(
                optional_text("LANGFUSE_BASE_URL", "LANGFUSE_HOST")
                or LANGFUSE_DEFAULT_BASE_URL
            ),
            langfuse_public_key=optional_text("LANGFUSE_PUBLIC_KEY"),
            langfuse_secret_key=optional_text("LANGFUSE_SECRET_KEY"),
        )


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Every setting the application reads, resolved at one boundary."""

    server: ServerConfig = field(default_factory=ServerConfig)
    identity: IdentityConfig = field(default_factory=IdentityConfig)
    object_storage: ObjectStorageConfig = field(default_factory=ObjectStorageConfig)
    vector_index: VectorIndexConfig = field(default_factory=VectorIndexConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    agent: AgentRuntimeConfig = field(default_factory=AgentRuntimeConfig)
    upload: UploadConfig = field(default_factory=UploadConfig)
    preview: PreviewConfig = field(default_factory=PreviewConfig)
    integration: IntegrationConfig = field(default_factory=IntegrationConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    worker: WorkerConfig = field(default_factory=WorkerConfig)

    @classmethod
    def from_environment(cls) -> AppConfig:
        """Parse and validate the whole process environment in one pass."""

        return cls(
            server=ServerConfig.from_environment(),
            identity=IdentityConfig.from_environment(),
            object_storage=ObjectStorageConfig.from_environment(),
            vector_index=VectorIndexConfig.from_environment(),
            model=ModelConfig.from_environment(),
            retrieval=RetrievalConfig.from_environment(),
            agent=AgentRuntimeConfig.from_environment(),
            upload=UploadConfig.from_environment(),
            preview=PreviewConfig.from_environment(),
            integration=IntegrationConfig.from_environment(),
            observability=ObservabilityConfig.from_environment(),
            worker=WorkerConfig.from_environment(),
        )


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Return the process configuration, parsed on first use."""

    return AppConfig.from_environment()


def reset_config() -> None:
    """Drop the cached configuration so a test can change the environment."""

    get_config.cache_clear()


__all__ = [
    "AWS_S3_PROVIDER",
    "CLOUDFLARE_R2_PROVIDER",
    "LANGFUSE_DEFAULT_BASE_URL",
    "OPENAI_DEFAULT_BASE_URL",
    "OPENROUTER_DEFAULT_BASE_URL",
    "AgentRuntimeConfig",
    "AppConfig",
    "IdentityConfig",
    "IntegrationConfig",
    "ModelConfig",
    "ObjectStorageConfig",
    "ObservabilityConfig",
    "PreviewConfig",
    "RetrievalConfig",
    "ServerConfig",
    "UploadConfig",
    "VectorIndexConfig",
    "WorkerConfig",
    "boolean",
    "get_config",
    "integer",
    "number",
    "optional_number",
    "optional_text",
    "reset_config",
    "text",
]
