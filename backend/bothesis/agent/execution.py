"""Provider-neutral hosted-execution capability contract."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ExecutionCapability:
    """Hosted-execution features resolved for one provider and model step."""

    provider: str
    model: str | None
    hosted_shell: bool = False
    provider_files: bool = False
    persistent_environments: bool = False
    # Opaque adapter state. It never becomes model context or a client event;
    # the provider tool builder is the only consumer.
    environment_id: str | None = field(default=None, repr=False, compare=False)
    workspace_file_ids: tuple[str, ...] = field(default=(), repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("execution capability provider must not be blank")
        if self.environment_id is not None and not self.environment_id.strip():
            raise ValueError("execution environment id must not be blank")
        if any(not identifier.strip() for identifier in self.workspace_file_ids):
            raise ValueError("execution workspace file ids must not be blank")

    @property
    def available(self) -> bool:
        return any(
            (
                self.hosted_shell,
                self.provider_files,
                self.persistent_environments,
            )
        )


__all__ = ["ExecutionCapability"]
