from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quant_system.live.deploy import build_symbol_deployment
from quant_system.symbol_research import _execution_candidate_row_from_result, _export_results
from quant_system.test_fixtures import make_candidate_result, make_candidate_row


class SymbolResearchExportsTests(unittest.TestCase):
    def test_export_results_writes_direction_columns_to_csv(self) -> None:
        row = make_candidate_result()
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            with patch("quant_system.symbol_research.research_reports_dir", return_value=reports_dir):
                csv_path, _ = _export_results("EURUSD", "EURUSD", "test", [row])
            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                reader = list(csv.reader(handle))

        header = reader[0]
        values = reader[1]
        self.assertIn("strategy_family", header)
        self.assertIn("direction_mode", header)
        self.assertIn("direction_role", header)
        self.assertEqual(values[header.index("strategy_family")], "opening_range_breakout")
        self.assertEqual(values[header.index("direction_mode")], "long_only")
        self.assertEqual(values[header.index("direction_role")], "long_leg")

    def test_export_results_writes_expected_text_summary(self) -> None:
        row = make_candidate_result()
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            with patch("quant_system.symbol_research.research_reports_dir", return_value=reports_dir):
                _, txt_path = _export_results("EURUSD", "EURUSD", "test", [row])
            report_text = txt_path.read_text(encoding="utf-8")

        self.assertIn("Top candidate-level winners", report_text)
        self.assertIn(row.name, report_text)

    def test_build_symbol_deployment_preserves_strategy_family_and_direction(self) -> None:
        deployment = build_symbol_deployment(
            profile_name="symbol::eurusd",
            symbol="EURUSD",
            data_symbol="EURUSD",
            broker_symbol="EURUSD",
            research_run_id=1,
            execution_set_id=2,
            execution_validation_summary="accepted",
            symbol_status="live_ready",
            selected_candidates=[make_candidate_row()],
        )

        strategy = deployment.strategies[0]
        self.assertEqual(strategy.strategy_family, "opening_range_breakout")
        self.assertEqual(strategy.direction_mode, "long_only")
        self.assertEqual(strategy.direction_role, "long_leg")

    def test_execution_candidate_row_from_result_preserves_direction_fields(self) -> None:
        result = make_candidate_result()

        row = _execution_candidate_row_from_result("EURUSD", result)

        self.assertEqual(row["strategy_family"], "opening_range_breakout")
        self.assertEqual(row["direction_mode"], "long_only")
        self.assertEqual(row["direction_role"], "long_leg")


if __name__ == "__main__":
    unittest.main()
