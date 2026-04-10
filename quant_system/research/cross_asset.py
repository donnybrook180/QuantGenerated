from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC

from quant_system.data.market_data import DuckDBMarketDataStore
from quant_system.models import FeatureVector, MarketBar
from quant_system.research.features import build_feature_library


@dataclass(frozen=True, slots=True)
class CrossAssetSpec:
    prefix: str
    symbols: tuple[str, ...]


_CROSS_ASSET_SPECS: dict[str, tuple[CrossAssetSpec, ...]] = {
    "US500": (
        CrossAssetSpec("us100", ("QQQ", "US100")),
        CrossAssetSpec("dxy", ("DXY", "UUP")),
        CrossAssetSpec("vol", ("I:VIX", "VIX", "UVXY")),
        CrossAssetSpec("yield", ("I:TNX", "TNX", "US10Y", "TLT")),
    ),
    "US100": (
        CrossAssetSpec("us500", ("SPY", "US500")),
        CrossAssetSpec("dxy", ("DXY", "UUP")),
        CrossAssetSpec("vol", ("I:VIX", "VIX", "UVXY")),
        CrossAssetSpec("yield", ("I:TNX", "TNX", "US10Y", "TLT")),
    ),
    "XAUUSD": (
        CrossAssetSpec("dxy", ("DXY", "UUP")),
        CrossAssetSpec("yield", ("I:TNX", "TNX", "US10Y", "TLT")),
        CrossAssetSpec("us500", ("SPY", "US500")),
    ),
}


def supports_cross_asset_context(symbol: str) -> bool:
    return symbol.upper() in _CROSS_ASSET_SPECS


def apply_cross_asset_context(
    features: list[FeatureVector],
    database_path: str,
    target_symbol: str,
    multiplier: int,
    timespan: str,
) -> list[FeatureVector]:
    if not features or not supports_cross_asset_context(target_symbol):
        return features

    store = DuckDBMarketDataStore(database_path, read_only=True)
    context_maps: dict[str, dict[object, FeatureVector]] = {}
    for spec in _CROSS_ASSET_SPECS.get(target_symbol.upper(), ()):
        context_features = _load_context_features(store, spec, multiplier, timespan, len(features) + 512)
        context_maps[spec.prefix] = {feature.timestamp: feature for feature in context_features}

    enriched: list[FeatureVector] = []
    for feature in features:
        values = dict(feature.values)
        for spec in _CROSS_ASSET_SPECS.get(target_symbol.upper(), ()):
            context_feature = context_maps.get(spec.prefix, {}).get(feature.timestamp)
            _merge_context_values(values, spec.prefix, context_feature)
        _merge_cross_asset_scores(target_symbol.upper(), values)
        enriched.append(FeatureVector(timestamp=feature.timestamp, symbol=feature.symbol, values=values))
    return enriched


