from __future__ import annotations

import unittest

from quant_system.symbol_research import _meets_viability, _promotion_tier_for_row
from quant_system.test_fixtures import make_candidate_row


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


if __name__ == "__main__":
    unittest.main()
