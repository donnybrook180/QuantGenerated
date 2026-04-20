from __future__ import annotations

import unittest

from quant_system.symbol_research import _build_execution_candidate_sets, _is_valid_execution_combo, select_execution_candidates, select_sparse_execution_candidates
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


if __name__ == "__main__":
    unittest.main()
