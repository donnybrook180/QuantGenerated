from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from quant_system.config import SystemConfig
from quant_system.interpreter.app import build_all_market_interpreter_states, build_market_interpreter_state
from quant_system.live.models import SymbolDeployment
from quant_system.models import FeatureVector, MarketBar
from quant_system.regime import RegimeSnapshot


@dataclass
class _DummyContext:
    timeframe: str
    bars: list[MarketBar]
    feature_values: dict[str, float]
    latest_feature: FeatureVector


def _deployment(symbol: str = "EURUSD") -> SymbolDeployment:
    return SymbolDeployment(
        profile_name=f"symbol::{symbol.lower()}",
        symbol=symbol,
        data_symbol=symbol,
        broker_symbol=symbol,
        research_run_id=1,
        execution_set_id=1,
        execution_validation_summary="accepted",
    )


def _bars() -> list[MarketBar]:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        MarketBar(timestamp=now, symbol="EURUSD", open=100.0, high=101.0, low=99.0, close=100.5, volume=1000.0)
        for _ in range(40)
    ]


def _feature_values() -> dict[str, float]:
    return {
        "session_bucket": "us_open",
        "fast_trend_return_pct": 0.3,
        "slow_trend_return_pct": 0.4,
        "range_compression_score": 0.2,
        "breakout_distance_atr": 0.4,
        "close_location_in_range": 0.85,
        "atr_pct": 0.009,
        "execution_fill_count": 6.0,
        "shortfall_regime_bps": 1.0,
        "cost_regime_bps": 0.5,
        "adverse_fill_rate_pct": 40.0,
        "spread_regime_zscore": 0.3,
        "latest_close": 100.5,
        "latest_volume": 1000.0,
    }


class InterpreterAppTests(unittest.TestCase):
    def test_build_market_interpreter_state_returns_insufficient_data_state_when_context_missing(self) -> None:
        with patch("quant_system.interpreter.app.build_feature_context", return_value=None):
            state = build_market_interpreter_state(_deployment())

        self.assertEqual(state.risk_posture, "defensive")
        self.assertEqual(state.no_trade_reason, "insufficient_market_data")
        self.assertEqual(state.allowed_archetypes, [])

    def test_build_market_interpreter_state_populates_expected_fields_when_context_exists(self) -> None:
        context = _DummyContext(
            timeframe="5_minute",
            bars=_bars(),
            feature_values=_feature_values(),
            latest_feature=FeatureVector(timestamp=datetime(2026, 1, 1, tzinfo=UTC), symbol="EURUSD", values={}),
        )
        regime_snapshot = RegimeSnapshot(
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            symbol="EURUSD",
            regime_label="calm_trend",
            volatility_label="normal",
            structure_label="trend",
            realized_vol_20=0.1,
            realized_vol_100=0.2,
            vol_ratio=0.5,
            vol_percentile=0.4,
            atr_percent=0.01,
            trend_strength=0.5,
            range_efficiency=0.8,
            risk_multiplier=1.0,
            block_new_entries=False,
        )
        with patch("quant_system.interpreter.app.build_feature_context", return_value=context), patch(
            "quant_system.interpreter.app.classify_regime",
            return_value=regime_snapshot,
        ):
            state = build_market_interpreter_state(_deployment())

        self.assertEqual(state.symbol, "EURUSD")
        self.assertEqual(state.directional_bias, "long")
        self.assertEqual(state.execution_regime, "clean")
        self.assertGreater(state.confidence, 0.0)
        self.assertIsNotNone(state.feature_snapshot)
        self.assertTrue(state.explanation)

    def test_build_market_interpreter_state_clears_allowed_archetypes_when_no_trade_reason_exists(self) -> None:
        values = _feature_values()
        values["execution_fill_count"] = 6.0
        values["shortfall_regime_bps"] = 7.0
        context = _DummyContext(
            timeframe="5_minute",
            bars=_bars(),
            feature_values=values,
            latest_feature=FeatureVector(timestamp=datetime(2026, 1, 1, tzinfo=UTC), symbol="EURUSD", values={}),
        )
        with patch("quant_system.interpreter.app.build_feature_context", return_value=context), patch(
            "quant_system.interpreter.app.classify_regime",
            return_value=None,
        ):
            state = build_market_interpreter_state(_deployment())

        self.assertEqual(state.no_trade_reason, "execution_toxic")
        self.assertEqual(state.allowed_archetypes, [])

    def test_build_market_interpreter_state_applies_regime_block_override(self) -> None:
        context = _DummyContext(
            timeframe="5_minute",
            bars=_bars(),
            feature_values=_feature_values(),
            latest_feature=FeatureVector(timestamp=datetime(2026, 1, 1, tzinfo=UTC), symbol="EURUSD", values={}),
        )
        regime_snapshot = RegimeSnapshot(
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            symbol="EURUSD",
            regime_label="volatile_trend",
            volatility_label="high",
            structure_label="trend",
            realized_vol_20=0.1,
            realized_vol_100=0.2,
            vol_ratio=0.5,
            vol_percentile=0.9,
            atr_percent=0.02,
            trend_strength=0.5,
            range_efficiency=0.8,
            risk_multiplier=0.5,
            block_new_entries=True,
        )
        with patch("quant_system.interpreter.app.build_feature_context", return_value=context), patch(
            "quant_system.interpreter.app.classify_regime",
            return_value=regime_snapshot,
        ):
            state = build_market_interpreter_state(_deployment())

        self.assertEqual(state.risk_posture, "defensive")
        self.assertEqual(state.no_trade_reason, "regime_block::volatile_trend")

    def test_build_all_market_interpreter_states_sorts_output_consistently(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            (base / "b" / "live.json").mkdir(parents=True)
            (base / "a" / "live.json").mkdir(parents=True)
            paths = [base / "b" / "live.json", base / "a" / "live.json"]
            states = [
                type("State", (), {"risk_posture": "reduced", "execution_regime": "clean", "symbol": "B"})(),
                type("State", (), {"risk_posture": "defensive", "execution_regime": "fragile", "symbol": "A"})(),
            ]
            with patch("quant_system.interpreter.app.DEPLOY_DIR", base), patch(
                "quant_system.interpreter.app.load_symbol_deployment",
                side_effect=[_deployment("B"), _deployment("A")],
            ), patch(
                "quant_system.interpreter.app.build_market_interpreter_state",
                side_effect=states,
            ):
                result = build_all_market_interpreter_states(SystemConfig())

        self.assertEqual([state.symbol for state in result], ["A", "B"])


if __name__ == "__main__":
    unittest.main()
