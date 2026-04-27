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
        row.variant_label = "4h_overlap"
        row.timeframe_label = "4h"
        row.session_label = "overlap"
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
        self.assertIn("variant_label", header)
        self.assertIn("timeframe_label", header)
        self.assertIn("session_label", header)
        self.assertIn("signal_quality_score", header)
        self.assertIn("prop_viability_score", header)
        self.assertIn("prop_viability_label", header)
        self.assertIn("prop_viability_pass", header)
        self.assertIn("avg_hold_hours", header)
        self.assertIn("estimated_swap_drag_per_trade", header)
        self.assertIn("swap_adjusted_expectancy", header)
        self.assertIn("estimated_gross_pnl_before_swap", header)
        self.assertIn("estimated_net_pnl_delta_from_swap", header)
        self.assertIn("stress_expectancy_mild", header)
        self.assertIn("stress_pf_medium", header)
        self.assertIn("stress_survival_score", header)
        self.assertIn("prop_fit_score", header)
        self.assertIn("prop_fit_label", header)
        self.assertIn("news_window_trade_share", header)
        self.assertIn("interpreter_fit_score", header)
        self.assertIn("common_live_regime_fit", header)
        self.assertIn("blocked_by_interpreter_risk", header)
        self.assertEqual(values[header.index("variant_label")], "4h_overlap")
        self.assertEqual(values[header.index("timeframe_label")], "4h")
        self.assertEqual(values[header.index("session_label")], "overlap")
        self.assertEqual(values[header.index("strategy_family")], "opening_range_breakout")
        self.assertEqual(values[header.index("direction_mode")], "long_only")
        self.assertEqual(values[header.index("direction_role")], "long_leg")
        self.assertTrue(float(values[header.index("signal_quality_score")]) > 0.0)
        self.assertIn(values[header.index("prop_viability_label")], {"pass", "caution", "fail"})

    def test_export_results_writes_expected_text_summary(self) -> None:
        row = make_candidate_result()
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            with patch("quant_system.symbol_research.research_reports_dir", return_value=reports_dir):
                _, txt_path = _export_results("EURUSD", "EURUSD", "test", [row])
            report_text = txt_path.read_text(encoding="utf-8")

        self.assertIn("Top candidate-level winners", report_text)
        self.assertIn(row.name, report_text)
        self.assertIn("strategy_scope: family=opening_range_breakout direction=long_only role=long_leg", report_text)
        self.assertIn("blue_guardian:", report_text)
        self.assertIn("pnl_netting:", report_text)
        self.assertIn("swap_drag:", report_text)
        self.assertIn("execution_stress:", report_text)
        self.assertIn("prop_fit:", report_text)
        self.assertIn("interpreter_fit:", report_text)
        self.assertIn("swap_drag_summary", report_text)
        self.assertIn("execution_stress_summary", report_text)
        self.assertIn("prop_fit_summary", report_text)
        self.assertIn("interpreter_fit_summary", report_text)
        self.assertIn("why_promoted_for_blue_guardian", report_text)
        self.assertIn("why_rejected_for_blue_guardian", report_text)
        self.assertIn("estimated_total_swap_drag", report_text)

    def test_export_results_writes_broker_data_summary_when_provided(self) -> None:
        row = make_candidate_result()
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            with patch("quant_system.symbol_research.research_reports_dir", return_value=reports_dir):
                from quant_system.research.exports import export_results

                _csv_path, txt_path = export_results(
                    "EURUSD",
                    "EURUSD",
                    "mt5",
                    [row],
                    reports_dir_fn=lambda _symbol: reports_dir,
                    strategy_family_fn=lambda item: item.strategy_family,
                    direction_mode_fn=lambda item: item.direction_mode,
                    direction_role_fn=lambda item: item.direction_role,
                    execution_candidate_row_from_result_fn=lambda _symbol, _row: _execution_candidate_row_from_result("EURUSD", row),
                    build_execution_policy_from_candidate_row_fn=lambda candidate_row: {"promotion_tier": candidate_row["promotion_tier"], "policy_summary": "tier=core"},
                    summarize_unified_regime_fn=lambda value: value,
                    meets_viability_fn=lambda _row, _symbol: True,
                    promotion_tier_for_row_fn=lambda _row, _symbol: "core",
                    broker_data_summary={
                        "broker_data_source": "blue_guardian_mt5",
                        "broker_symbol": "EURUSD",
                        "history_bars_loaded": 1200,
                        "history_window_start": "2026-01-01T00:00:00+00:00",
                        "history_window_end": "2026-03-01T00:00:00+00:00",
                        "missing_bar_warnings": ("detected_2_timestamp_gaps_gt_5m",),
                        "session_alignment_notes": "continuous MT5-style stream; broker-backed research path",
                        "contract_spec_notes": "resolved_symbol=EURUSD point=0.00001000 contract_size=100000.00",
                    },
                )
            report_text = txt_path.read_text(encoding="utf-8")

        self.assertIn("broker_data_summary", report_text)
        self.assertIn("broker_data_source: blue_guardian_mt5", report_text)
        self.assertIn("history_bars_loaded: 1200", report_text)

    def test_export_results_explains_blue_guardian_promotion_and_rejection_reasons(self) -> None:
        promoted = make_candidate_result(name="promoted_candidate")
        rejected = make_candidate_result(
            name="rejected_candidate",
            validation_pnl=-2.0,
            test_pnl=-1.0,
            validation_closed_trades=0,
            test_closed_trades=0,
            profit_factor=0.8,
            mc_pnl_p05=-1.0,
        )
        rejected.prop_fit_label = "fail"
        rejected.prop_fit_reasons = ("execution_dependency_flag",)
        rejected.interpreter_fit_reasons = ("blocked_by_interpreter_risk_high",)

        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            with patch("quant_system.symbol_research.research_reports_dir", return_value=reports_dir):
                _, txt_path = _export_results("EURUSD", "EURUSD", "test", [promoted, rejected])
            report_text = txt_path.read_text(encoding="utf-8")

        self.assertIn("why_promoted_for_blue_guardian", report_text)
        self.assertIn("promoted_candidate", report_text)
        self.assertIn("why_rejected_for_blue_guardian", report_text)
        self.assertIn("rejected_candidate", report_text)

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
            venue_key="blue_guardian",
        )

        strategy = deployment.strategies[0]
        self.assertEqual(strategy.strategy_family, "opening_range_breakout")
        self.assertEqual(strategy.direction_mode, "long_only")
        self.assertEqual(strategy.direction_role, "long_leg")
        self.assertEqual(strategy.prop_viability_label, "pass")
        self.assertEqual(deployment.venue_basis, "blue_guardian_mt5")
        self.assertEqual(deployment.prop_viability_label, "pass")
        self.assertEqual(tuple(deployment.top_caution_reasons), ())
        self.assertEqual(tuple(deployment.top_rejection_reasons), ())

    def test_build_symbol_deployment_surfaces_top_caution_and_rejection_reasons(self) -> None:
        deployment = build_symbol_deployment(
            profile_name="symbol::eurusd",
            symbol="EURUSD",
            data_symbol="EURUSD",
            broker_symbol="EURUSD",
            research_run_id=1,
            execution_set_id=2,
            execution_validation_summary="accepted",
            symbol_status="reduced_risk_only",
            selected_candidates=[
                make_candidate_row(
                    candidate_name="caution_candidate",
                    prop_viability_label="caution",
                    prop_viability_pass=True,
                    prop_viability_reasons=("swap_drag_material_to_expectancy", "blocked_by_interpreter_risk_elevated"),
                ),
                make_candidate_row(
                    candidate_name="failed_candidate",
                    prop_viability_label="fail",
                    prop_viability_pass=False,
                    prop_viability_reasons=("stress_medium_breaks_viability", "stress_medium_breaks_viability"),
                ),
            ],
            venue_key="blue_guardian",
        )

        self.assertEqual(tuple(deployment.top_caution_reasons), ("blocked_by_interpreter_risk_elevated", "swap_drag_material_to_expectancy"))
        self.assertEqual(tuple(deployment.top_rejection_reasons), ("stress_medium_breaks_viability",))

    def test_execution_candidate_row_from_result_preserves_direction_fields(self) -> None:
        result = make_candidate_result()

        row = _execution_candidate_row_from_result("EURUSD", result)

        self.assertEqual(row["strategy_family"], "opening_range_breakout")
        self.assertEqual(row["direction_mode"], "long_only")
        self.assertEqual(row["direction_role"], "long_leg")
        self.assertIn(row["prop_viability_label"], {"pass", "caution", "fail"})
        self.assertIn("signal_quality_score", row)

    def test_export_results_writes_inferred_strategy_direction_for_legacy_result(self) -> None:
        row = make_candidate_result(
            name="trend__4h_overlap",
            code_path="quant_system.agents.trend.TrendAgent",
            strategy_family="",
            direction_mode="",
            direction_role="",
        )
        row.variant_label = "4h_overlap"
        row.timeframe_label = "4h"
        row.session_label = "overlap"

        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            with patch("quant_system.symbol_research.research_reports_dir", return_value=reports_dir):
                csv_path, _ = _export_results("XAUUSD", "XAUUSD", "test", [row])
            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                reader = list(csv.DictReader(handle))

        self.assertEqual(reader[0]["timeframe_label"], "4h")
        self.assertTrue(reader[0]["strategy_family"])


if __name__ == "__main__":
    unittest.main()
