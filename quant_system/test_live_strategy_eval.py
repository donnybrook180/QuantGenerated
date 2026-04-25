from __future__ import annotations

from types import SimpleNamespace

from quant_system.live.strategy_eval import matches_regime, matches_session, session_name_from_variant


def test_session_name_from_variant_defaults_to_all() -> None:
    assert session_name_from_variant("30m") == "all"


def test_matches_session_accepts_overlap_hour() -> None:
    feature = SimpleNamespace(timestamp=SimpleNamespace(hour=13), values={"hour_of_day": 13})
    assert matches_session(feature, "overlap") is True


def test_matches_regime_supports_exclude_prefix() -> None:
    feature = SimpleNamespace(values={"trend_strength": 0.002, "atr_proxy": 0.0035})
    assert matches_regime(feature, "exclude:trend_down") is True
