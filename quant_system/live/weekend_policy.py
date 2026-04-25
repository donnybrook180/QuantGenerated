from __future__ import annotations

from datetime import UTC, datetime

from quant_system.config import SystemConfig


def weekend_flatten_cutoff(config: SystemConfig) -> tuple[int, int]:
    hour = min(max(int(config.execution.weekend_flatten_hour_utc), 0), 23)
    minute = min(max(int(config.execution.weekend_flatten_minute_utc), 0), 59)
    return hour, minute


def is_weekend_entry_block(config: SystemConfig, now: datetime | None = None) -> bool:
    if not config.execution.avoid_weekend_holds:
        return False
    current = now or datetime.now(UTC)
    weekday = current.weekday()
    cutoff_hour, cutoff_minute = weekend_flatten_cutoff(config)
    if weekday > 4:
        return True
    if weekday < int(config.execution.weekend_flatten_weekday_utc):
        return False
    if weekday > int(config.execution.weekend_flatten_weekday_utc):
        return True
    return (current.hour, current.minute) >= (cutoff_hour, cutoff_minute)


def should_force_weekend_flatten(config: SystemConfig, now: datetime | None = None) -> bool:
    if not config.execution.avoid_weekend_holds:
        return False
    current = now or datetime.now(UTC)
    cutoff_weekday = int(config.execution.weekend_flatten_weekday_utc)
    cutoff_hour, cutoff_minute = weekend_flatten_cutoff(config)
    return current.weekday() == cutoff_weekday and (current.hour, current.minute) >= (cutoff_hour, cutoff_minute)
