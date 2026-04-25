from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from quant_system.live.loop_app import record_action_state, should_skip_duplicate
from quant_system.models import Side


def test_should_skip_duplicate_ignores_dry_run_prefix_differences() -> None:
    timestamp = datetime(2026, 4, 25, tzinfo=UTC)
    state = {
        "EURUSD::forex_breakout_momentum__30m_overlap": {
            "signal_timestamp": timestamp.isoformat(),
            "signal_side": Side.BUY.value,
            "intended_action": "dry_run_open_long",
        }
    }
    action = SimpleNamespace(
        candidate_name="forex_breakout_momentum__30m_overlap",
        signal_timestamp=timestamp,
        signal_side=Side.BUY,
        intended_action="open_long",
    )

    assert should_skip_duplicate(state, "EURUSD", action) is True


def test_record_action_state_persists_expected_fields() -> None:
    timestamp = datetime(2026, 4, 25, tzinfo=UTC)
    action = SimpleNamespace(
        candidate_name="trend__4h_overlap",
        signal_timestamp=timestamp,
        signal_side=Side.SELL,
        intended_action="close_long_open_short",
    )

    state: dict[str, dict[str, object]] = {}
    record_action_state(state, "XAUUSD", action)

    stored = state["XAUUSD::trend__4h_overlap"]
    assert stored["signal_timestamp"] == timestamp.isoformat()
    assert stored["signal_side"] == Side.SELL.value
    assert stored["intended_action"] == "close_long_open_short"
    assert "updated_at" in stored
