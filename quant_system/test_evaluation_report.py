from __future__ import annotations

import unittest

from quant_system.config import FTMOEvaluationConfig, InstrumentConfig, RiskConfig
from quant_system.evaluation.report import build_ftmo_report
from quant_system.test_fixtures import make_execution_result


class EvaluationReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.initial_cash = 100_000.0
        self.risk = RiskConfig(max_total_drawdown_pct=0.10)
        self.ftmo = FTMOEvaluationConfig(
            profit_target_pct=0.10,
            min_win_rate_pct=35.0,
            min_profit_factor=1.2,
            min_trades=10,
        )
        self.instrument = InstrumentConfig()

    def test_build_ftmo_report_passes_when_all_thresholds_are_met(self) -> None:
        result = make_execution_result(
            initial_cash=self.initial_cash,
            realized_pnl=12_000.0,
            max_drawdown=0.05,
            win_rate_pct=45.0,
            profit_factor=1.5,
            closed_trade_pnls=[500.0] * 10,
        )

        report = build_ftmo_report(result, self.initial_cash, self.risk, self.ftmo, self.instrument)

        self.assertTrue(report.passed)
        self.assertEqual(report.reasons, [])

    def test_build_ftmo_report_fails_on_profit_target(self) -> None:
        result = make_execution_result(initial_cash=self.initial_cash, realized_pnl=5_000.0, closed_trade_pnls=[250.0] * 10)

        report = build_ftmo_report(result, self.initial_cash, self.risk, self.ftmo, self.instrument)

        self.assertFalse(report.passed)
        self.assertTrue(any("profit target not met" in reason for reason in report.reasons))

    def test_build_ftmo_report_fails_on_drawdown_breach(self) -> None:
        result = make_execution_result(initial_cash=self.initial_cash, max_drawdown=0.12, closed_trade_pnls=[500.0] * 10)

        report = build_ftmo_report(result, self.initial_cash, self.risk, self.ftmo, self.instrument)

        self.assertFalse(report.passed)
        self.assertTrue(any("max drawdown breached" in reason for reason in report.reasons))

    def test_build_ftmo_report_fails_on_win_rate(self) -> None:
        result = make_execution_result(initial_cash=self.initial_cash, win_rate_pct=30.0, closed_trade_pnls=[500.0] * 10)

        report = build_ftmo_report(result, self.initial_cash, self.risk, self.ftmo, self.instrument)

        self.assertFalse(report.passed)
        self.assertTrue(any("win rate too low" in reason for reason in report.reasons))

    def test_build_ftmo_report_fails_on_profit_factor(self) -> None:
        result = make_execution_result(initial_cash=self.initial_cash, profit_factor=1.1, closed_trade_pnls=[500.0] * 10)

        report = build_ftmo_report(result, self.initial_cash, self.risk, self.ftmo, self.instrument)

        self.assertFalse(report.passed)
        self.assertTrue(any("profit factor too low" in reason for reason in report.reasons))

    def test_build_ftmo_report_fails_on_min_trades(self) -> None:
        result = make_execution_result(initial_cash=self.initial_cash, closed_trade_pnls=[500.0] * 9)

        report = build_ftmo_report(result, self.initial_cash, self.risk, self.ftmo, self.instrument)

        self.assertFalse(report.passed)
        self.assertTrue(any("too few closed trades" in reason for reason in report.reasons))

    def test_build_ftmo_report_fails_when_kill_switch_triggered(self) -> None:
        result = make_execution_result(initial_cash=self.initial_cash, locked=True, closed_trade_pnls=[500.0] * 10)

        report = build_ftmo_report(result, self.initial_cash, self.risk, self.ftmo, self.instrument)

        self.assertFalse(report.passed)
        self.assertIn("kill-switch triggered", report.reasons)

    def test_build_ftmo_report_accepts_exact_boundary_values(self) -> None:
        result = make_execution_result(
            initial_cash=self.initial_cash,
            ending_equity=110_000.0,
            realized_pnl=10_000.0,
            max_drawdown=0.10,
            win_rate_pct=35.0,
            profit_factor=1.2,
            closed_trade_pnls=[500.0] * 10,
        )

        report = build_ftmo_report(result, self.initial_cash, self.risk, self.ftmo, self.instrument)

        self.assertTrue(report.passed)
        self.assertAlmostEqual(report.net_return_pct, 10.0, places=6)
        self.assertAlmostEqual(report.max_drawdown_pct, 10.0, places=6)


if __name__ == "__main__":
    unittest.main()
