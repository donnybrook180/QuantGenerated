from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quant_system.live.deploy import build_symbol_deployment, load_symbol_deployment
from quant_system.live.runtime import _mt5_timeframe_from_variant
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


if __name__ == "__main__":
    unittest.main()
