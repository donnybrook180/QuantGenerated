from __future__ import annotations

import copy
import csv
from dataclasses import dataclass
from pathlib import Path

from quant_system.artifacts import system_reports_dir
from quant_system.config import SystemConfig
from quant_system.data.market_data import DuckDBMarketDataStore
from quant_system.integrations.mt5 import MT5Client, MT5Error
from quant_system.live_support import build_features_with_events
from quant_system.models import FeatureVector, MarketBar
from quant_system.symbols import resolve_symbol_request


DEFAULT_STOCK_SELECTOR_UNIVERSE: tuple[str, ...] = ("AAPL", "AMD", "META", "MSFT", "NVDA", "TSLA")


@dataclass(slots=True)
class StockSelectorRow:
    rank: int
    symbol: str
    broker_symbol: str
    score: float
    source: str
    latest_timestamp: str
    average_daily_dollar_volume: float
    opening_gap_pct: float
    relative_volume: float
    atr_proxy: float
    momentum_20: float
    event_day: bool
    earnings_day: bool
    reasons: tuple[str, ...]


def _symbol_slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def _variant_timeframe_key(data_symbol: str, multiplier: int, timespan: str) -> str:
    return f"symbol_research_{_symbol_slug(data_symbol)}_{multiplier}_{timespan}"


def _load_cached_bars(config: SystemConfig, data_symbol: str, limit: int = 2000) -> list[MarketBar]:
    store = DuckDBMarketDataStore(config.mt5.database_path, read_only=True)
    return store.load_bars(data_symbol, _variant_timeframe_key(data_symbol, 5, "minute"), limit)


def _load_mt5_bars(config: SystemConfig, symbol: str, broker_symbol: str, limit: int = 2000) -> tuple[list[MarketBar], str]:
    mt5_config = copy.deepcopy(config.mt5)
    mt5_config.symbol = broker_symbol
    mt5_config.timeframe = "M5"
    mt5_config.history_bars = limit
    client = MT5Client(mt5_config)
    try:
        client.initialize()
        bars = client.fetch_bars(limit)
    finally:
        try:
            client.shutdown()
        except Exception:
            pass
    normalized = [
        MarketBar(
            timestamp=bar.timestamp,
            symbol=symbol,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )
        for bar in bars
    ]
    return normalized, "mt5"


def _load_selector_bars(config: SystemConfig, symbol: str, broker_symbol: str) -> tuple[list[MarketBar], str]:
    cached = _load_cached_bars(config, symbol)
    if len(cached) >= 300:
        return cached, "duckdb_cache"
    try:
        bars, source = _load_mt5_bars(config, symbol, broker_symbol)
    except MT5Error:
        return cached, "duckdb_cache" if cached else "unavailable"
    if bars:
        try:
            DuckDBMarketDataStore(config.mt5.database_path).upsert_bars(
                bars,
                timeframe=_variant_timeframe_key(symbol, 5, "minute"),
                source=source,
            )
        except Exception:
            pass
        return bars, source
    return cached, "duckdb_cache" if cached else "unavailable"


def _average_daily_dollar_volume(bars: list[MarketBar]) -> float:
    by_day: dict[object, float] = {}
    for bar in bars[-390:]:
        by_day.setdefault(bar.timestamp.date(), 0.0)
        by_day[bar.timestamp.date()] += bar.close * bar.volume
    if not by_day:
        return 0.0
    values = list(by_day.values())[-20:]
    return sum(values) / len(values)


def _score_stock_candidate(feature: FeatureVector, average_daily_dollar_volume: float) -> tuple[float, tuple[str, ...]]:
    gap_pct = abs(float(feature.values.get("opening_gap_pct", 0.0) or 0.0))
    relative_volume = float(feature.values.get("relative_volume", 0.0) or 0.0)
    atr_proxy = float(feature.values.get("atr_proxy", 0.0) or 0.0)
    momentum_20 = abs(float(feature.values.get("momentum_20", 0.0) or 0.0))
    high_impact = float(feature.values.get("high_impact_event_day", 0.0) or 0.0) > 0.0
    earnings_day = float(feature.values.get("earnings_event_day", 0.0) or 0.0) > 0.0
    news_count = float(feature.values.get("news_count_1d", 0.0) or 0.0)

    liquidity_score = min(1.0, average_daily_dollar_volume / 250_000_000.0)
    gap_score = min(2.0, gap_pct * 120.0)
    volume_score = min(2.0, max(relative_volume - 1.0, 0.0) * 1.25)
    atr_score = min(1.5, atr_proxy * 180.0)
    momentum_score = min(1.25, momentum_20 * 120.0)
    event_score = 0.0
    if earnings_day:
        event_score = 1.25
    elif high_impact:
        event_score = 0.75
    elif news_count > 0.0:
        event_score = 0.25

    score = liquidity_score + gap_score + volume_score + atr_score + momentum_score + event_score

    reasons: list[tuple[float, str]] = [
        (gap_score, f"gap={gap_pct * 100.0:.2f}%"),
        (volume_score, f"rel_vol={relative_volume:.2f}"),
        (atr_score, f"atr_proxy={atr_proxy:.4f}"),
        (momentum_score, f"mom20={float(feature.values.get('momentum_20', 0.0) or 0.0):.4f}"),
        (liquidity_score, f"adv=${average_daily_dollar_volume:,.0f}"),
    ]
    if earnings_day:
        reasons.append((event_score, "earnings_day"))
    elif high_impact:
        reasons.append((event_score, "high_impact_day"))
    elif news_count > 0.0:
        reasons.append((event_score, f"news_count={int(news_count)}"))
    top_reasons = tuple(label for _, label in sorted(reasons, key=lambda item: item[0], reverse=True)[:3] if _ > 0.0)
    return score, top_reasons