def _merge_context_values(values: dict[str, float], prefix: str, context_feature: FeatureVector | None) -> None:
    if context_feature is None:
        values[f"cross_{prefix}_available"] = 0.0
        values[f"cross_{prefix}_momentum_5"] = 0.0
        values[f"cross_{prefix}_momentum_20"] = 0.0
        values[f"cross_{prefix}_trend_strength"] = 0.0
        values[f"cross_{prefix}_vwap_distance"] = 0.0
        values[f"cross_{prefix}_session_position"] = 0.5
        values[f"cross_{prefix}_opening_window"] = 0.0
        values[f"cross_{prefix}_closing_window"] = 0.0
        values[f"cross_{prefix}_breakout_up"] = 0.0
        values[f"cross_{prefix}_breakout_down"] = 0.0
        values[f"cross_{prefix}_reentry_mid"] = 0.0
        values[f"cross_{prefix}_vwap_reclaim_up"] = 0.0
        values[f"cross_{prefix}_vwap_reclaim_down"] = 0.0
        return
    source = context_feature.values
    session_position = float(source.get("session_position", 0.5))
    vwap_distance = float(source.get("vwap_distance", 0.0))
    trend_strength = float(source.get("trend_strength", 0.0))
    momentum_20 = float(source.get("momentum_20", 0.0))
    values[f"cross_{prefix}_available"] = 1.0
    values[f"cross_{prefix}_momentum_5"] = float(source.get("momentum_5", 0.0))
    values[f"cross_{prefix}_momentum_20"] = momentum_20
    values[f"cross_{prefix}_trend_strength"] = trend_strength
    values[f"cross_{prefix}_vwap_distance"] = vwap_distance
    values[f"cross_{prefix}_session_position"] = session_position
    values[f"cross_{prefix}_opening_window"] = float(source.get("opening_window", 0.0))
    values[f"cross_{prefix}_closing_window"] = float(source.get("closing_window", 0.0))
    values[f"cross_{prefix}_breakout_up"] = 1.0 if session_position >= 0.95 and vwap_distance > 0.0004 else 0.0
    values[f"cross_{prefix}_breakout_down"] = 1.0 if session_position <= 0.05 and vwap_distance < -0.0004 else 0.0
    values[f"cross_{prefix}_reentry_mid"] = 1.0 if 0.3 <= session_position <= 0.7 and abs(vwap_distance) <= 0.0005 else 0.0
    values[f"cross_{prefix}_vwap_reclaim_up"] = 1.0 if vwap_distance > 0.0 and trend_strength > 0.0 and momentum_20 > 0.0 else 0.0
    values[f"cross_{prefix}_vwap_reclaim_down"] = 1.0 if vwap_distance < 0.0 and trend_strength < 0.0 and momentum_20 < 0.0 else 0.0


def _merge_cross_asset_scores(target_symbol: str, values: dict[str, float]) -> None:
    if target_symbol == "US500":
        confirm = values.get("cross_us100_momentum_20", 0.0) + values.get("cross_us100_trend_strength", 0.0)
        headwind = (
            max(values.get("cross_dxy_momentum_20", 0.0), 0.0)
            + max(values.get("cross_vol_momentum_20", 0.0), 0.0)
            + max(values.get("cross_yield_momentum_20", 0.0), 0.0)
        )
        values["cross_us100_confirm"] = confirm
        values["cross_us100_breakout_confirm"] = (
            values.get("cross_us100_breakout_up", 0.0)
            + values.get("cross_us100_vwap_reclaim_up", 0.0)
            - values.get("cross_us100_breakout_down", 0.0)
        )
        values["cross_us100_reentry_warning"] = (
            values.get("cross_us100_reentry_mid", 0.0)
            * (1.0 if values.get("cross_us100_trend_strength", 0.0) > 0.0 else 0.5)
        )
        values["cross_dxy_headwind"] = values.get("cross_dxy_momentum_20", 0.0)
        values["cross_vol_headwind"] = values.get("cross_vol_momentum_20", 0.0)
        values["cross_yield_headwind"] = values.get("cross_yield_momentum_20", 0.0)
        values["cross_risk_on_score"] = (
            confirm
            + values.get("cross_us100_breakout_confirm", 0.0) * 0.5
            - values.get("cross_us100_reentry_warning", 0.0) * 0.35
            - headwind
        )
    elif target_symbol == "US100":
        confirm = values.get("cross_us500_momentum_20", 0.0) + values.get("cross_us500_trend_strength", 0.0)
        headwind = (
            max(values.get("cross_dxy_momentum_20", 0.0), 0.0)
            + max(values.get("cross_vol_momentum_20", 0.0), 0.0)
            + max(values.get("cross_yield_momentum_20", 0.0), 0.0)
        )
        values["cross_us500_confirm"] = confirm
        values["cross_dxy_headwind"] = values.get("cross_dxy_momentum_20", 0.0)
        values["cross_vol_headwind"] = values.get("cross_vol_momentum_20", 0.0)
        values["cross_yield_headwind"] = values.get("cross_yield_momentum_20", 0.0)
        values["cross_risk_on_score"] = confirm - headwind
    elif target_symbol == "XAUUSD":
        inverse_tailwind = (
            -values.get("cross_dxy_momentum_20", 0.0)
            -values.get("cross_yield_momentum_20", 0.0)
        )
        risk_off_support = -values.get("cross_us500_momentum_20", 0.0)
        values["cross_dxy_inverse_confirm"] = -values.get("cross_dxy_momentum_20", 0.0)
        values["cross_yield_inverse_confirm"] = -values.get("cross_yield_momentum_20", 0.0)
        values["cross_risk_off_support"] = risk_off_support
        values["cross_gold_macro_tailwind_score"] = inverse_tailwind + risk_off_support


