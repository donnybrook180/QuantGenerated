from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quant_system.live.deploy import load_symbol_deployment


REQUIRED_DEPLOYMENT_KEYS = {
    "profile_name",
    "symbol",
    "data_symbol",
    "broker_symbol",
    "research_run_id",
    "execution_set_id",
    "execution_validation_summary",
    "symbol_status",
    "strategies",
    "target_volatility",
    "max_symbol_vol_percentile",
    "block_new_entries_in_event_risk",
}

REQUIRED_STRATEGY_KEYS = {
    "candidate_name",
    "code_path",
    "strategy_family",
    "direction_mode",
    "direction_role",
    "promotion_tier",
    "policy_summary",
    "variant_label",
    "regime_filter_label",
    "execution_overrides",
    "allocation_weight",
    "allowed_regimes",
    "blocked_regimes",
    "min_vol_percentile",
    "max_vol_percentile",
    "base_allocation_weight",
    "max_risk_multiplier",
    "min_risk_multiplier",
}


def _make_payload() -> dict[str, object]:
    return {
        "profile_name": "symbol::eurusd",
        "symbol": "EURUSD",
        "data_symbol": "C:EURUSD",
        "broker_symbol": "EURUSD",
        "research_run_id": 402,
        "execution_set_id": 203,
        "execution_validation_summary": "accepted",
        "symbol_status": "live_ready",
        "strategies": [
            {
                "candidate_name": "forex_breakout_momentum__30m_overlap",
                "code_path": "quant_system.agents.forex.ForexBreakoutMomentumAgent",
                "strategy_family": "forex_breakout_momentum__30m_overlap",
                "direction_mode": "long_only",
                "direction_role": "long_leg",
                "promotion_tier": "core",
                "policy_summary": "tier=core",
                "variant_label": "30m_overlap",
                "regime_filter_label": "",
                "execution_overrides": {},
                "allocation_weight": 1.0,
                "allowed_regimes": ["orderly_trend"],
                "blocked_regimes": ["compressed_range"],
                "min_vol_percentile": 0.2,
                "max_vol_percentile": 0.8,
                "base_allocation_weight": 1.1,
                "max_risk_multiplier": 0.96,
                "min_risk_multiplier": 0.0,
            }
        ],
        "target_volatility": 0.0,
        "max_symbol_vol_percentile": 0.98,
        "block_new_entries_in_event_risk": True,
    }


class LiveDeploymentContractTests(unittest.TestCase):
    def test_live_json_contract_contains_required_top_level_keys(self) -> None:
        payload = _make_payload()
        self.assertTrue(REQUIRED_DEPLOYMENT_KEYS.issubset(payload.keys()))

    def test_live_json_contract_contains_required_strategy_keys(self) -> None:
        payload = _make_payload()
        strategy = payload["strategies"][0]
        assert isinstance(strategy, dict)
        self.assertTrue(REQUIRED_STRATEGY_KEYS.issubset(strategy.keys()))

    def test_load_symbol_deployment_accepts_contract_payload(self) -> None:
        payload = _make_payload()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "live.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            deployment = load_symbol_deployment(path)

        self.assertEqual(deployment.symbol, "EURUSD")
        self.assertEqual(len(deployment.strategies), 1)
        self.assertEqual(deployment.strategies[0].candidate_name, "forex_breakout_momentum__30m_overlap")

    def test_load_symbol_deployment_preserves_contract_fields(self) -> None:
        payload = _make_payload()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "live.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            deployment = load_symbol_deployment(path)

        strategy = deployment.strategies[0]
        self.assertEqual(deployment.symbol_status, "live_ready")
        self.assertEqual(strategy.direction_mode, "long_only")
        self.assertEqual(strategy.direction_role, "long_leg")
        self.assertEqual(list(strategy.allowed_regimes), ["orderly_trend"])
        self.assertEqual(list(strategy.blocked_regimes), ["compressed_range"])


if __name__ == "__main__":
    unittest.main()
