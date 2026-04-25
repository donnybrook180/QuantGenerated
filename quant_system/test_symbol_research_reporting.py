from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quant_system.symbol_research import _candidate_failure_reasons, _export_viability_autopsy
from quant_system.test_fixtures import make_candidate_result


class SymbolResearchReportingTests(unittest.TestCase):
    def test_candidate_failure_reasons_reports_validation_failure(self) -> None:
        row = make_candidate_result(
            validation_pnl=-1.0,
            test_pnl=5.0,
            validation_closed_trades=0,
            test_closed_trades=2,
        )

        reasons = _candidate_failure_reasons(row, "EURUSD")

        self.assertTrue(any("validation pnl <= 0" in reason for reason in reasons))
        self.assertTrue(any("validation trades too low" in reason for reason in reasons))

    def test_export_viability_autopsy_writes_summary_file(self) -> None:
        row = make_candidate_result(validation_pnl=-1.0, validation_closed_trades=1)

        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            with patch("quant_system.symbol_research.research_reports_dir", return_value=reports_dir):
                path = _export_viability_autopsy("EURUSD", [row], "accepted")
            text = path.read_text(encoding="utf-8")

        self.assertIn("Viability autopsy: EURUSD", text)
        self.assertIn("Execution validation summary: accepted", text)
        self.assertIn(row.name, text)
        self.assertIn("Top blockers", text)


if __name__ == "__main__":
    unittest.main()
