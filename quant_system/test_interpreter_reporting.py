from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from quant_system.interpreter.models import InterpreterState
from quant_system.interpreter.reporting import generate_market_interpreter_report


def _state(symbol: str, *, no_trade_reason: str = "") -> InterpreterState:
    return InterpreterState(
        symbol=symbol,
        broker_symbol=symbol,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        legacy_regime_label="calm_range",
        unified_regime_label="orderly_range",
        macro_regime="neutral",
        session_regime="midday_chop",
        structure_regime="range_rotation",
        volatility_regime="normal",
        execution_regime="acceptable",
        crowding_regime="neutral",
        directional_bias="neutral",
        setup_quality=0.5,
        execution_quality=0.6,
        confidence=0.55,
        risk_posture="normal" if not no_trade_reason else "defensive",
        allowed_archetypes=["mean_reversion"] if not no_trade_reason else [],
        blocked_archetypes=["breakout"],
        no_trade_reason=no_trade_reason,
        explanation="test explanation",
    )


class InterpreterReportingTests(unittest.TestCase):
    def test_generate_market_interpreter_report_handles_no_live_deployments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            reports_dir.mkdir(parents=True, exist_ok=True)
            with patch("quant_system.interpreter.reporting.system_reports_dir", return_value=reports_dir), patch(
                "quant_system.interpreter.reporting.build_all_market_interpreter_states",
                return_value=[],
            ):
                report_path = generate_market_interpreter_report()

            report_text = report_path.read_text(encoding="utf-8")
            report_json = json.loads(report_path.with_suffix(".json").read_text(encoding="utf-8"))

        self.assertIn("No live deployments found.", report_text)
        self.assertEqual(report_json["states"], [])

    def test_generate_market_interpreter_report_writes_state_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            reports_dir = base / "reports"
            live_dir = base / "live"
            reports_dir.mkdir(parents=True, exist_ok=True)
            def _live_symbol_dir(symbol: str) -> Path:
                path = live_dir / symbol.lower()
                path.mkdir(parents=True, exist_ok=True)
                return path
            with patch("quant_system.interpreter.reporting.system_reports_dir", return_value=reports_dir), patch(
                "quant_system.interpreter.reporting.live_symbol_dir",
                side_effect=_live_symbol_dir,
            ), patch(
                "quant_system.interpreter.reporting.build_all_market_interpreter_states",
                return_value=[_state("EURUSD"), _state("GBPUSD", no_trade_reason="pre_event_window")],
            ):
                report_path = generate_market_interpreter_report()

            report_text = report_path.read_text(encoding="utf-8")
            report_json = json.loads(report_path.with_suffix(".json").read_text(encoding="utf-8"))
            artifacts = sorted(live_dir.glob("*/market_interpreter.json"))

        self.assertIn("EURUSD: bias=neutral", report_text)
        self.assertIn("no_trade_reason: pre_event_window", report_text)
        self.assertEqual(len(artifacts), 2)
        self.assertEqual(len(report_json["states"]), 2)


if __name__ == "__main__":
    unittest.main()