def _load_context_features(
    store: DuckDBMarketDataStore,
    spec: CrossAssetSpec,
    multiplier: int,
    timespan: str,
    limit: int,
) -> list[FeatureVector]:
    for symbol in spec.symbols:
        bars = _load_context_bars(store, symbol, multiplier, timespan, limit)
        if bars:
            normalized = _normalize_symbol(bars, symbol)
            return build_feature_library(normalized)
    return []


def _load_context_bars(
    store: DuckDBMarketDataStore,
    symbol: str,
    multiplier: int,
    timespan: str,
    limit: int,
) -> list[MarketBar]:
    timeframe = _variant_timeframe_key(symbol, multiplier, timespan)
    cached = store.load_bars(symbol, timeframe, limit)
    if cached:
        return cached
    if timespan == "minute" and multiplier in {15, 30, 60}:
        base = store.load_bars(symbol, _variant_timeframe_key(symbol, 5, "minute"), max(limit * max(multiplier // 5, 1), limit))
        aggregated = _aggregate_minute_bars(base, multiplier, 5)
        if aggregated:
            return aggregated
    return []


def _variant_timeframe_key(symbol: str, multiplier: int, timespan: str) -> str:
    return f"symbol_research_{_symbol_slug(symbol)}_{multiplier}_{timespan}"


def _symbol_slug(symbol: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in symbol).strip("_")


def _normalize_symbol(bars: list[MarketBar], symbol: str) -> list[MarketBar]:
    return [
        MarketBar(
            timestamp=bar.timestamp.astimezone(UTC) if bar.timestamp.tzinfo else bar.timestamp.replace(tzinfo=UTC),
            symbol=symbol,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )
        for bar in bars
    ]


def _aggregate_minute_bars(bars: list[MarketBar], target_multiplier: int, source_multiplier: int) -> list[MarketBar]:
    if not bars or target_multiplier <= source_multiplier or target_multiplier % source_multiplier != 0:
        return []
    ratio = target_multiplier // source_multiplier
    aggregated: list[MarketBar] = []
    bucket: list[MarketBar] = []
    current_key: tuple[int, int, int, int] | None = None
    for bar in bars:
        bucket_minute = (bar.timestamp.minute // target_multiplier) * target_multiplier
        key = (bar.timestamp.year, bar.timestamp.month, bar.timestamp.day, bar.timestamp.hour * 60 + bucket_minute)
        if current_key is None or key == current_key:
            bucket.append(bar)
            current_key = key
        else:
            _flush_bucket(bucket, current_key, ratio, aggregated)
            bucket = [bar]
            current_key = key
    _flush_bucket(bucket, current_key, ratio, aggregated)
    return aggregated


def _flush_bucket(
    bucket: list[MarketBar],
    bucket_key: tuple[int, int, int, int] | None,
    ratio: int,
    aggregated: list[MarketBar],
) -> None:
    if bucket_key is None or len(bucket) != ratio:
        return
    aggregated.append(
        MarketBar(
            timestamp=bucket[0].timestamp,
            symbol=bucket[0].symbol,
            open=bucket[0].open,
            high=max(item.high for item in bucket),
            low=min(item.low for item in bucket),
            close=bucket[-1].close,
            volume=sum(item.volume for item in bucket),
        )
    )
