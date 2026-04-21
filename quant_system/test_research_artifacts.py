from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quant_system.plotting import plot_symbol_research
from quant_system.test_fixtures import make_candidate_result


def _write_trade_log(path: Path, pnls: list[float]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["exit_timestamp", "entry_reason", "pnl"])
        for index, pnl in enumerate(pnls):
            writer.writerow([f"2026-04-21T0{index}:00:00+00:00", "test_candidate", pnl])


class ResearchArtifactsTests(unittest.TestCase):
    def test_best_candidate_equity_plot_uses_best_row_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plot_dir = root / "plots"
            plot_dir.mkdir(parents=True, exist_ok=True)
            missing_log = root / "missing.csv"
            best_log = root / "best.csv"
            _write_trade_log(best_log, [10.0, -5.0, 20.0])

            top_row = make_candidate_result(name="top_candidate", realized_pnl=200.0)
            top_row.trade_log_path = str(missing_log)
            best_row = make_candidate_result(name="best_candidate", realized_pnl=100.0)
            best_row.trade_log_path = str(best_log)

            with patch("quant_system.plotting.research_plots_dir", return_value=plot_dir):
                paths = plot_symbol_research("XAUUSD", [top_row, best_row], best_row=best_row)
                self.assertIn(plot_dir / "best_candidate_equity.png", paths)
                self.assertTrue((plot_dir / "best_candidate_equity.png").exists())

    def test_execution_set_equity_plot_is_removed_when_new_run_has_no_execution_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plot_dir = root / "plots"
            plot_dir.mkdir(parents=True, exist_ok=True)
            stale = plot_dir / "execution_set_equity.png"
            stale.write_text("stale", encoding="utf-8")
            row = make_candidate_result(name="candidate", realized_pnl=50.0)
            best_log = root / "best.csv"
            _write_trade_log(best_log, [5.0, -2.0])
            row.trade_log_path = str(best_log)

            with patch("quant_system.plotting.research_plots_dir", return_value=plot_dir):
                plot_symbol_research("EURUSD", [row], best_row=row, execution_rows=[])
                self.assertFalse(stale.exists())

    def test_execution_set_equity_plot_is_written_when_execution_rows_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plot_dir = root / "plots"
            plot_dir.mkdir(parents=True, exist_ok=True)
            best_log = root / "best.csv"
            exec_log = root / "exec.csv"
            _write_trade_log(best_log, [10.0, 5.0])
            _write_trade_log(exec_log, [7.0, -3.0, 9.0])
            best_row = make_candidate_result(name="best_candidate")
            best_row.trade_log_path = str(best_log)
            exec_row = make_candidate_result(name="exec_candidate")
            exec_row.trade_log_path = str(exec_log)

            with patch("quant_system.plotting.research_plots_dir", return_value=plot_dir):
                paths = plot_symbol_research("JP225", [best_row], best_row=best_row, execution_rows=[exec_row])
                self.assertIn(plot_dir / "execution_set_equity.png", paths)
                self.assertTrue((plot_dir / "execution_set_equity.png").exists())


if __name__ == "__main__":
    unittest.main()
