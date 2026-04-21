from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from quant_system.config import SystemConfig
from quant_system.data.market_data import DuckDBMarketDataStore
from quant_system.symbol_research import (
    _aggregate_minute_bars,
    _detect_research_mode,
    _load_crypto_network_bars,
    _load_mt5_network_bars,
    _variant_timeframe_key,
)
from quant_system.test_fixtures import make_market_bar_series


class MarketDataDuckDBTests(unittest.TestCase):
    def test_variant_timeframe_key_is_stable_for_symbol_and_multiplier(self) -> None:
        key = _variant_timeframe_key("X:BTCUSD", 240, "minute")
        self.assertEqual(key, "symbol_research_x_btcusd_240_minute")

    def test_aggregate_minute_bars_builds_expected_4h_bars_from_1h_input(self) -> None:
        bars = make_market_bar_series(8, symbol="JP225", minutes=60)

        aggregated = _aggregate_minute_bars(bars, 240, 60)

        self.assertEqual(len(aggregated), 2)
        self.assertEqual(aggregated[0].timestamp.hour, 0)
        self.assertEqual(aggregated[1].timestamp.hour, 4)
        self.assertEqual(aggregated[0].open, bars[0].open)
        self.assertEqual(aggregated[0].close, bars[3].close)
        self.assertEqual(aggregated[0].volume, sum(bar.volume for bar in bars[:4]))

    def test_load_mt5_network_bars_supports_4h_via_h1_aggregation(self) -> None:
        config = SystemConfig()
        hourly_bars = make_market_bar_series(8, symbol="JP225", minutes=60)

        class FakeMT5Client:
            def __init__(self, mt5_config) -> None:
                self.mt5_config = mt5_config

            def initialize(self) -> None:
                return None

            def fetch_bars(self, history_bars: int):
                return hourly_bars

            def shutdown(self) -> None:
                return None

        with patch("quant_system.symbol_research.MT5Client", FakeMT5Client):
            bars, source = _load_mt5_network_bars(config, "JP225", "JP225", "JP225.cash", 240, "minute")

        self.assertEqual(source, "mt5_aggregated_4h")
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0].symbol, "JP225")

    def test_load_crypto_network_bars_supports_4h_via_60m_aggregation(self) -> None:
        config = SystemConfig()
        hourly_bars = make_market_bar_series(8, symbol="X:BTCUSD", start_close=40_000.0, minutes=60)

        class FakeBinanceClient:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

            def fetch_bars(self):
                return hourly_bars

        with patch("quant_system.symbol_research.BinanceKlineClient", FakeBinanceClient):
            bars, source = _load_crypto_network_bars(config, "X:BTCUSD", 240, "minute")

        self.assertEqual(source, "binance_aggregated_4h")
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0].symbol, "X:BTCUSD")

    def test_detect_research_mode_switches_to_full_when_4h_cache_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = f"{temp_dir}\\market.duckdb"
            store = DuckDBMarketDataStore(database_path)
            store.upsert_bars(
                make_market_bar_series(600, symbol="JP225", minutes=5),
                timeframe="symbol_research_jp225_5_minute",
                source="test",
            )
            store.upsert_bars(
                make_market_bar_series(600, symbol="JP225", minutes=15),
                timeframe="symbol_research_jp225_15_minute",
                source="test",
            )
            store.upsert_bars(
                make_market_bar_series(600, symbol="JP225", minutes=30),
                timeframe="symbol_research_jp225_30_minute",
                source="test",
            )
            store.upsert_bars(
                make_market_bar_series(300, symbol="JP225", minutes=60),
                timeframe="symbol_research_jp225_60_minute",
                source="test",
            )
            store.upsert_bars(
                make_market_bar_series(250, symbol="JP225", minutes=240),
                timeframe="symbol_research_jp225_240_minute",
                source="test",
            )
            config = SystemConfig()
            config.mt5.database_path = database_path
            config.symbol_research.mode = "auto"

            mode = _detect_research_mode(config, "JP225", "JP225")

        self.assertEqual(mode, "full")

    def test_missing_4h_cache_for_supported_symbol_falls_back_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = f"{temp_dir}\\market.duckdb"
            store = DuckDBMarketDataStore(database_path)
            store.upsert_bars(
                make_market_bar_series(600, symbol="JP225", minutes=5),
                timeframe="symbol_research_jp225_5_minute",
                source="test",
            )
            store.upsert_bars(
                make_market_bar_series(600, symbol="JP225", minutes=15),
                timeframe="symbol_research_jp225_15_minute",
                source="test",
            )
            store.upsert_bars(
                make_market_bar_series(600, symbol="JP225", minutes=30),
                timeframe="symbol_research_jp225_30_minute",
                source="test",
            )
            store.upsert_bars(
                make_market_bar_series(300, symbol="JP225", minutes=60),
                timeframe="symbol_research_jp225_60_minute",
                source="test",
            )
            config = SystemConfig()
            config.mt5.database_path = database_path
            config.symbol_research.mode = "auto"

            mode = _detect_research_mode(config, "JP225", "JP225")

        self.assertEqual(mode, "seed")


if __name__ == "__main__":
    unittest.main()
