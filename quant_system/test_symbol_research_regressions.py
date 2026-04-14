from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta

from quant_system.config import SystemConfig
from quant_system.data.market_data import DuckDBMarketDataStore
from quant_system.models import MarketBar
from quant_system.symbol_research import (
    _detect_research_mode,
    _execution_candidate_row,
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
            "closed_trades": 2,
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
            "regime_stability_score": 1.0,
            "regime_loss_ratio": 0.0,
            "regime_trade_count_by_label": {"trend_up_vol_high": 2},
            "regime_pf_by_label": {"trend_up_vol_high": 1.8},
            "variant_label": "30m_europe",
        }
        candidate_row = _execution_candidate_row("BTC", row)
        self.assertEqual(candidate_row["promotion_tier"], "specialist")
        self.assertTrue(candidate_row["regime_specialist_viable"])


if __name__ == "__main__":
    unittest.main()
