from __future__ import annotations

import unittest

from quant_system.symbol_research import _execution_candidate_row, _meets_viability, _promotion_tier_for_row, _specialist_live_gate
from quant_system.test_fixtures import make_candidate_result, make_candidate_row


class SymbolResearchViabilityTests(unittest.TestCase):
    def test_meets_viability_accepts_candidate_above_thresholds(self) -> None:
        row = make_candidate_row()
        self.assertTrue(_meets_viability(row, "EURUSD"))

    def test_meets_viability_rejects_candidate_below_validation_trade_threshold(self) -> None:
        row = make_candidate_row(validation_closed_trades=0, test_closed_trades=1)
        self.assertFalse(_meets_viability(row, "EURUSD"))

    def test_meets_viability_rejects_candidate_with_bad_monte_carlo_profile(self) -> None:
        row = make_candidate_row(mc_pnl_p05=-1.0)
        self.assertFalse(_meets_viability(row, "EURUSD"))

    def test_meets_viability_requires_extra_trade_support_for_4h(self) -> None:
        row = make_candidate_row(
            timeframe_label="4h",
            closed_trades=3,
            validation_closed_trades=1,
            test_closed_trades=0,
        )
        self.assertFalse(_meets_viability(row, "JP225"))

    def test_promotion_tier_returns_core_for_viable_candidate(self) -> None:
        row = make_candidate_row()
        self.assertEqual(_promotion_tier_for_row(row, "EURUSD"), "core")

    def test_promotion_tier_returns_specialist_for_btc_specialist_candidate(self) -> None:
        row = make_candidate_row(
            symbol="BTC",
            candidate_name="btc_specialist_candidate",
            code_path="quant_system.agents.crypto.CryptoTrendPullbackAgent",
            strategy_family="crypto_trend_pullback",
            realized_pnl=25.0,
            profit_factor=1.8,
            closed_trades=5,
            payoff_ratio=2.0,
            validation_pnl=0.0,
            validation_profit_factor=0.0,
            validation_closed_trades=0,
            test_pnl=0.0,
            test_profit_factor=0.0,
            test_closed_trades=0,
            walk_forward_windows=1,
            walk_forward_pass_rate_pct=0.0,
            walk_forward_soft_pass_rate_pct=0.0,
            walk_forward_avg_validation_pnl=5.0,
            walk_forward_avg_test_pnl=0.0,
            best_trade_share_pct=80.0,
            equity_quality_score=0.5,
            best_regime="trend_up_vol_high",
            best_regime_pnl=25.0,
            regime_stability_score=1.0,
            regime_loss_ratio=0.0,
            regime_trade_count_by_label={"trend_up_vol_high": 5},
            regime_pf_by_label={"trend_up_vol_high": 1.8},
            sparse_strategy=True,
            mc_simulations=500,
            mc_pnl_p05=3.0,
            mc_loss_probability_pct=0.0,
            promotion_tier="reject",
        )
        self.assertEqual(_promotion_tier_for_row(row, "BTC"), "specialist")

    def test_promotion_tier_returns_reject_for_non_viable_candidate(self) -> None:
        row = make_candidate_row(realized_pnl=-1.0)
        self.assertEqual(_promotion_tier_for_row(row, "EURUSD"), "reject")

    def test_specialist_live_gate_accepts_strong_specialist(self) -> None:
        row = make_candidate_row(
            symbol="US500",
            promotion_tier="specialist",
            regime_specialist_viable=True,
            realized_pnl=90.0,
            profit_factor=2.1,
            closed_trades=12,
            validation_pnl=1.0,
            validation_closed_trades=2,
            test_pnl=5.0,
            test_closed_trades=2,
            dominant_regime_share_pct=80.0,
            equity_quality_score=0.62,
            walk_forward_pass_rate_pct=0.0,
            walk_forward_soft_pass_rate_pct=50.0,
            best_regime="trend_up_vol_high",
        )
        approved, reasons = _specialist_live_gate(row, "US500")
        self.assertTrue(approved)
        self.assertEqual(reasons, [])

    def test_specialist_live_gate_rejects_weak_specialist(self) -> None:
        row = make_candidate_row(
            symbol="UK100",
            promotion_tier="specialist",
            regime_specialist_viable=True,
            realized_pnl=40.0,
            profit_factor=1.3,
            closed_trades=4,
            validation_pnl=-6.0,
            validation_closed_trades=1,
            test_pnl=0.0,
            test_closed_trades=1,
            dominant_regime_share_pct=35.0,
            equity_quality_score=0.41,
            walk_forward_pass_rate_pct=0.0,
            walk_forward_soft_pass_rate_pct=0.0,
            best_regime="trend_up_vol_high",
        )
        approved, reasons = _specialist_live_gate(row, "UK100")
        self.assertFalse(approved)
        self.assertTrue(any("profit_factor" in reason for reason in reasons))
        self.assertTrue(any("walk_forward" in reason for reason in reasons))

    def test_execution_candidate_row_does_not_add_explicit_swap_viability_reason(self) -> None:
        row = make_candidate_row(
            symbol="EURUSD",
            direction_mode="long_only",
            expectancy=0.2,
            broker_swap_available=True,
            broker_swap_long=-2.4,
            broker_swap_short=0.5,
            broker_preferred_carry_side="short",
            avg_hold_hours=36.0,
            estimated_swap_drag_total=21.6,
            estimated_swap_drag_per_trade=3.6,
            swap_adjusted_expectancy=-3.4,
        )

        candidate_row = _execution_candidate_row("EURUSD", row)

        self.assertNotIn("swap_adjusted_expectancy_non_positive", candidate_row["prop_viability_reasons"])

    def test_execution_candidate_row_fails_when_medium_execution_stress_breaks_edge(self) -> None:
        row = make_candidate_row(
            symbol="EURUSD",
            expectancy=1.2,
            stress_expectancy_mild=0.8,
            stress_expectancy_medium=-0.1,
            stress_expectancy_harsh=-0.6,
            stress_pf_mild=1.08,
            stress_pf_medium=0.96,
            stress_pf_harsh=0.82,
            stress_survival_score=0.40,
        )

        candidate_row = _execution_candidate_row("EURUSD", row)

        self.assertEqual(candidate_row["prop_viability_label"], "fail")
        self.assertIn("stress_medium_breaks_viability", candidate_row["prop_viability_reasons"])

    def test_execution_candidate_row_downgrades_when_prop_fit_is_caution(self) -> None:
        row = make_candidate_row(
            symbol="EURUSD",
            prop_fit_score=0.62,
            prop_fit_label="caution",
            prop_fit_reasons=("news_window_trade_share_elevated", "execution_dependency_flag"),
            news_window_trade_share=0.30,
            sub_short_hold_share=0.10,
            execution_dependency_flag=True,
        )

        candidate_row = _execution_candidate_row("EURUSD", row)

        self.assertEqual(candidate_row["prop_viability_label"], "caution")
        self.assertIn("news_window_trade_share_elevated", candidate_row["prop_viability_reasons"])

    def test_execution_candidate_row_fails_when_prop_fit_is_fail(self) -> None:
        row = make_candidate_row(
            symbol="EURUSD",
            prop_fit_score=0.30,
            prop_fit_label="fail",
            prop_fit_reasons=("sub_short_hold_share_too_high", "execution_dependency_flag"),
            sub_short_hold_share=0.75,
            execution_dependency_flag=True,
        )

        candidate_row = _execution_candidate_row("EURUSD", row)

        self.assertEqual(candidate_row["prop_viability_label"], "fail")
        self.assertIn("sub_short_hold_share_too_high", candidate_row["prop_viability_reasons"])

    def test_execution_candidate_row_fails_when_interpreter_fit_is_poor(self) -> None:
        row = make_candidate_row(
            symbol="EURUSD",
            interpreter_fit_score=0.18,
            common_live_regime_fit=0.12,
            blocked_by_interpreter_risk=0.82,
            interpreter_fit_reasons=("blocked_by_interpreter_risk_high", "common_live_regime_fit_low"),
        )

        candidate_row = _execution_candidate_row("EURUSD", row)

        self.assertEqual(candidate_row["prop_viability_label"], "fail")
        self.assertIn("blocked_by_interpreter_risk_high", candidate_row["prop_viability_reasons"])

    def test_execution_candidate_row_downgrades_when_interpreter_fit_is_elevated_risk(self) -> None:
        row = make_candidate_row(
            symbol="EURUSD",
            interpreter_fit_score=0.54,
            common_live_regime_fit=0.42,
            blocked_by_interpreter_risk=0.48,
            interpreter_fit_reasons=("blocked_by_interpreter_risk_elevated",),
        )

        candidate_row = _execution_candidate_row("EURUSD", row)

        self.assertEqual(candidate_row["prop_viability_label"], "caution")
        self.assertIn("blocked_by_interpreter_risk_elevated", candidate_row["prop_viability_reasons"])

    def test_execution_candidate_row_from_result_downgrades_prop_fit_caution_without_failing_interpreter_fit(self) -> None:
        row = make_candidate_result(
            strategy_family="forex_breakout_momentum",
            direction_mode="long_only",
            direction_role="long_leg",
            interpreter_fit_score=0.82,
            common_live_regime_fit=0.66,
            blocked_by_interpreter_risk=0.18,
        )
        row.prop_fit_label = "caution"
        row.prop_fit_reasons = ("news_window_trade_share_elevated",)
        row.news_window_trade_share = 0.32

        candidate_row = _execution_candidate_row("EURUSD", row)

        self.assertEqual(candidate_row["prop_viability_label"], "caution")
        self.assertIn("news_window_trade_share_elevated", candidate_row["prop_viability_reasons"])


if __name__ == "__main__":
    unittest.main()
