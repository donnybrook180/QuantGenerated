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
    "venue_key",
    "venue_basis",
    "prop_viability_label",
    "prop_viability_reasons",
    "top_caution_reasons",
    "top_rejection_reasons",
    "stress_survival_score",
    "prop_fit_label",
    "prop_fit_reasons",
    "interpreter_fit_score",
    "interpreter_fit_reasons",
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
    "signal_quality_score",
    "prop_viability_score",
    "prop_viability_label",
    "prop_viability_pass",
    "prop_viability_reasons",
    "stress_expectancy_mild",
    "stress_expectancy_medium",
    "stress_expectancy_harsh",
    "stress_pf_mild",
    "stress_pf_medium",
    "stress_pf_harsh",
    "stress_survival_score",
    "prop_fit_score",
    "prop_fit_label",
    "prop_fit_reasons",
    "news_window_trade_share",
    "sub_short_hold_share",
    "micro_target_risk_flag",
    "execution_dependency_flag",
    "interpreter_fit_score",
    "common_live_regime_fit",
    "blocked_by_interpreter_risk",
    "interpreter_fit_reasons",
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
        "venue_key": "blue_guardian",
        "venue_basis": "blue_guardian_mt5",
        "prop_viability_label": "pass",
        "prop_viability_reasons": [],
        "top_caution_reasons": [],
        "top_rejection_reasons": [],
        "stress_survival_score": 1.0,
        "prop_fit_label": "pass",
        "prop_fit_reasons": [],
        "interpreter_fit_score": 0.78,
        "interpreter_fit_reasons": [],
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
                "signal_quality_score": 0.84,
                "prop_viability_score": 0.79,
                "prop_viability_label": "pass",
                "prop_viability_pass": True,
                "prop_viability_reasons": [],
                "stress_expectancy_mild": 0.42,
                "stress_expectancy_medium": 0.28,
                "stress_expectancy_harsh": 0.11,
                "stress_pf_mild": 1.12,
                "stress_pf_medium": 1.06,
                "stress_pf_harsh": 1.01,
                "stress_survival_score": 1.0,
                "prop_fit_score": 0.88,
                "prop_fit_label": "pass",
                "prop_fit_reasons": [],
                "news_window_trade_share": 0.05,
                "sub_short_hold_share": 0.08,
                "micro_target_risk_flag": False,
                "execution_dependency_flag": False,
                "interpreter_fit_score": 0.78,
                "common_live_regime_fit": 0.62,
                "blocked_by_interpreter_risk": 0.14,
                "interpreter_fit_reasons": [],
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
        self.assertEqual(deployment.venue_basis, "blue_guardian_mt5")
        self.assertEqual(deployment.prop_viability_label, "pass")
        self.assertEqual(deployment.prop_fit_label, "pass")
        self.assertGreater(deployment.interpreter_fit_score, 0.0)
        self.assertEqual(strategy.direction_mode, "long_only")
        self.assertEqual(strategy.direction_role, "long_leg")
        self.assertEqual(list(strategy.allowed_regimes), ["orderly_trend"])
        self.assertEqual(list(strategy.blocked_regimes), ["compressed_range"])
        self.assertEqual(strategy.prop_viability_label, "pass")
        self.assertEqual(strategy.prop_fit_label, "pass")
        self.assertGreater(strategy.stress_survival_score, 0.0)
        self.assertGreater(strategy.interpreter_fit_score, 0.0)


if __name__ == "__main__":
    unittest.main()
