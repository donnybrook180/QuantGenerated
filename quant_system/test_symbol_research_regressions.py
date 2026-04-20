from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta

from quant_system.config import SystemConfig
from quant_system.data.market_data import DuckDBMarketDataStore
from quant_system.models import MarketBar
from quant_system.symbol_research import (
    _build_execution_candidate_sets,
    _detect_research_mode,
    _execution_candidate_row,
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
    def test_detect_research_mode_accepts_btc_full_from_5m_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = f"{temp_dir}\\test.duckdb"
            store = DuckDBMarketDataStore(database_path)
            store.upsert_bars(
                _make_bar_series("X:BTCUSD", 6_000),
                timeframe="symbol_research_x_btcusd_5_minute",
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
        self.assertEqual(candidate_row["strategy_family"], "trend_agent")
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
        both_set = next(candidate_set for label, candidate_set in candidate_sets if label == "family_both_opening_range_breakout")
        self.assertEqual({row["direction_mode"] for row in both_set}, {"long_only", "short_only"})


if __name__ == "__main__":
    unittest.main()
