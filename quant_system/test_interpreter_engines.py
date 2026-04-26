from __future__ import annotations

import unittest

from quant_system.interpreter.engines import (
    build_explanation,
    build_feature_snapshot,
    classify_execution_regime,
    classify_macro_regime,
    classify_session_regime,
    classify_structure_regime,
    classify_volatility_regime,
    derive_allowed_archetypes,
    derive_directional_bias,
    derive_risk_posture,
    score_execution_quality,
    score_setup_quality,
)
from quant_system.interpreter.models import InterpreterState


class InterpreterEnginesTests(unittest.TestCase):
    def test_classify_macro_regime_detects_pre_event(self) -> None:
        regime = classify_macro_regime({"macro_pre_event_window": 1.0})
        self.assertEqual(regime, "event_risk_high")

    def test_classify_session_regime_returns_us_open_expansion(self) -> None:
        regime = classify_session_regime({"session_bucket": "us_open", "fast_trend_return_pct": 0.25})
        self.assertEqual(regime, "us_open_expansion")

    def test_classify_structure_regime_detects_clean_breakout(self) -> None:
        regime = classify_structure_regime({"breakout_distance_atr": 0.4, "close_location_in_range": 0.9})
        self.assertEqual(regime, "clean_breakout")

    def test_classify_volatility_regime_detects_high_dislocated(self) -> None:
        regime = classify_volatility_regime({"atr_pct": 0.02})
        self.assertEqual(regime, "high_dislocated")

    def test_classify_execution_regime_detects_toxic(self) -> None:
        regime = classify_execution_regime(
            {
                "execution_fill_count": 5,
                "shortfall_regime_bps": 6.5,
                "cost_regime_bps": 3.2,
                "adverse_fill_rate_pct": 85.0,
            }
        )
        self.assertEqual(regime, "toxic")

    def test_derive_directional_bias_returns_short_for_negative_trend(self) -> None:
        bias = derive_directional_bias({"slow_trend_return_pct": -0.4}, "trend_pullback")
        self.assertEqual(bias, "short")

    def test_score_setup_quality_stays_in_unit_interval(self) -> None:
        score = score_setup_quality({"slow_trend_return_pct": 0.8}, "clean_breakout", "us_open_expansion")
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_score_execution_quality_stays_in_unit_interval(self) -> None:
        score = score_execution_quality({"spread_regime_zscore": 3.0}, "fragile")
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_derive_risk_posture_returns_defensive_for_low_confidence(self) -> None:
        posture, reason = derive_risk_posture("us_open_expansion", "normal", "clean", 0.2)
        self.assertEqual((posture, reason), ("defensive", "low_confidence"))

    def test_derive_allowed_archetypes_blocks_trend_pullback_when_bias_is_neutral(self) -> None:
        allowed, blocked = derive_allowed_archetypes("range_rotation", "midday_chop", "acceptable", "neutral")
        self.assertIn("mean_reversion", allowed)
        self.assertIn("breakout", blocked)
        self.assertIn("trend_pullback", blocked)

    def test_build_explanation_mentions_no_trade_reason(self) -> None:
        state = InterpreterState(
            symbol="EURUSD",
            broker_symbol="EURUSD",
            venue_key="blue_guardian",
            generated_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            legacy_regime_label="calm_range",
            unified_regime_label="orderly_range",
            macro_regime="neutral",
            session_regime="pre_event",
            structure_regime="compression",
            volatility_regime="normal",
            execution_regime="fragile",
            crowding_regime="neutral",
            directional_bias="neutral",
            setup_quality=0.2,
            execution_quality=0.4,
            confidence=0.3,
            risk_posture="defensive",
            allowed_archetypes=[],
            blocked_archetypes=["breakout"],
            no_trade_reason="pre_event_window",
        )
        explanation = build_explanation(state)
        self.assertIn("no trade because pre_event_window", explanation)

    def test_build_feature_snapshot_copies_expected_fields(self) -> None:
        snapshot = build_feature_snapshot(
            {
                "latest_close": 101.0,
                "latest_volume": 2000.0,
                "fast_trend_return_pct": 0.2,
                "slow_trend_return_pct": 0.5,
                "atr_pct": 0.01,
                "range_compression_score": 0.3,
                "breakout_distance_atr": 0.4,
                "distance_to_prev_day_high_atr": 0.1,
                "distance_to_prev_day_low_atr": 0.2,
                "close_location_in_range": 0.8,
                "wick_asymmetry": 0.0,
                "session_bucket": "us_open",
                "minutes_since_session_open": 30.0,
                "minutes_to_session_close": 180.0,
                "macro_high_impact_event_day": 0.0,
                "macro_pre_event_window": 0.0,
                "macro_post_event_window": 0.0,
                "macro_minutes_to_next_event": 90.0,
                "spread_regime_zscore": 0.5,
                "shortfall_regime_bps": 1.0,
                "cost_regime_bps": 0.5,
                "adverse_fill_rate_pct": 40.0,
                "execution_fill_count": 6,
            },
            timeframe="5_minute",
            bar_count=64,
        )
        self.assertEqual(snapshot.timeframe, "5_minute")
        self.assertEqual(snapshot.bar_count, 64)
        self.assertEqual(snapshot.latest_close, 101.0)
        self.assertEqual(snapshot.execution_fill_count, 6)


if __name__ == "__main__":
    unittest.main()
