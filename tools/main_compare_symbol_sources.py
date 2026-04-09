from __future__ import annotations

import copy
import statistics
import sys

import _bootstrap  # noqa: F401

from quant_system.config import SystemConfig
from quant_system.data.market_data import DuckDBMarketDataStore
from quant_system.integrations.binance_data import BinanceKlineClient
from quant_system.integrations.mt5 import MT5Client
from quant_system.models import MarketBar
from quant_system.symbol_research import _variant_timeframe_key
from quant_system.symbols import is_crypto_symbol, resolve_symbol_request


def _session_label(hour: int) -> str:
    if 7 <= hour < 13:
        return "europe"
    if 12 <= hour < 17:
        return "overlap"
    if 13 <= hour < 21:
        return "us"
    return "other"


def _load_cached_bars(config: SystemConfig, data_symbol: str, multiplier: int) -> list[MarketBar]:
    store = DuckDBMarketDataStore(config.mt5.database_path)
    return store.load_bars(data_symbol, _variant_timeframe_key(data_symbol, multiplier, "minute"), 200_000)


def _load_reference_bars(config: SystemConfig, data_symbol: str, multiplier: int, bar_count: int) -> tuple[list[MarketBar], str]:
    cached_bars = _load_cached_bars(config, data_symbol, multiplier)
    if not is_crypto_symbol(data_symbol):
        return cached_bars, "duckdb_cache"

    recent_days = max(10, int(((bar_count * multiplier) / (60 * 24)) + 3))
    try:
        network_bars = BinanceKlineClient(data_symbol, multiplier, "minute", recent_days).fetch_bars()
        return network_bars, "binance_recent"
    except Exception:
        return cached_bars, "duckdb_cache"


def _compare(symbol: str, broker_symbol: str | None, timeframe: str, bar_count: int) -> list[str]:
    config = SystemConfig()
    resolved = resolve_symbol_request(symbol, broker_symbol)
    multiplier = int(timeframe.removeprefix("M"))

    reference_bars, reference_source = _load_reference_bars(config, resolved.data_symbol, multiplier, bar_count)
    if not reference_bars:
        raise RuntimeError(f"No cached bars found for {resolved.data_symbol} {timeframe}. Refresh cache first.")

    mt5_config = copy.deepcopy(config.mt5)
    mt5_config.symbol = resolved.broker_symbol
    mt5_config.timeframe = timeframe
    mt5_client = MT5Client(mt5_config)
    mt5_client.initialize()
    try:
        mt5_bars = mt5_client.fetch_bars(bar_count=bar_count)
        resolved_mt5_symbol = mt5_client.resolved_symbol or resolved.broker_symbol
    finally:
        mt5_client.shutdown()

    cache_by_ts = {bar.timestamp: bar for bar in reference_bars}
    matched: list[tuple[MarketBar, MarketBar]] = []
    for mt5_bar in mt5_bars:
        cached_bar = cache_by_ts.get(mt5_bar.timestamp)
        if cached_bar is not None:
            matched.append((mt5_bar, cached_bar))

    if not matched:
        raise RuntimeError("No overlapping timestamps found between MT5 and cached research bars.")

    close_pct_diffs = [
        ((mt5_bar.close / cache_bar.close) - 1.0) * 100.0
        for mt5_bar, cache_bar in matched
        if cache_bar.close > 0
    ]
    abs_close_pct_diffs = [abs(value) for value in close_pct_diffs]

    session_rows: dict[str, list[float]] = {}
    for mt5_bar, cache_bar in matched:
        if cache_bar.close <= 0:
            continue
        pct_diff = ((mt5_bar.close / cache_bar.close) - 1.0) * 100.0
        session_rows.setdefault(_session_label(mt5_bar.timestamp.hour), []).append(pct_diff)

    sorted_abs = sorted(abs_close_pct_diffs)
    p95_index = max(0, min(len(sorted_abs) - 1, round((len(sorted_abs) - 1) * 0.95)))

    lines = [
        f"Requested symbol: {resolved.requested_symbol}",
        f"Data symbol: {resolved.data_symbol}",
        f"Broker symbol: {resolved.broker_symbol}",
        f"Resolved MT5 symbol: {resolved_mt5_symbol}",
        f"Timeframe: {timeframe}",
        f"MT5 bars fetched: {len(mt5_bars)}",
        f"Reference source: {reference_source}",
        f"Reference bars loaded: {len(reference_bars)}",
        f"Matched bars: {len(matched)}",
        f"MT5 close range: {min(bar.close for bar, _ in matched):.2f} .. {max(bar.close for bar, _ in matched):.2f}",
        f"Cache close range: {min(bar.close for _, bar in matched):.2f} .. {max(bar.close for _, bar in matched):.2f}",
        f"Median close diff pct: {statistics.median(close_pct_diffs):.4f}%",
        f"Median abs close diff pct: {statistics.median(abs_close_pct_diffs):.4f}%",
        f"P95 abs close diff pct: {sorted_abs[p95_index]:.4f}%",
        "Session diffs:",
    ]
    for session_name in ("europe", "overlap", "us", "other"):
        values = session_rows.get(session_name, [])
        if not values:
            lines.append(f"- {session_name}: no overlap")
            continue
        lines.append(
            f"- {session_name}: count={len(values)} median={statistics.median(values):.4f}% "
            f"median_abs={statistics.median(abs(value) for value in values):.4f}%"
        )
    return lines


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: .\\.venv\\Scripts\\python.exe main_compare_symbol_sources.py <symbol> [broker_symbol] [timeframe] [bar_count]")
        return 1
    symbol = sys.argv[1].strip()
    broker_symbol = sys.argv[2].strip() if len(sys.argv) >= 3 and sys.argv[2].strip() else None
    timeframe = sys.argv[3].strip().upper() if len(sys.argv) >= 4 and sys.argv[3].strip() else "M5"
    bar_count = int(sys.argv[4]) if len(sys.argv) >= 5 and sys.argv[4].strip() else 3000
    print("\n".join(_compare(symbol, broker_symbol, timeframe, bar_count)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
