from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from quant_system.config import SystemConfig
from quant_system.live.deploy import build_symbol_deployment, load_symbol_deployment
from quant_system.live.models import DeploymentStrategy, SymbolDeployment
from quant_system.live.runtime import MT5LiveExecutor, _mt5_timeframe_from_variant
from quant_system.models import Side
from quant_system.test_fixtures import make_candidate_row


class LiveDeployRuntimeTests(unittest.TestCase):
    def test_build_symbol_deployment_preserves_4h_variant_metadata(self) -> None:
        row = make_candidate_row(
            candidate_name="trend__4h_overlap",
            code_path="quant_system.agents.trend.TrendAgent",
            strategy_family="trend",
            direction_mode="both",
            direction_role="combined",
            variant_label="4h_overlap",
            regime_filter_label="trend_up_vol_high",
        )

        deployment = build_symbol_deployment(
            profile_name="symbol::xauusd",
            symbol="XAUUSD",
            data_symbol="C:XAUUSD",
            broker_symbol="XAUUSD",
            research_run_id=10,
            execution_set_id=20,
            execution_validation_summary="accepted",
            symbol_status="live_ready",
            selected_candidates=[row],
        )

        strategy = deployment.strategies[0]
        self.assertEqual(strategy.variant_label, "4h_overlap")
        self.assertEqual(strategy.strategy_family, "trend")
        self.assertEqual(strategy.direction_mode, "both")
        self.assertEqual(strategy.direction_role, "combined")

    def test_load_symbol_deployment_infers_live_ready_when_status_missing_and_core_strategy_exists(self) -> None:
        payload = {
            "profile_name": "symbol::xauusd",
            "symbol": "XAUUSD",
            "data_symbol": "C:XAUUSD",
            "broker_symbol": "XAUUSD",
            "research_run_id": 1,
            "execution_set_id": 2,
            "execution_validation_summary": "accepted",
            "symbol_status": "",
            "strategies": [
                {
                    "candidate_name": "trend__4h_overlap",
                    "code_path": "quant_system.agents.trend.TrendAgent",
                    "strategy_family": "trend",
                    "direction_mode": "both",
                    "direction_role": "combined",
                    "promotion_tier": "core",
                    "variant_label": "4h_overlap",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "live.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            deployment = load_symbol_deployment(path)

        self.assertEqual(deployment.symbol_status, "live_ready")
        self.assertEqual(deployment.strategies[0].variant_label, "4h_overlap")

    def test_load_symbol_deployment_infers_reduced_risk_only_for_specialist_only_set(self) -> None:
        payload = {
            "profile_name": "symbol::us500",
            "symbol": "US500",
            "data_symbol": "SPY",
            "broker_symbol": "US500.cash",
            "research_run_id": 1,
            "execution_set_id": 2,
            "execution_validation_summary": "accepted",
            "symbol_status": "",
            "strategies": [
                {
                    "candidate_name": "trend__4h_us__local_opt_density",
                    "code_path": "quant_system.agents.trend.TrendAgent",
                    "strategy_family": "trend",
                    "direction_mode": "both",
                    "direction_role": "combined",
                    "promotion_tier": "specialist",
                    "variant_label": "4h_us",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "live.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            deployment = load_symbol_deployment(path)

        self.assertEqual(deployment.symbol_status, "reduced_risk_only")

    def test_mt5_timeframe_from_variant_maps_4h_variant_to_h4(self) -> None:
        timeframe = _mt5_timeframe_from_variant("4h_overlap", "M5")
        self.assertEqual(timeframe, "H4")

    def test_reconcile_strategy_holds_existing_long_position_after_restart(self) -> None:
        deployment = SymbolDeployment(
            profile_name="symbol::eurusd",
            symbol="EURUSD",
            data_symbol="C:EURUSD",
            broker_symbol="EURUSD",
            research_run_id=1,
            execution_set_id=2,
            execution_validation_summary="accepted",
            symbol_status="live_ready",
            strategies=[
                DeploymentStrategy(
                    candidate_name="forex_breakout_momentum__30m_overlap",
                    code_path="quant_system.agents.forex.ForexBreakoutMomentumAgent",
                    variant_label="30m_overlap",
                    promotion_tier="core",
                )
            ],
        )
        config = SystemConfig()
        strategy = deployment.strategies[0]
        snapshot = SimpleNamespace(
            regime_label="trend_up_vol_high",
            vol_percentile=0.4,
            risk_multiplier=1.0,
            block_new_entries=False,
            volatility_label="vol_high",
            structure_label="breakout",
        )
        interpreter_state = SimpleNamespace(
            regime_snapshot=None,
            directional_bias="long",
            confidence=0.7,
            risk_posture="normal",
            no_trade_reason="",
            session_regime="us_open",
            blocked_archetypes=[],
            allowed_archetypes=[],
        )
        existing_position = SimpleNamespace(ticket=1001, side=Side.BUY, quantity=0.2)
        client = SimpleNamespace(
            list_positions=lambda magic_number=None: [existing_position],
            market_snapshot=lambda: SimpleNamespace(ask=1.1050, bid=1.1048),
        )

        with patch("quant_system.live.runtime.build_market_interpreter_state", return_value=interpreter_state):
            executor = MT5LiveExecutor(deployment, config)

        action = executor._reconcile_strategy(
            client=client,
            strategy=strategy,
            signal_side=Side.BUY,
            signal_timestamp=None,
            confidence=0.8,
            snapshot=snapshot,
            allocation_fraction=1.0,
            allocator_score=1.0,
            account_equity=100000.0,
            latest_feature=None,
        )

        self.assertEqual(action.current_quantity, 0.2)
        self.assertEqual(action.intended_action, "hold_long")

    def test_reconcile_strategy_holds_existing_short_position_after_restart(self) -> None:
        deployment = SymbolDeployment(
            profile_name="symbol::jp225",
            symbol="JP225",
            data_symbol="JP225",
            broker_symbol="JP225.cash",
            research_run_id=1,
            execution_set_id=2,
            execution_validation_summary="accepted",
            symbol_status="live_ready",
            strategies=[
                DeploymentStrategy(
                    candidate_name="volatility_short_breakdown__15m_europe",
                    code_path="quant_system.agents.breakout.VolatilityShortBreakdownAgent",
                    variant_label="15m_europe",
                    promotion_tier="core",
                )
            ],
        )
        config = SystemConfig()
        strategy = deployment.strategies[0]
        snapshot = SimpleNamespace(
            regime_label="trend_down_vol_high",
            vol_percentile=0.5,
            risk_multiplier=1.0,
            block_new_entries=False,
            volatility_label="vol_high",
            structure_label="breakdown",
        )
        interpreter_state = SimpleNamespace(
            regime_snapshot=None,
            directional_bias="short",
            confidence=0.75,
            risk_posture="normal",
            no_trade_reason="",
            session_regime="europe",
            blocked_archetypes=[],
            allowed_archetypes=[],
        )
        existing_position = SimpleNamespace(ticket=2002, side=Side.SELL, quantity=1.0)
        client = SimpleNamespace(
            list_positions=lambda magic_number=None: [existing_position],
            market_snapshot=lambda: SimpleNamespace(ask=59315.0, bid=59313.0),
        )

        with patch("quant_system.live.runtime.build_market_interpreter_state", return_value=interpreter_state):
            executor = MT5LiveExecutor(deployment, config)

        action = executor._reconcile_strategy(
            client=client,
            strategy=strategy,
            signal_side=Side.SELL,
            signal_timestamp=None,
            confidence=0.82,
            snapshot=snapshot,
            allocation_fraction=1.0,
            allocator_score=1.0,
            account_equity=100000.0,
            latest_feature=None,
        )

        self.assertEqual(action.current_quantity, -1.0)
        self.assertEqual(action.intended_action, "hold_short")


if __name__ == "__main__":
    unittest.main()