def build_stock_selector_universe(symbols: tuple[str, ...] | None = None) -> tuple[str, ...]:
    return tuple(symbol.upper() for symbol in (symbols or DEFAULT_STOCK_SELECTOR_UNIVERSE))


def select_top_stock_candidates(
    config: SystemConfig | None = None,
    symbols: tuple[str, ...] | None = None,
    top_n: int = 5,
) -> list[StockSelectorRow]:
    config = config or SystemConfig()
    selected: list[StockSelectorRow] = []
    for raw_symbol in build_stock_selector_universe(symbols):
        resolved = resolve_symbol_request(raw_symbol)
        bars, source = _load_selector_bars(config, resolved.data_symbol, resolved.broker_symbol)
        if len(bars) < 100:
            continue
        features = build_features_with_events(config, resolved.data_symbol, bars)
        if not features:
            continue
        latest_feature = features[-1]
        average_daily_dollar_volume = _average_daily_dollar_volume(bars)
        relative_volume = float(latest_feature.values.get("relative_volume", 0.0) or 0.0)
        atr_proxy = float(latest_feature.values.get("atr_proxy", 0.0) or 0.0)
        if average_daily_dollar_volume < 50_000_000.0:
            continue
        if relative_volume < 0.9 and atr_proxy < 0.0025:
            continue
        score, reasons = _score_stock_candidate(latest_feature, average_daily_dollar_volume)
        if score <= 0.0:
            continue
        selected.append(
            StockSelectorRow(
                rank=0,
                symbol=resolved.profile_symbol,
                broker_symbol=resolved.broker_symbol,
                score=score,
                source=source,
                latest_timestamp=latest_feature.timestamp.isoformat(),
                average_daily_dollar_volume=average_daily_dollar_volume,
                opening_gap_pct=float(latest_feature.values.get("opening_gap_pct", 0.0) or 0.0),
                relative_volume=relative_volume,
                atr_proxy=atr_proxy,
                momentum_20=float(latest_feature.values.get("momentum_20", 0.0) or 0.0),
                event_day=float(latest_feature.values.get("high_impact_event_day", 0.0) or 0.0) > 0.0,
                earnings_day=float(latest_feature.values.get("earnings_event_day", 0.0) or 0.0) > 0.0,
                reasons=reasons,
            )
        )
    ranked = sorted(selected, key=lambda row: row.score, reverse=True)[: max(top_n, 1)]
    for index, row in enumerate(ranked, start=1):
        row.rank = index
    return ranked


def write_stock_selector_report(rows: list[StockSelectorRow]) -> tuple[Path, Path]:
    reports_dir = system_reports_dir()
    txt_path = reports_dir / "stock_selector_today.txt"
    csv_path = reports_dir / "stock_selector_today.csv"

    lines = ["Stock Selector Today", ""]
    if not rows:
        lines.append("No eligible stock candidates found.")
    else:
        for row in rows:
            lines.extend(
                [
                    f"{row.rank}. {row.symbol} score={row.score:.2f} source={row.source}",
                    f"   broker={row.broker_symbol} ts={row.latest_timestamp}",
                    f"   adv=${row.average_daily_dollar_volume:,.0f} gap={row.opening_gap_pct * 100.0:.2f}% "
                    f"rel_vol={row.relative_volume:.2f} atr={row.atr_proxy:.4f} mom20={row.momentum_20:.4f}",
                    f"   event_day={'yes' if row.event_day else 'no'} earnings_day={'yes' if row.earnings_day else 'no'}",
                    f"   reasons: {', '.join(row.reasons) if row.reasons else 'none'}",
                    "",
                ]
            )
    txt_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "rank",
                "symbol",
                "broker_symbol",
                "score",
                "source",
                "latest_timestamp",
                "average_daily_dollar_volume",
                "opening_gap_pct",
                "relative_volume",
                "atr_proxy",
                "momentum_20",
                "event_day",
                "earnings_day",
                "reasons",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.rank,
                    row.symbol,
                    row.broker_symbol,
                    f"{row.score:.6f}",
                    row.source,
                    row.latest_timestamp,
                    f"{row.average_daily_dollar_volume:.2f}",
                    f"{row.opening_gap_pct:.6f}",
                    f"{row.relative_volume:.6f}",
                    f"{row.atr_proxy:.6f}",
                    f"{row.momentum_20:.6f}",
                    int(row.event_day),
                    int(row.earnings_day),
                    "|".join(row.reasons),
                ]
            )
    return txt_path, csv_path
