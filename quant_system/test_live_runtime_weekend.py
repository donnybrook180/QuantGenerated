from __future__ import annotations

from datetime import UTC, datetime

from quant_system.config import SystemConfig
from quant_system.live.runtime import _is_weekend_entry_block, _should_force_weekend_flatten


def test_weekend_entry_block_starts_at_friday_cutoff() -> None:
    config = SystemConfig()
    config.execution.avoid_weekend_holds = True
    config.execution.weekend_flatten_weekday_utc = 4
    config.execution.weekend_flatten_hour_utc = 20
    config.execution.weekend_flatten_minute_utc = 45

    assert not _is_weekend_entry_block(config, datetime(2026, 4, 17, 20, 44, tzinfo=UTC))
    assert _is_weekend_entry_block(config, datetime(2026, 4, 17, 20, 45, tzinfo=UTC))


def test_force_weekend_flatten_only_triggers_on_cutoff_day() -> None:
    config = SystemConfig()
    config.execution.avoid_weekend_holds = True
    config.execution.weekend_flatten_weekday_utc = 4
    config.execution.weekend_flatten_hour_utc = 20
    config.execution.weekend_flatten_minute_utc = 45

    assert _should_force_weekend_flatten(config, datetime(2026, 4, 17, 21, 0, tzinfo=UTC))
    assert not _should_force_weekend_flatten(config, datetime(2026, 4, 18, 10, 0, tzinfo=UTC))
