"""Plugin-agnostic scheduling whose execution unit is a Binding."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import PluginBinding, PluginConnection, Schedule, SyncRun


class SchedulerService:
    """Enqueue due Binding runs and apply the configured overlap policy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue_due(
        self, *, now: datetime | None = None, limit: int = 100
    ) -> tuple[SyncRun, ...]:
        if not 1 <= limit <= 1_000:
            raise ValueError("scheduler batch limit must be between 1 and 1000")
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("scheduler time must be timezone-aware")
        schedules = list(
            await self._session.scalars(
                select(Schedule)
                .join(PluginBinding, PluginBinding.id == Schedule.binding_id)
                .join(PluginConnection, PluginConnection.id == PluginBinding.connection_id)
                .where(
                    Schedule.enabled.is_(True),
                    Schedule.deleted_at.is_(None),
                    Schedule.next_run_at.is_not(None),
                    Schedule.next_run_at <= current,
                    PluginBinding.status == "active",
                    PluginBinding.deleted_at.is_(None),
                    PluginConnection.status == "active",
                    PluginConnection.deleted_at.is_(None),
                )
                .order_by(Schedule.next_run_at, Schedule.id)
                .limit(limit)
                .with_for_update(of=Schedule, skip_locked=True)
            )
        )
        runs: list[SyncRun] = []
        for schedule in schedules:
            active = await self._session.scalar(
                select(SyncRun)
                .where(
                    SyncRun.binding_id == schedule.binding_id,
                    SyncRun.status.in_(("pending", "running")),
                )
                .order_by(SyncRun.created_at)
                .limit(1)
                .with_for_update()
            )
            if active is not None and schedule.overlap_policy == "replace":
                active.status = "cancelled"
                active.finished_at = current
                active.error_code = "schedule_replaced"
                active = None
            skipped = active is not None and schedule.overlap_policy == "skip"
            run = SyncRun(
                binding_id=schedule.binding_id,
                schedule_id=schedule.id,
                trigger_type="scheduled",
                status="skipped" if skipped else "pending",
                error_code="overlap_skipped" if skipped else None,
                finished_at=current if skipped else None,
            )
            self._session.add(run)
            runs.append(run)
            schedule.last_run_at = current
            schedule.next_run_at = self._next_run(schedule, current)
        await self._session.flush()
        return tuple(runs)

    @staticmethod
    def _next_run(schedule: Schedule, after: datetime) -> datetime | None:
        expression = (schedule.cron_expression or "").strip()
        if schedule.schedule_type == "interval":
            try:
                seconds = int(expression)
            except ValueError as exc:
                raise ValueError("interval schedule expression must be seconds") from exc
            if seconds < 1:
                raise ValueError("interval schedule must be positive")
            return after + timedelta(seconds=seconds)
        fields = expression.split()
        if len(fields) != 5:
            raise ValueError("cron expression must contain five fields")
        candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(366 * 24 * 60):
            if all(
                SchedulerService._cron_matches(field, value)
                for field, value in zip(
                    fields,
                    (
                        candidate.minute,
                        candidate.hour,
                        candidate.day,
                        candidate.month,
                        (candidate.weekday() + 1) % 7,
                    ),
                    strict=True,
                )
            ):
                return candidate
            candidate += timedelta(minutes=1)
        raise ValueError("cron expression has no run within one year")

    @staticmethod
    def _cron_matches(field: str, value: int) -> bool:
        if field == "*":
            return True
        if field.startswith("*/"):
            step = int(field[2:])
            return step > 0 and value % step == 0
        return value in {int(part) for part in field.split(",")}


__all__ = ["SchedulerService"]
