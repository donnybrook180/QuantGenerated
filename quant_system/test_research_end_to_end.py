from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quant_system.live.deploy import load_symbol_deployment
from quant_system.symbol_research import CandidateSpec, run_symbol_research
from quant_system.test_fixtures import make_candidate_result, make_execution_result, make_feature


class _FakeExperimentStore:
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path

    def record_symbol_research_run(self, **kwargs) -> int:
        self.last_research_run = kwargs
        return 1

    def record_symbol_execution_set(self, **kwargs) -> int:
        self.last_execution_set = kwargs
        return 2

    def promote_symbol_research_candidates(self, **kwargs) -> None:
        self.last_promoted = kwargs
        return None


class ResearchEndToEndTests(unittest.TestCase):
    def test_research_end_to_end_selects_intraday_candidate_for_forex_symbol(self) -> None:
        specs = [
            CandidateSpec(
                name="forex_breakout_momentum",
                description="forex breakout",
                agents=[],
                code_path="quant_system.agents.forex.ForexBreakoutMomentumAgent",
                allowed_variants=("15m_overlap",),
            ),
            CandidateSpec(
                name="forex_short_breakdown_momentum",
                description="forex short breakdown",
                agents=[],
                code_path="quant_system.agents.forex.ForexShortBreakdownMomentumAgent",
                allowed_variants=("15m_overlap",),
            ),
        ]
        results_by_name = {
            "forex_breakout_momentum__15m_overlap": make_candidate_result(
                name="forex_breakout_momentum__15m_overlap",
                code_path="quant_system.agents.forex.ForexBreakoutMomentumAgent",
                realized_pnl=120.0,
                profit_factor=2.1,
                closed_trades=8,
                validation_pnl=40.0,
                validation_profit_factor=1.5,
                validation_closed_trades=3,
                test_pnl=35.0,
                test_profit_factor=1.4,
                test_closed_trades=3,
                walk_forward_windows=2,
                walk_forward_pass_rate_pct=100.0,
                walk_forward_avg_validation_pnl=20.0,
                walk_forward_avg_test_pnl=15.0,
            ),
            "forex_short_breakdown_momentum__15m_overlap": make_candidate_result(
                name="forex_short_breakdown_momentum__15m_overlap",
                code_path="quant_system.agents.forex.ForexShortBreakdownMomentumAgent",
                realized_pnl=20.0,
                profit_factor=1.1,
                closed_trades=4,
                validation_pnl=-5.0,
                validation_profit_factor=0.8,
                validation_closed_trades=1,
                test_pnl=2.0,
                test_profit_factor=1.0,
                test_closed_trades=1,
            ),
        }

        lines, reports_dir, deploy_dir = self._execute_fake_research(
            symbol="EURUSD",
            feature_variants={"15m_overlap": [make_feature(index=0, symbol="EURUSD")]},
            specs=specs,
            results_by_name=results_by_name,
            evaluator=lambda candidate_set: (
                make_execution_result(realized_pnl=120.0, profit_factor=2.0, trades=8, closed_trade_pnls=[40.0, -10.0, 35.0, 55.0]),
                "test",
                "forex_breakout_momentum__15m_overlap@15m_overlap",
            ),
        )

        self.assertIn("Best candidate: forex_breakout_momentum__15m_overlap", lines)
        self.assertIn("Recommended active agents: forex_breakout_momentum__15m_overlap", lines)
        deployment = load_symbol_deployment(deploy_dir / "eurusd" / "live.json")
        self.assertEqual(len(deployment.strategies), 1)
        self.assertEqual(deployment.strategies[0].candidate_name, "forex_breakout_momentum__15m_overlap")
        self.assertEqual(deployment.strategies[0].variant_label, "15m_overlap")
        self.assertTrue((reports_dir / "eurusd" / "reports" / "symbol_research.csv").exists())

    def test_research_end_to_end_selects_4h_candidate_for_supported_symbol(self) -> None:
        specs = [
            CandidateSpec(
                name="trend",
                description="trend",
                agents=[],
                code_path="quant_system.agents.trend.TrendAgent",
                allowed_variants=("15m_overlap", "4h_overlap"),
            ),
        ]
        results_by_name = {
            "trend__15m_overlap": make_candidate_result(
                name="trend__15m_overlap",
                code_path="quant_system.agents.trend.TrendAgent",
                realized_pnl=50.0,
                profit_factor=1.4,
                closed_trades=6,
                validation_pnl=10.0,
                validation_closed_trades=2,
                test_pnl=8.0,
                test_closed_trades=2,
                walk_forward_windows=1,
                walk_forward_pass_rate_pct=50.0,
            ),
            "trend__4h_overlap": make_candidate_result(
                name="trend__4h_overlap",
                code_path="quant_system.agents.trend.TrendAgent",
                realized_pnl=600.0,
                profit_factor=2.4,
                closed_trades=10,
                validation_pnl=120.0,
                validation_profit_factor=1.7,
                validation_closed_trades=3,
                test_pnl=140.0,
                test_profit_factor=1.8,
                test_closed_trades=3,
                walk_forward_windows=2,
                walk_forward_pass_rate_pct=100.0,
                walk_forward_avg_validation_pnl=60.0,
                walk_forward_avg_test_pnl=70.0,
                strategy_family="trend",
                direction_mode="both",
                direction_role="combined",
            ),
        }
        results_by_name["trend__4h_overlap"].variant_label = "4h_overlap"
        results_by_name["trend__4h_overlap"].timeframe_label = "4h"
        results_by_name["trend__4h_overlap"].session_label = "overlap"

        lines, reports_dir, deploy_dir = self._execute_fake_research(
            symbol="XAUUSD",
            feature_variants={
                "15m_overlap": [make_feature(index=0, symbol="XAUUSD")],
                "4h_overlap": [make_feature(index=1, symbol="XAUUSD")],
            },
            specs=specs,
            results_by_name=results_by_name,
            evaluator=lambda candidate_set: (
                make_execution_result(realized_pnl=600.0, profit_factor=2.4, trades=10, closed_trade_pnls=[150.0, -25.0, 175.0, 300.0]),
                "test",
                "trend__4h_overlap@4h_overlap",
            ),
        )

        self.assertIn("Best candidate: trend__4h_overlap", lines)
        deployment = load_symbol_deployment(deploy_dir / "xauusd" / "live.json")
        self.assertEqual(deployment.strategies[0].variant_label, "4h_overlap")
        csv_text = (reports_dir / "xauusd" / "reports" / "symbol_research.csv").read_text(encoding="utf-8")
        self.assertIn("trend__4h_overlap", csv_text)
        self.assertIn(",4h_overlap,4h,overlap,", csv_text)

    def test_research_end_to_end_selects_family_both_combo_when_long_and_short_are_complementary(self) -> None:
        specs = [
            CandidateSpec(
                name="opening_range_breakout",
                description="orb long",
                agents=[],
                code_path="quant_system.agents.strategies.OpeningRangeBreakoutAgent",
                allowed_variants=("15m_overlap",),
            ),
            CandidateSpec(
                name="opening_range_short_breakdown",
                description="orb short",
                agents=[],
                code_path="quant_system.agents.strategies.OpeningRangeShortBreakdownAgent",
                allowed_variants=("15m_overlap",),
            ),
        ]
        long_result = make_candidate_result(
            name="opening_range_breakout__15m_overlap",
            code_path="quant_system.agents.strategies.OpeningRangeBreakoutAgent",
            realized_pnl=60.0,
            profit_factor=1.5,
            closed_trades=6,
            validation_pnl=20.0,
            validation_closed_trades=2,
            test_pnl=18.0,
            test_closed_trades=2,
            walk_forward_windows=1,
            walk_forward_pass_rate_pct=100.0,
            strategy_family="opening_range_breakout",
            direction_mode="long_only",
            direction_role="long_leg",
        )
        short_result = make_candidate_result(
            name="opening_range_short_breakdown__15m_overlap",
            code_path="quant_system.agents.strategies.OpeningRangeShortBreakdownAgent",
            realized_pnl=55.0,
            profit_factor=1.4,
            closed_trades=6,
            validation_pnl=18.0,
            validation_closed_trades=2,
            test_pnl=16.0,
            test_closed_trades=2,
            walk_forward_windows=1,
            walk_forward_pass_rate_pct=100.0,
            strategy_family="opening_range_breakout",
            direction_mode="short_only",
            direction_role="short_leg",
        )
        results_by_name = {
            long_result.name: long_result,
            short_result.name: short_result,
        }

        def evaluator(candidate_set):
            if len(candidate_set) == 2:
                return (
                    make_execution_result(realized_pnl=180.0, profit_factor=2.2, trades=10, closed_trade_pnls=[70.0, -10.0, 60.0, 60.0]),
                    "test",
                    "family_both_opening_range_breakout",
                )
            return (
                make_execution_result(realized_pnl=50.0, profit_factor=1.2, trades=4, closed_trade_pnls=[20.0, -10.0, 40.0]),
                "test",
                "single",
            )

        lines, _reports_dir, deploy_dir = self._execute_fake_research(
            symbol="EURUSD",
            feature_variants={"15m_overlap": [make_feature(index=0, symbol="EURUSD")]},
            specs=specs,
            results_by_name=results_by_name,
            evaluator=evaluator,
        )

        self.assertTrue(any("Execution set: opening_range_breakout__15m_overlap, opening_range_short_breakdown__15m_overlap" in line for line in lines))
        deployment = load_symbol_deployment(deploy_dir / "eurusd" / "live.json")
        self.assertEqual(len(deployment.strategies), 2)

    def test_research_end_to_end_returns_research_only_when_no_candidate_is_viable(self) -> None:
        specs = [
            CandidateSpec(
                name="mean_reversion",
                description="mean reversion",
                agents=[],
                code_path="quant_system.agents.trend.MeanReversionAgent",
                allowed_variants=("15m_overlap",),
            ),
        ]
        reject_result = make_candidate_result(
            name="mean_reversion__15m_overlap",
            code_path="quant_system.agents.trend.MeanReversionAgent",
            realized_pnl=-10.0,
            profit_factor=0.8,
            closed_trades=3,
            validation_pnl=-5.0,
            validation_closed_trades=1,
            test_pnl=-3.0,
            test_closed_trades=1,
            walk_forward_windows=0,
            walk_forward_pass_rate_pct=0.0,
        )

        lines, _reports_dir, deploy_dir = self._execute_fake_research(
            symbol="US100",
            feature_variants={"15m_overlap": [make_feature(index=0, symbol="US100")]},
            specs=specs,
            results_by_name={reject_result.name: reject_result},
            evaluator=lambda candidate_set: (
                make_execution_result(realized_pnl=-25.0, profit_factor=0.7, trades=3, closed_trade_pnls=[-10.0, -5.0, -10.0]),
                "test",
                "rejected",
            ),
        )

        self.assertIn("Best candidate: none", lines)
        self.assertIn("Recommended active agents: none", lines)
        self.assertIn("Symbol status: research_only", lines)
        deployment = load_symbol_deployment(deploy_dir / "us100" / "live.json")
        self.assertEqual(deployment.symbol_status, "research_only")
        self.assertEqual(len(deployment.strategies), 0)

    def test_research_end_to_end_filters_weak_specialist_out_of_live_deployment(self) -> None:
        specs = [
            CandidateSpec(
                name="btc_specialist_candidate",
                description="btc specialist",
                agents=[],
                code_path="quant_system.agents.crypto.CryptoTrendPullbackAgent",
                allowed_variants=("15m_us",),
            ),
        ]
        specialist_result = make_candidate_result(
            name="btc_specialist_candidate__15m_us",
            code_path="quant_system.agents.crypto.CryptoTrendPullbackAgent",
            realized_pnl=25.0,
            profit_factor=1.4,
            closed_trades=5,
            validation_pnl=0.0,
            validation_closed_trades=0,
            test_pnl=0.0,
            test_closed_trades=0,
            walk_forward_windows=1,
            walk_forward_pass_rate_pct=0.0,
            walk_forward_avg_validation_pnl=5.0,
            walk_forward_avg_test_pnl=0.0,
            best_regime="trend_up_vol_high",
            best_regime_pnl=25.0,
            regime_stability_score=1.0,
            regime_loss_ratio=0.0,
            best_trade_share_pct=80.0,
            equity_quality_score=0.5,
            mc_pnl_p05=3.0,
            strategy_family="crypto_trend_pullback",
            direction_mode="long_only",
            direction_role="long_leg",
        )
        specialist_result.sparse_strategy = True

        lines, _reports_dir, deploy_dir = self._execute_fake_research(
            symbol="BTC",
            feature_variants={"15m_us": [make_feature(index=0, symbol="BTC")]},
            specs=specs,
            results_by_name={specialist_result.name: specialist_result},
            evaluator=lambda candidate_set: (
                make_execution_result(realized_pnl=25.0, profit_factor=1.2, trades=5, closed_trade_pnls=[10.0, -5.0, 8.0, 6.0, 6.0]),
                "test",
                "btc_specialist_candidate__15m_us@15m_us",
            ),
        )

        self.assertIn("Symbol status: research_only", lines)
        deployment = load_symbol_deployment(deploy_dir / "btc" / "live.json")
        self.assertEqual(deployment.symbol_status, "research_only")
        self.assertEqual(len(deployment.strategies), 0)

    def test_research_end_to_end_writes_blue_guardian_report_and_deployment_reasons(self) -> None:
        specs = [
            CandidateSpec(
                name="forex_breakout_momentum",
                description="forex breakout",
                agents=[],
                code_path="quant_system.agents.forex.ForexBreakoutMomentumAgent",
                allowed_variants=("15m_overlap",),
            ),
            CandidateSpec(
                name="forex_short_breakdown_momentum",
                description="forex short breakdown",
                agents=[],
                code_path="quant_system.agents.forex.ForexShortBreakdownMomentumAgent",
                allowed_variants=("15m_overlap",),
            ),
        ]
        caution_result = make_candidate_result(
            name="forex_breakout_momentum__15m_overlap",
            code_path="quant_system.agents.forex.ForexBreakoutMomentumAgent",
            realized_pnl=95.0,
            profit_factor=1.9,
            closed_trades=7,
            validation_pnl=28.0,
            validation_profit_factor=1.4,
            validation_closed_trades=2,
            test_pnl=24.0,
            test_profit_factor=1.3,
            test_closed_trades=2,
            walk_forward_windows=2,
            walk_forward_pass_rate_pct=100.0,
            walk_forward_avg_validation_pnl=14.0,
            walk_forward_avg_test_pnl=12.0,
            strategy_family="forex_breakout_momentum",
            direction_mode="long_only",
            direction_role="long_leg",
        )
        caution_result.prop_fit_label = "caution"
        caution_result.prop_fit_reasons = ("news_window_trade_share_elevated",)
        caution_result.news_window_trade_share = 0.32
        rejected_result = make_candidate_result(
            name="forex_short_breakdown_momentum__15m_overlap",
            code_path="quant_system.agents.forex.ForexShortBreakdownMomentumAgent",
            realized_pnl=15.0,
            profit_factor=0.8,
            closed_trades=4,
            validation_pnl=-4.0,
            validation_profit_factor=0.7,
            validation_closed_trades=1,
            test_pnl=-2.0,
            test_profit_factor=0.8,
            test_closed_trades=1,
            walk_forward_windows=0,
            walk_forward_pass_rate_pct=0.0,
            strategy_family="forex_short_breakdown_momentum",
            direction_mode="short_only",
            direction_role="short_leg",
        )
        rejected_result.interpreter_fit_reasons = ("blocked_by_interpreter_risk_high",)
        rejected_result.blocked_by_interpreter_risk = 0.82
        rejected_result.common_live_regime_fit = 0.12
        results_by_name = {
            caution_result.name: caution_result,
            rejected_result.name: rejected_result,
        }

        lines, reports_dir, deploy_dir = self._execute_fake_research(
            symbol="EURUSD",
            feature_variants={"15m_overlap": [make_feature(index=0, symbol="EURUSD")]},
            specs=specs,
            results_by_name=results_by_name,
            evaluator=lambda candidate_set: (
                make_execution_result(realized_pnl=95.0, profit_factor=1.8, trades=7, closed_trade_pnls=[30.0, -8.0, 25.0, 20.0, 28.0]),
                "test",
                "forex_breakout_momentum__15m_overlap@15m_overlap",
            ),
        )

        self.assertIn("Recommended active agents: forex_breakout_momentum__15m_overlap", lines)
        report_text = (reports_dir / "eurusd" / "reports" / "symbol_research.txt").read_text(encoding="utf-8")
        self.assertIn("broker_data_summary", report_text)
        self.assertIn("why_promoted_for_blue_guardian", report_text)
        self.assertIn("forex_breakout_momentum__15m_overlap", report_text)
        self.assertIn("why_rejected_for_blue_guardian", report_text)
        self.assertIn("forex_short_breakdown_momentum__15m_overlap", report_text)
        deployment = load_symbol_deployment(deploy_dir / "eurusd" / "live.json")
        self.assertEqual(deployment.venue_basis, "blue_guardian_mt5")
        self.assertEqual(deployment.prop_viability_label, "caution")
        self.assertEqual(tuple(deployment.top_caution_reasons), ("news_window_trade_share_elevated",))
        self.assertEqual(tuple(deployment.top_rejection_reasons), ())

    def _execute_fake_research(
        self,
        *,
        symbol: str,
        feature_variants: dict[str, list[object]],
        specs: list[CandidateSpec],
        results_by_name: dict[str, object],
        evaluator,
    ) -> tuple[list[str], Path, Path]:
        fake_store = _FakeExperimentStore("ignored.duckdb")

        def fake_run_candidate_with_splits(config, feature_rows, spec, archetype, artifact_prefix):
            _ = config, feature_rows, archetype, artifact_prefix
            result = results_by_name.get(spec.name)
            if result is None:
                raise AssertionError(f"Missing fake result for {spec.name}")
            materialized = copy.deepcopy(result)
            if not materialized.variant_label:
                materialized.variant_label = spec.variant_label
            if not materialized.timeframe_label:
                materialized.timeframe_label = spec.timeframe_label
            if not materialized.session_label:
                materialized.session_label = spec.session_label
            if not materialized.regime_filter_label:
                materialized.regime_filter_label = spec.regime_filter_label
            if not materialized.cross_filter_label:
                materialized.cross_filter_label = spec.cross_filter_label
            return materialized

        def fake_eval(config, profile_symbol, data_symbol, candidate_set):
            _ = config, profile_symbol, data_symbol
            return evaluator(candidate_set)

        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        reports_root = root / "research"
        deploy_root = root / "deploy"
        reports_root.mkdir(parents=True, exist_ok=True)
        deploy_root.mkdir(parents=True, exist_ok=True)

        with patch.dict("os.environ", {"PROP_BROKER": "blue_guardian"}), patch(
            "quant_system.symbol_research._build_symbol_feature_variants",
            return_value=(feature_variants, "test", "full"),
        ), patch(
            "quant_system.symbol_research._candidate_specs",
            return_value=specs,
        ), patch(
            "quant_system.symbol_research._exit_family_specs",
            return_value=[],
        ), patch(
            "quant_system.symbol_research._parameter_sweep_specs",
            return_value=[],
        ), patch(
            "quant_system.symbol_research._auto_improvement_specs",
            return_value=[],
        ), patch(
            "quant_system.symbol_research._second_pass_specs",
            return_value=[],
        ), patch(
            "quant_system.symbol_research._regime_improvement_specs",
            return_value=[],
        ), patch(
            "quant_system.symbol_research._autopsy_improvement_specs",
            return_value=[],
        ), patch(
            "quant_system.symbol_research._near_miss_optimizer_specs",
            return_value=[],
        ), patch(
            "quant_system.symbol_research._near_miss_local_optimizer",
            return_value=([], []),
        ), patch(
            "quant_system.symbol_research._combined_specs",
            return_value=[],
        ), patch(
            "quant_system.symbol_research._run_candidate_with_splits",
            side_effect=fake_run_candidate_with_splits,
        ), patch(
            "quant_system.symbol_research._evaluate_execution_candidate_set",
            side_effect=fake_eval,
        ), patch(
            "quant_system.symbol_research.plot_symbol_research",
            return_value=[],
        ), patch(
            "quant_system.symbol_research.ExperimentStore",
            return_value=fake_store,
        ), patch(
            "quant_system.symbol_research.research_reports_dir",
            side_effect=lambda s: (reports_root / s.lower() / "reports").mkdir(parents=True, exist_ok=True) or (reports_root / s.lower() / "reports"),
        ), patch(
            "quant_system.live.deploy.deploy_symbol_dir",
            side_effect=lambda s: (deploy_root / s.lower()).mkdir(parents=True, exist_ok=True) or (deploy_root / s.lower()),
        ):
            lines = run_symbol_research(symbol)
            return lines, reports_root, deploy_root


if __name__ == "__main__":
    unittest.main()
