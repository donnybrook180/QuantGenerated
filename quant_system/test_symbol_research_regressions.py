from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta

from quant_system.config import SystemConfig
from quant_system.data.market_data import DuckDBMarketDataStore
from quant_system.models import MarketBar
from quant_system.symbol_research import (
    _build_execution_candidate_sets,
    _candidate_specs,
    _detect_research_mode,
    _execution_candidate_row,
    _research_variant_plan,
    _with_variant_name,
    CandidateSpec,
    select_execution_candidates,
)


def _make_bar_series(symbol: str, count: int, minutes: int = 5) -> list[MarketBar]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars: list[MarketBar] = []
    for index in range(count):
        close = 40_000.0 + float(index)
        bars.append(
            MarketBar(
                timestamp=start + timedelta(minutes=index * minutes),
                symbol=symbol,
                open=close - 5.0,
                high=close + 10.0,
                low=close - 10.0,
                close=close,
                volume=100.0 + float(index % 10),
            )
        )
    return bars


class SymbolResearchRegressionTests(unittest.TestCase):
    def test_candidate_specs_adds_eurusd_range_rotation_coverage(self) -> None:
        specs = _candidate_specs(SystemConfig(), "EURUSD")
        names = {spec.name for spec in specs}

        self.assertIn("eurusd_range_reversion_europe", names)
        self.assertIn("eurusd_range_reversion_overlap", names)
        self.assertIn("eurusd_london_range_reclaim_selective", names)

        overlap_spec = next(spec for spec in specs if spec.name == "eurusd_range_reversion_overlap")
        self.assertEqual(overlap_spec.allowed_variants, ("15m_overlap",))

    def test_candidate_specs_adds_xauusd_us_reclaim_coverage(self) -> None:
        specs = _candidate_specs(SystemConfig(), "XAUUSD")
        names = {spec.name for spec in specs}

        self.assertIn("xauusd_opening_drive_reclaim", names)
        self.assertIn("xauusd_us_open_range_reclaim", names)
        self.assertIn("xauusd_vwap_reclaim", names)

        us_open_spec = next(spec for spec in specs if spec.name == "xauusd_us_open_range_reclaim")
        self.assertEqual(us_open_spec.allowed_variants, ("5m_us", "15m_us"))
        self.assertEqual(us_open_spec.regime_filter_label, "range_rotation")

    def test_candidate_specs_adds_jp225_open_reversal_coverage(self) -> None:
        specs = _candidate_specs(SystemConfig(), "JP225")
        names = {spec.name for spec in specs}

        self.assertIn("jp225_open_drive_mean_reversion_selective", names)
        self.assertIn("jp225_failed_breakdown_reclaim_open_selective", names)

        open_spec = next(spec for spec in specs if spec.name == "jp225_open_drive_mean_reversion_selective")
        self.assertEqual(open_spec.allowed_variants, ("5m_open", "15m_open"))
        self.assertEqual(open_spec.regime_filter_label, "range_rotation")

    def test_candidate_specs_adds_eu50_mean_reversion_coverage(self) -> None:
        specs = _candidate_specs(SystemConfig(), "EU50")
        names = {spec.name for spec in specs}

        self.assertIn("eu50_europe_mean_reversion_long", names)
        self.assertIn("eu50_europe_mean_reversion_short", names)

        long_spec = next(spec for spec in specs if spec.name == "eu50_europe_mean_reversion_long")
        short_spec = next(spec for spec in specs if spec.name == "eu50_europe_mean_reversion_short")
        self.assertEqual(long_spec.allowed_variants, ("15m_europe", "30m_europe"))
        self.assertEqual(short_spec.allowed_variants, ("15m_europe", "30m_europe"))
        self.assertEqual(long_spec.regime_filter_label, "range_rotation")
        self.assertEqual(short_spec.regime_filter_label, "range_rotation")

    def test_candidate_specs_adds_us500_reclaim_balance_coverage(self) -> None:
        specs = _candidate_specs(SystemConfig(), "US500")
        names = {spec.name for spec in specs}

        self.assertIn("us500_opening_drive_reclaim", names)
        self.assertIn("us500_failed_breakdown_reclaim", names)
        self.assertIn("us500_failed_upside_reject_short", names)

        reclaim_spec = next(spec for spec in specs if spec.name == "us500_failed_breakdown_reclaim")
        reject_spec = next(spec for spec in specs if spec.name == "us500_failed_upside_reject_short")
        self.assertEqual(reclaim_spec.regime_filter_label, "range_rotation")
        self.assertEqual(reject_spec.regime_filter_label, "range_rotation")

    def test_detect_research_mode_accepts_btc_full_from_5m_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = f"{temp_dir}\\test.duckdb"
            store = DuckDBMarketDataStore(database_path)
            store.upsert_bars(
                _make_bar_series("X:BTCUSD", 6_000),
                timeframe="symbol_research_x_btcusd_5_minute",
                source="test",
            )
            store.upsert_bars(
                _make_bar_series("X:BTCUSD", 2_000, minutes=240),
                timeframe="symbol_research_x_btcusd_240_minute",
                source="test",
            )
            config = SystemConfig()
            config.mt5.database_path = database_path
            config.symbol_research.mode = "auto"
            mode = _detect_research_mode(config, "BTC", "X:BTCUSD")
            self.assertEqual(mode, "full")

    def test_execution_candidate_row_preserves_btc_specialist_tier_for_dict_rows(self) -> None:
        row = {
            "candidate_name": "btc_specialist_candidate",
            "symbol": "BTC",
            "code_path": "quant_system.agents.crypto.CryptoTrendPullbackAgent",
            "realized_pnl": 25.0,
            "profit_factor": 1.8,
            "closed_trades": 5,
            "payoff_ratio": 2.0,
            "validation_pnl": 0.0,
            "validation_profit_factor": 0.0,
            "validation_closed_trades": 0,
            "test_pnl": 0.0,
            "test_profit_factor": 0.0,
            "test_closed_trades": 0,
            "walk_forward_windows": 1,
            "walk_forward_pass_rate_pct": 0.0,
            "walk_forward_soft_pass_rate_pct": 0.0,
            "walk_forward_avg_validation_pnl": 5.0,
            "walk_forward_avg_test_pnl": 0.0,
            "best_trade_share_pct": 80.0,
            "equity_quality_score": 0.5,
            "mc_simulations": 500,
            "mc_pnl_p05": 3.0,
            "mc_loss_probability_pct": 0.0,
            "sparse_strategy": True,
            "best_regime": "trend_up_vol_high",
            "best_regime_pnl": 25.0,
            "regime_filter_label": "",
            "regime_stability_score": 1.0,
            "regime_loss_ratio": 0.0,
            "regime_trade_count_by_label": {"trend_up_vol_high": 5},
            "regime_pf_by_label": {"trend_up_vol_high": 1.8},
            "variant_label": "30m_europe",
        }
        candidate_row = _execution_candidate_row("BTC", row)
        self.assertEqual(candidate_row["promotion_tier"], "specialist")
        self.assertTrue(candidate_row["regime_specialist_viable"])

    def test_execution_candidate_row_infers_strategy_family_and_direction(self) -> None:
        row = {
            "candidate_name": "opening_range_short_breakdown",
            "symbol": "EURUSD",
            "code_path": "quant_system.agents.strategies.OpeningRangeShortBreakdownAgent",
            "realized_pnl": 10.0,
            "profit_factor": 1.2,
            "closed_trades": 4,
        }
        candidate_row = _execution_candidate_row("EURUSD", row)
        self.assertEqual(candidate_row["strategy_family"], "opening_range_breakout")
        self.assertEqual(candidate_row["direction_mode"], "short_only")
        self.assertEqual(candidate_row["direction_role"], "short_leg")

    def test_execution_candidate_row_uses_explicit_catalog_for_bidirectional_agent(self) -> None:
        row = {
            "candidate_name": "trend_default",
            "symbol": "EURUSD",
            "code_path": "quant_system.agents.trend.TrendAgent",
            "realized_pnl": 10.0,
            "profit_factor": 1.2,
            "closed_trades": 4,
        }
        candidate_row = _execution_candidate_row("EURUSD", row)
        self.assertTrue(str(candidate_row["strategy_family"]))
        self.assertEqual(candidate_row["direction_mode"], "both")
        self.assertEqual(candidate_row["direction_role"], "combined")

    def test_select_execution_candidates_keeps_one_row_per_strategy_family_direction_choice(self) -> None:
        long_row = {
            "candidate_name": "opening_range_breakout",
            "symbol": "EURUSD",
            "code_path": "quant_system.agents.strategies.OpeningRangeBreakoutAgent",
            "strategy_family": "opening_range_breakout",
            "direction_mode": "long_only",
            "direction_role": "long_leg",
            "realized_pnl": 15.0,
            "profit_factor": 1.3,
            "closed_trades": 5,
            "validation_pnl": 5.0,
            "validation_profit_factor": 1.2,
            "validation_closed_trades": 2,
            "test_pnl": 4.0,
            "test_profit_factor": 1.1,
            "test_closed_trades": 2,
            "walk_forward_windows": 1,
            "walk_forward_pass_rate_pct": 50.0,
            "walk_forward_soft_pass_rate_pct": 50.0,
            "walk_forward_avg_validation_pnl": 2.0,
            "walk_forward_avg_test_pnl": 2.0,
            "best_regime": "trend_up_vol_high",
            "best_regime_pnl": 7.0,
            "best_trade_share_pct": 20.0,
            "equity_quality_score": 0.7,
            "regime_stability_score": 0.6,
            "regime_loss_ratio": 0.4,
            "combo_outperformance_score": 0.0,
            "mc_simulations": 500,
            "mc_pnl_p05": 2.0,
            "mc_loss_probability_pct": 0.0,
        }
        short_row = {
            **long_row,
            "candidate_name": "opening_range_short_breakdown",
            "code_path": "quant_system.agents.strategies.OpeningRangeShortBreakdownAgent",
            "direction_mode": "short_only",
            "direction_role": "short_leg",
            "realized_pnl": 12.0,
            "validation_pnl": 3.0,
            "test_pnl": 2.0,
            "equity_quality_score": 0.5,
        }
        selected = select_execution_candidates([long_row, short_row], max_candidates=3)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["candidate_name"], "opening_range_breakout")

    def test_build_execution_candidate_sets_adds_family_both_pair(self) -> None:
        base = {
            "symbol": "EURUSD",
            "strategy_family": "opening_range_breakout",
            "validation_profit_factor": 1.2,
            "validation_closed_trades": 2,
            "test_profit_factor": 1.1,
            "test_closed_trades": 2,
            "walk_forward_windows": 1,
            "walk_forward_pass_rate_pct": 50.0,
            "walk_forward_soft_pass_rate_pct": 50.0,
            "walk_forward_avg_validation_pnl": 2.0,
            "walk_forward_avg_test_pnl": 2.0,
            "best_regime": "trend_up_vol_high",
            "best_regime_pnl": 7.0,
            "best_trade_share_pct": 20.0,
            "equity_new_high_share_pct": 40.0,
            "max_consecutive_losses": 1,
            "equity_quality_score": 0.7,
            "regime_stability_score": 0.6,
            "regime_loss_ratio": 0.4,
            "combo_outperformance_score": 0.0,
            "realized_pnl": 15.0,
            "profit_factor": 1.3,
            "closed_trades": 5,
            "validation_pnl": 5.0,
            "test_pnl": 4.0,
            "promotion_tier": "core",
            "regime_specialist_viable": False,
            "mc_simulations": 500,
            "mc_pnl_p05": 2.0,
            "mc_loss_probability_pct": 0.0,
        }
        long_row = {
            **base,
            "candidate_name": "opening_range_breakout",
            "code_path": "quant_system.agents.strategies.OpeningRangeBreakoutAgent",
            "direction_mode": "long_only",
            "direction_role": "long_leg",
        }
        short_row = {
            **base,
            "candidate_name": "opening_range_short_breakdown",
            "code_path": "quant_system.agents.strategies.OpeningRangeShortBreakdownAgent",
            "direction_mode": "short_only",
            "direction_role": "short_leg",
            "realized_pnl": 14.0,
            "validation_pnl": 4.0,
            "test_pnl": 3.0,
        }
        candidate_sets = _build_execution_candidate_sets([long_row, short_row], "EURUSD", max_candidates=3)
        labels = {label for label, _ in candidate_sets}
        self.assertIn("family_both_opening_range_breakout", labels)

    def test_research_variant_plan_adds_4h_for_targeted_symbol(self) -> None:
        timeframe_specs, _, _ = _research_variant_plan("JP225", "full")
        self.assertIn(("4h", 240, "minute"), timeframe_specs)

    def test_with_variant_name_blocks_4h_for_intraday_only_family(self) -> None:
        spec = CandidateSpec(
            name="opening_range_breakout",
            description="test",
            agents=[],
            code_path="quant_system.agents.strategies.OpeningRangeBreakoutAgent",
        )
        self.assertIsNone(_with_variant_name(spec, "4h_open"))

    def test_with_variant_name_preserves_strategy_direction_metadata(self) -> None:
        spec = CandidateSpec(
            name="trend",
            description="test",
            agents=[],
            code_path="quant_system.agents.trend.TrendAgent",
            strategy_family="trend_family",
            direction_mode="both",
            direction_role="combined",
        )

        variant = _with_variant_name(spec, "4h_overlap")

        self.assertIsNotNone(variant)
        assert variant is not None
        self.assertEqual(variant.strategy_family, "trend_family")
        self.assertEqual(variant.direction_mode, "both")
        self.assertEqual(variant.direction_role, "combined")

    def test_with_variant_name_infers_strategy_direction_metadata_when_missing(self) -> None:
        spec = CandidateSpec(
            name="trend",
            description="test",
            agents=[],
            code_path="quant_system.agents.trend.TrendAgent",
        )

        variant = _with_variant_name(spec, "4h_overlap")

        self.assertIsNotNone(variant)
        assert variant is not None
        self.assertTrue(variant.strategy_family)
        self.assertEqual(variant.direction_mode, "both")
        self.assertEqual(variant.direction_role, "combined")


if __name__ == "__main__":
    unittest.main()
