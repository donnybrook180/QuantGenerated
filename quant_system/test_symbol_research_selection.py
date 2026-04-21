from __future__ import annotations

import unittest

from quant_system.symbol_research import (
    _build_execution_candidate_sets,
    _is_valid_execution_combo,
    _max_regime_overlap_score,
    _specialist_regime_overlap_rejections,
    select_execution_candidates,
    select_sparse_execution_candidates,
)
from quant_system.test_fixtures import make_candidate_row


class SymbolResearchSelectionTests(unittest.TestCase):
    def test_select_execution_candidates_keeps_single_candidate_per_strategy_family(self) -> None:
        long_row = make_candidate_row(candidate_name="opening_range_breakout")
        short_row = make_candidate_row(
            candidate_name="opening_range_short_breakdown",
            code_path="quant_system.agents.strategies.OpeningRangeShortBreakdownAgent",
            direction_mode="short_only",
            direction_role="short_leg",
            realized_pnl=12.0,
            validation_pnl=4.0,
            test_pnl=3.0,
        )

        selected = select_execution_candidates([long_row, short_row], max_candidates=3)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["strategy_family"], "opening_range_breakout")

    def test_select_sparse_execution_candidates_respects_family_uniqueness(self) -> None:
        long_row = make_candidate_row(sparse_strategy=True, payoff_ratio=2.0)
        short_row = make_candidate_row(
            candidate_name="opening_range_short_breakdown",
            code_path="quant_system.agents.strategies.OpeningRangeShortBreakdownAgent",
            direction_mode="short_only",
            direction_role="short_leg",
            sparse_strategy=True,
            payoff_ratio=2.0,
            realized_pnl=14.0,
            validation_pnl=3.0,
            test_pnl=3.0,
        )

        selected = select_sparse_execution_candidates([long_row, short_row], "EURUSD", max_candidates=3)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["strategy_family"], "opening_range_breakout")

    def test_build_execution_candidate_sets_adds_family_both_pair(self) -> None:
        long_row = make_candidate_row(candidate_name="opening_range_breakout")
        short_row = make_candidate_row(
            candidate_name="opening_range_short_breakdown",
            code_path="quant_system.agents.strategies.OpeningRangeShortBreakdownAgent",
            direction_mode="short_only",
            direction_role="short_leg",
            realized_pnl=14.0,
            validation_pnl=4.0,
            test_pnl=3.0,
        )

        candidate_sets = _build_execution_candidate_sets([long_row, short_row], "EURUSD", max_candidates=3)

        labels = {label for label, _ in candidate_sets}
        self.assertIn("family_both_opening_range_breakout", labels)

    def test_is_valid_execution_combo_rejects_both_and_single_from_same_family(self) -> None:
        both_row = make_candidate_row(direction_mode="both", direction_role="combined")
        long_row = make_candidate_row(candidate_name="opening_range_breakout")

        valid = _is_valid_execution_combo((both_row, long_row), "EURUSD", max_candidates=3)

        self.assertFalse(valid)

    def test_is_valid_execution_combo_allows_low_overlap_across_families(self) -> None:
        left = make_candidate_row(
            candidate_name="opening_range_breakout",
            strategy_family="opening_range_breakout",
            best_regime="trend_up_vol_high",
            regime_trade_count_by_label={"trend_up_vol_high": 10},
        )
        right = make_candidate_row(
            candidate_name="volatility_breakout",
            code_path="quant_system.agents.strategies.VolatilityBreakoutAgent",
            strategy_family="volatility_breakout",
            best_regime="trend_down_vol_high",
            regime_trade_count_by_label={"trend_down_vol_high": 9, "trend_flat_vol_mid": 1},
        )

        valid = _is_valid_execution_combo((left, right), "EURUSD", max_candidates=3)

        self.assertTrue(valid)

    def test_is_valid_execution_combo_rejects_high_overlap_across_families(self) -> None:
        left = make_candidate_row(
            candidate_name="opening_range_breakout",
            strategy_family="opening_range_breakout",
            best_regime="trend_up_vol_high",
            regime_trade_count_by_label={"trend_up_vol_high": 7, "trend_flat_vol_mid": 3},
        )
        right = make_candidate_row(
            candidate_name="volatility_breakout",
            code_path="quant_system.agents.strategies.VolatilityBreakoutAgent",
            strategy_family="volatility_breakout",
            best_regime="trend_down_vol_high",
            regime_trade_count_by_label={"trend_up_vol_high": 6, "trend_flat_vol_mid": 4},
        )

        valid = _is_valid_execution_combo((left, right), "EURUSD", max_candidates=3)

        self.assertFalse(valid)

    def test_select_execution_candidates_allows_specialist_with_low_regime_overlap(self) -> None:
        core_row = make_candidate_row(
            candidate_name="opening_range_breakout",
            strategy_family="opening_range_breakout",
            best_regime="trend_up_vol_high",
            regime_trade_count_by_label={"trend_up_vol_high": 10},
        )
        specialist_row = make_candidate_row(
            candidate_name="volatility_short_breakdown_specialist",
            code_path="quant_system.agents.strategies.VolatilityShortBreakdownAgent",
            strategy_family="volatility_breakout",
            direction_mode="short_only",
            direction_role="short_leg",
            best_regime="trend_down_vol_high",
            best_regime_pnl=6.0,
            regime_trade_count_by_label={"trend_down_vol_high": 8},
            regime_pf_by_label={"trend_down_vol_high": 1.3},
            regime_specialist_viable=True,
            realized_pnl=9.0,
            validation_pnl=0.0,
            validation_profit_factor=0.0,
            test_pnl=0.0,
            test_profit_factor=0.0,
            validation_closed_trades=0,
            test_closed_trades=0,
            walk_forward_avg_validation_pnl=0.0,
            walk_forward_avg_test_pnl=0.0,
        )

        selected = select_execution_candidates([core_row, specialist_row], max_candidates=3)

        self.assertEqual(len(selected), 2)
        self.assertEqual({row["best_regime"] for row in selected}, {"trend_up_vol_high", "trend_down_vol_high"})

    def test_select_execution_candidates_blocks_specialist_with_high_regime_overlap(self) -> None:
        core_row = make_candidate_row(
            candidate_name="opening_range_breakout",
            strategy_family="opening_range_breakout",
            best_regime="trend_up_vol_high",
            regime_trade_count_by_label={"trend_up_vol_high": 7, "trend_flat_vol_mid": 3},
        )
        specialist_row = make_candidate_row(
            candidate_name="volatility_short_breakdown_specialist",
            code_path="quant_system.agents.strategies.VolatilityShortBreakdownAgent",
            strategy_family="volatility_breakout",
            direction_mode="short_only",
            direction_role="short_leg",
            best_regime="trend_up_vol_high",
            best_regime_pnl=6.0,
            regime_trade_count_by_label={"trend_up_vol_high": 8, "trend_flat_vol_mid": 2},
            regime_pf_by_label={"trend_up_vol_high": 1.3, "trend_flat_vol_mid": 1.1},
            regime_specialist_viable=True,
            realized_pnl=9.0,
            validation_pnl=0.0,
            validation_profit_factor=0.0,
            test_pnl=0.0,
            test_profit_factor=0.0,
            validation_closed_trades=0,
            test_closed_trades=0,
            walk_forward_avg_validation_pnl=0.0,
            walk_forward_avg_test_pnl=0.0,
        )

        selected = select_execution_candidates([core_row, specialist_row], max_candidates=3)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["strategy_family"], "opening_range_breakout")

    def test_max_regime_overlap_score_uses_trade_distribution(self) -> None:
        base_rows = [
            make_candidate_row(
                best_regime="trend_up_vol_high",
                regime_trade_count_by_label={"trend_up_vol_high": 8, "trend_flat_vol_mid": 2},
            )
        ]
        candidate = make_candidate_row(
            strategy_family="volatility_breakout",
            best_regime="trend_down_vol_high",
            regime_trade_count_by_label={"trend_down_vol_high": 9, "trend_flat_vol_mid": 1},
        )

        overlap = _max_regime_overlap_score(candidate, base_rows)

        self.assertAlmostEqual(overlap, 0.1, places=6)

    def test_specialist_regime_overlap_rejections_reports_conflicting_candidate(self) -> None:
        selected = [
            make_candidate_row(
                candidate_name="opening_range_breakout",
                best_regime="trend_up_vol_high",
                regime_trade_count_by_label={"trend_up_vol_high": 7, "trend_flat_vol_mid": 3},
            )
        ]
        specialist = make_candidate_row(
            candidate_name="volatility_short_breakdown_specialist",
            code_path="quant_system.agents.strategies.VolatilityShortBreakdownAgent",
            strategy_family="volatility_breakout",
            direction_mode="short_only",
            direction_role="short_leg",
            best_regime="trend_up_vol_high",
            regime_trade_count_by_label={"trend_up_vol_high": 8, "trend_flat_vol_mid": 2},
            regime_pf_by_label={"trend_up_vol_high": 1.3},
            regime_specialist_viable=True,
            realized_pnl=9.0,
            validation_pnl=0.0,
            validation_profit_factor=0.0,
            test_pnl=0.0,
            test_profit_factor=0.0,
            validation_closed_trades=0,
            test_closed_trades=0,
            walk_forward_avg_validation_pnl=0.0,
            walk_forward_avg_test_pnl=0.0,
        )

        reasons = _specialist_regime_overlap_rejections([*selected, specialist], selected)

        self.assertEqual(len(reasons), 1)
        self.assertIn("rejected_due_to_regime_overlap", reasons[0])
        self.assertIn("conflicts_with=opening_range_breakout", reasons[0])


if __name__ == "__main__":
    unittest.main()
