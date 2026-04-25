from __future__ import annotations

import copy
from datetime import timedelta

import duckdb

from quant_system.config import SystemConfig
from quant_system.data.market_data import DuckDBMarketDataStore
from quant_system.integrations.binance_data import BinanceError, BinanceKlineClient
from quant_system.integrations.kraken_data import KrakenError, KrakenOHLCClient
from quant_system.integrations.macro_events import apply_macro_event_context
from quant_system.integrations.mt5 import MT5Client, MT5Error
from quant_system.models import FeatureVector, MarketBar
from quant_system.research.cross_asset import apply_cross_asset_context, supports_cross_asset_context
from quant_system.research.features import build_feature_library
from quant_system.research.funding import apply_broker_funding_context, load_broker_funding_context
from quant_system.symbols import (
    is_crypto_symbol as symbol_is_crypto,
    is_forex_symbol as symbol_is_forex,
    is_index_symbol as symbol_is_index,
    is_metal_symbol as symbol_is_metal,
    is_stock_symbol as symbol_is_stock,
)


class ExternalMarketDataUnavailableError(RuntimeError):
    pass


def _session_alignment_note(profile_symbol: str, data_source: str) -> str:
    symbol_upper = profile_symbol.upper()
    if symbol_is_stock(symbol_upper):
        base = "session-bounded equity-style stream"
    elif symbol_is_crypto(symbol_upper):
        base = "continuous crypto-style stream"
    else:
        base = "continuous MT5-style stream"
    if "mt5" in data_source:
        return f"{base}; broker-backed research path"
    return f"{base}; fallback/non-broker data source"


def build_broker_data_sanity_summary(
    config: SystemConfig,
    profile_symbol: str,
    data_symbol: str,
    broker_symbol: str,
    data_source: str,
    features: list[FeatureVector],
    *,
    mt5_client_cls=MT5Client,
) -> dict[str, object]:
    history_bars_loaded = len(features)
    history_window_start = features[0].timestamp.isoformat() if features else ""
    history_window_end = features[-1].timestamp.isoformat() if features else ""
    missing_bar_warnings: list[str] = []
    if len(features) >= 3:
        deltas = [
            features[index].timestamp - features[index - 1].timestamp
            for index in range(1, len(features))
            if features[index].timestamp > features[index - 1].timestamp
        ]
        if deltas:
            expected_delta = min(deltas)
            gap_count = sum(1 for delta in deltas if delta > (expected_delta * 2))
            if gap_count:
                missing_bar_warnings.append(
                    f"detected_{gap_count}_timestamp_gaps_gt_{int(expected_delta.total_seconds() // 60)}m"
                )
    contract_spec_notes = "not_available"
    broker_data_source = data_source
    resolved_broker_symbol = broker_symbol
    if "mt5" in data_source and broker_symbol:
        mt5_config = copy.deepcopy(config.mt5)
        mt5_config.symbol = broker_symbol
        client = mt5_client_cls(mt5_config)
        try:
            client.initialize()
            resolved_broker_symbol = str(client.resolved_symbol or broker_symbol)
            funding = client.funding_info()
            snapshot = client.market_snapshot()
            contract_spec_notes = (
                f"resolved_symbol={resolved_broker_symbol} point={funding.point:.8f} "
                f"contract_size={funding.contract_size:.2f} spread_points={snapshot.spread_points:.8f} "
                f"swap_long={funding.swap_long:.4f} swap_short={funding.swap_short:.4f}"
            )
            broker_data_source = "blue_guardian_mt5" if str(config.mt5.prop_broker) == "blue_guardian" else "mt5"
        except Exception as exc:
            missing_bar_warnings.append(f"contract_spec_lookup_failed:{exc}")
        finally:
            try:
                client.shutdown()
            except Exception:
                pass
    return {
        "broker_data_source": broker_data_source,
        "broker_symbol": resolved_broker_symbol,
        "data_symbol": data_symbol,
        "history_bars_loaded": history_bars_loaded,
        "history_window_start": history_window_start,
        "history_window_end": history_window_end,
        "missing_bar_warnings": tuple(missing_bar_warnings),
        "session_alignment_notes": _session_alignment_note(profile_symbol, data_source),
        "contract_spec_notes": contract_spec_notes,
    }


def aggregate_minute_bars(bars: list[MarketBar], target_multiplier: int, source_multiplier: int) -> list[MarketBar]:
    if not bars or target_multiplier <= source_multiplier or target_multiplier % source_multiplier != 0:
        return []
    ratio = target_multiplier // source_multiplier
    aggregated: list[MarketBar] = []
    bucket: list[MarketBar] = []
    current_bucket_key: tuple[int, int, int, int] | None = None

    def flush_bucket(items: list[MarketBar], bucket_key: tuple[int, int, int, int] | None) -> None:
        if len(items) != ratio or bucket_key is None:
            return
        total_minutes = bucket_key[3]
        bucket_hour = total_minutes // 60
        bucket_minute = total_minutes % 60
        aggregated.append(
            MarketBar(
                timestamp=items[0].timestamp.replace(hour=bucket_hour, minute=bucket_minute, second=0, microsecond=0),
                symbol=items[0].symbol,
                open=items[0].open,
                high=max(item.high for item in items),
                low=min(item.low for item in items),
                close=items[-1].close,
                volume=sum(item.volume for item in items),
            )
        )

    for bar in bars:
        total_minutes = (bar.timestamp.hour * 60) + bar.timestamp.minute
        bucket_start_minutes = (total_minutes // target_multiplier) * target_multiplier
        bucket_key = (bar.timestamp.year, bar.timestamp.month, bar.timestamp.day, bucket_start_minutes)
        if current_bucket_key != bucket_key:
            flush_bucket(bucket, current_bucket_key)
            bucket = [bar]
            current_bucket_key = bucket_key
        else:
            bucket.append(bar)

    flush_bucket(bucket, current_bucket_key)
    return aggregated


def full_mode_minimum_bars(profile_symbol: str, multiplier: int, timespan: str) -> int:
    if symbol_is_index(profile_symbol):
        if timespan == "minute" and multiplier >= 60:
            return 200
        return 300
    return 500


def has_plausible_price_scale(data_symbol: str, bars: list[MarketBar]) -> bool:
    if not bars:
        return False
    closes = sorted(bar.close for bar in bars if bar.close > 0)
    if not closes:
        return False
    median_close = closes[len(closes) // 2]
    upper = data_symbol.upper()
    if upper == "X:ETHUSD":
        return median_close >= 100.0
    if upper == "X:BTCUSD":
        return median_close >= 1_000.0
    return True


def cache_bar_limit(config: SystemConfig, multiplier: int, timespan: str) -> int:
    if timespan == "minute":
        minutes = max(config.market_data.history_days * 24 * 60, multiplier)
        return max(50_000, int(minutes / max(multiplier, 1)) + 512)
    return 50_000


def mt5_bar_limit(
    config: SystemConfig,
    symbol: str,
    multiplier: int,
    timespan: str,
    *,
    uses_continuous_session_stream_fn,
) -> int:
    if timespan != "minute":
        return 0
    trading_minutes_per_day = 24 * 60 if uses_continuous_session_stream_fn(symbol) else 8 * 60
    estimated = int((config.market_data.history_days * trading_minutes_per_day) / max(multiplier, 1))
    return max(2_500, estimated + 512)


def normalize_bars_symbol(bars: list[MarketBar], target_symbol: str) -> list[MarketBar]:
    return [
        MarketBar(
            timestamp=bar.timestamp,
            symbol=target_symbol,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )
        for bar in bars
    ]


def infer_bars_timeframe(bars: list[MarketBar]) -> tuple[int, str]:
    if len(bars) < 2:
        return 5, "minute"
    delta_seconds = int((bars[1].timestamp - bars[0].timestamp).total_seconds())
    if delta_seconds <= 0:
        return 5, "minute"
    return max(delta_seconds // 60, 1), "minute"


def build_features_with_events(config: SystemConfig, data_symbol: str, bars: list[MarketBar]) -> list[FeatureVector]:
    if not bars:
        return []
    funding_context = load_broker_funding_context(config, data_symbol, config.mt5.symbol)
    if not symbol_is_stock(data_symbol):
        features = build_feature_library(bars)
        features = apply_broker_funding_context(features, funding_context)
        if config.macro_calendar.enabled:
            features = apply_macro_event_context(
                features,
                data_symbol,
                config.macro_calendar.calendar_path,
                pre_event_minutes=config.macro_calendar.pre_event_minutes,
                post_event_minutes=config.macro_calendar.post_event_minutes,
            )
        if supports_cross_asset_context(data_symbol):
            multiplier, timespan = infer_bars_timeframe(bars)
            features = apply_cross_asset_context(
                features,
                config.mt5.database_path,
                data_symbol,
                multiplier,
                timespan,
            )
        return features
    try:
        from quant_system.integrations.stock_events import fetch_stock_event_flags

        event_flags = fetch_stock_event_flags(
            data_symbol,
            start_day=bars[0].timestamp.date(),
            end_day=bars[-1].timestamp.date(),
        )
    except RuntimeError:
        features = build_feature_library(bars)
    else:
        features = build_feature_library(bars, event_flags)
    features = apply_broker_funding_context(features, funding_context)
    if config.macro_calendar.enabled:
        features = apply_macro_event_context(
            features,
            data_symbol,
            config.macro_calendar.calendar_path,
            pre_event_minutes=config.macro_calendar.pre_event_minutes,
            post_event_minutes=config.macro_calendar.post_event_minutes,
        )
    if supports_cross_asset_context(data_symbol):
        multiplier, timespan = infer_bars_timeframe(bars)
        features = apply_cross_asset_context(
            features,
            config.mt5.database_path,
            data_symbol,
            multiplier,
            timespan,
        )
    return features


def load_cached_variant_bars(
    store: DuckDBMarketDataStore,
    data_symbol: str,
    multiplier: int,
    timespan: str,
    cache_limit: int,
    base_cache_limit: int,
    *,
    cache_symbol_candidates_fn,
    variant_timeframe_key_fn,
    has_plausible_price_scale_fn,
    write_store: DuckDBMarketDataStore | None = None,
) -> tuple[list[MarketBar], str] | None:
    for cache_symbol in cache_symbol_candidates_fn(data_symbol):
        target_timeframe = variant_timeframe_key_fn(cache_symbol, multiplier, timespan)
        cached = store.load_bars(cache_symbol, target_timeframe, cache_limit)
        if cached and has_plausible_price_scale_fn(data_symbol, cached):
            return cached, "duckdb_cache"
        if timespan == "minute" and multiplier in {15, 30, 60}:
            base_cached = store.load_bars(
                cache_symbol,
                variant_timeframe_key_fn(cache_symbol, 5, "minute"),
                base_cache_limit,
            )
            if base_cached and has_plausible_price_scale_fn(data_symbol, base_cached):
                aggregated = aggregate_minute_bars(base_cached, multiplier, 5)
                if aggregated:
                    if write_store is not None and not write_store.read_only:
                        try:
                            write_store.upsert_bars(aggregated, timeframe=target_timeframe, source="duckdb_cache_aggregated")
                        except RuntimeError:
                            pass
                    return aggregated, "duckdb_cache_aggregated"
    return None


def cache_has_variant_bars(
    store: DuckDBMarketDataStore,
    data_symbol: str,
    multiplier: int,
    timespan: str,
    minimum_bars: int,
    *,
    cache_symbol_candidates_fn,
    variant_timeframe_key_fn,
    has_plausible_price_scale_fn,
) -> bool:
    cached = load_cached_variant_bars(
        store,
        data_symbol,
        multiplier,
        timespan,
        cache_limit=max(minimum_bars, 50_000),
        base_cache_limit=50_000,
        cache_symbol_candidates_fn=cache_symbol_candidates_fn,
        variant_timeframe_key_fn=variant_timeframe_key_fn,
        has_plausible_price_scale_fn=has_plausible_price_scale_fn,
    )
    return bool(cached and len(cached[0]) >= minimum_bars)


def load_crypto_network_bars(
    config: SystemConfig,
    data_symbol: str,
    multiplier: int,
    timespan: str,
    *,
    binance_client_cls=BinanceKlineClient,
    kraken_client_cls=KrakenOHLCClient,
) -> tuple[list[MarketBar], str]:
    if timespan == "minute" and multiplier == 240:
        base_bars, source = load_crypto_network_bars(
            config,
            data_symbol,
            60,
            timespan,
            binance_client_cls=binance_client_cls,
            kraken_client_cls=kraken_client_cls,
        )
        aggregated = aggregate_minute_bars(base_bars, 240, 60)
        if aggregated:
            return aggregated, f"{source}_aggregated_4h"
        raise RuntimeError("Unable to aggregate crypto 4h bars from 1h source bars.")
    errors: list[str] = []
    try:
        bars = binance_client_cls(
            symbol=data_symbol,
            multiplier=multiplier,
            timespan=timespan,
            history_days=config.market_data.history_days,
        ).fetch_bars()
        return bars, "binance"
    except BinanceError as exc:
        errors.append(str(exc))

    try:
        bars = kraken_client_cls(
            symbol=data_symbol,
            multiplier=multiplier,
            timespan=timespan,
            history_days=config.market_data.history_days,
        ).fetch_bars()
        return bars, "kraken"
    except KrakenError as exc:
        errors.append(str(exc))

    raise RuntimeError("; ".join(errors))


def load_mt5_network_bars(
    config: SystemConfig,
    profile_symbol: str,
    data_symbol: str,
    broker_symbol: str,
    multiplier: int,
    timespan: str,
    *,
    mt5_client_cls=MT5Client,
    uses_continuous_session_stream_fn,
) -> tuple[list[MarketBar], str]:
    if timespan != "minute":
        raise MT5Error(f"Unsupported MT5 timespan {timespan}.")
    if multiplier == 240:
        base_bars, source = load_mt5_network_bars(
            config,
            profile_symbol,
            data_symbol,
            broker_symbol,
            60,
            timespan,
            mt5_client_cls=mt5_client_cls,
            uses_continuous_session_stream_fn=uses_continuous_session_stream_fn,
        )
        aggregated = aggregate_minute_bars(base_bars, 240, 60)
        if aggregated:
            return aggregated, f"{source}_aggregated_4h"
        raise MT5Error(f"Unable to aggregate MT5 4h bars for {broker_symbol} from H1 source bars.")
    timeframe_map = {1: "M1", 5: "M5", 15: "M15", 30: "M30", 60: "H1"}
    timeframe = timeframe_map.get(multiplier)
    if timeframe is None:
        raise MT5Error(f"Unsupported MT5 minute multiplier {multiplier}.")
    mt5_config = copy.deepcopy(config.mt5)
    mt5_config.symbol = broker_symbol
    mt5_config.timeframe = timeframe
    mt5_config.history_bars = mt5_bar_limit(
        config,
        profile_symbol,
        multiplier,
        timespan,
        uses_continuous_session_stream_fn=uses_continuous_session_stream_fn,
    )
    client = mt5_client_cls(mt5_config)
    try:
        client.initialize()
        bars = client.fetch_bars(mt5_config.history_bars)
    finally:
        try:
            client.shutdown()
        except Exception:
            pass
    normalized = normalize_bars_symbol(bars, data_symbol)
    if not normalized:
        raise MT5Error(f"No MT5 bars returned for {broker_symbol}/{timeframe}.")
    return normalized, "mt5"


def detect_research_mode(
    config: SystemConfig,
    profile_symbol: str,
    data_symbol: str,
    *,
    research_variant_plan_fn,
    cache_symbol_candidates_fn,
    variant_timeframe_key_fn,
) -> str:
    requested_mode = config.symbol_research.mode
    if requested_mode in {"seed", "full"}:
        return requested_mode
    symbol_specific = (
        symbol_is_crypto(profile_symbol)
        or symbol_is_metal(profile_symbol)
        or symbol_is_forex(profile_symbol)
        or symbol_is_stock(profile_symbol)
        or symbol_is_index(profile_symbol)
    )
    if not symbol_specific:
        return "full"

    store = DuckDBMarketDataStore(config.mt5.database_path, read_only=True)
    timeframe_specs, _, _ = research_variant_plan_fn(profile_symbol, "full")
    for _, multiplier, timespan in timeframe_specs:
        if not cache_has_variant_bars(
            store,
            data_symbol,
            multiplier,
            timespan,
            minimum_bars=full_mode_minimum_bars(profile_symbol, multiplier, timespan),
            cache_symbol_candidates_fn=cache_symbol_candidates_fn,
            variant_timeframe_key_fn=variant_timeframe_key_fn,
            has_plausible_price_scale_fn=has_plausible_price_scale,
        ):
            return "seed"
    return "full"


def load_symbol_features_variant(
    config: SystemConfig,
    data_symbol: str,
    multiplier: int,
    timespan: str,
    *,
    symbol_slug_fn,
    cache_symbol_candidates_fn,
    variant_timeframe_key_fn,
    uses_continuous_session_stream_fn,
    broker_symbol: str | None = None,
    profile_symbol: str | None = None,
) -> tuple[list[FeatureVector], str]:
    cache_store = DuckDBMarketDataStore(config.mt5.database_path, read_only=True)
    try:
        write_store: DuckDBMarketDataStore | None = DuckDBMarketDataStore(config.mt5.database_path)
    except duckdb.IOException:
        write_store = None
    timeframe = f"{multiplier}_{timespan}"
    scoped_timeframe = f"symbol_research_{symbol_slug_fn(data_symbol)}_{timeframe}"
    cache_limit_value = cache_bar_limit(config, multiplier, timespan)
    base_cache_limit = cache_bar_limit(config, 5, "minute")
    resolved_profile_symbol = profile_symbol or data_symbol
    source_preference = config.symbol_research.source_preference

    def _try_mt5_fetch() -> tuple[list[FeatureVector], str] | None:
        if not broker_symbol or source_preference in {"external_only", "cache_only"}:
            return None
        bars, source = load_mt5_network_bars(
            config,
            resolved_profile_symbol,
            data_symbol,
            broker_symbol,
            multiplier,
            timespan,
            uses_continuous_session_stream_fn=uses_continuous_session_stream_fn,
        )
        if not has_plausible_price_scale(data_symbol, bars):
            raise RuntimeError(f"Fetched implausible MT5 price scale for {data_symbol}; refusing to persist suspect bars.")
        try:
            DuckDBMarketDataStore(config.mt5.database_path).upsert_bars(bars, timeframe=scoped_timeframe, source=source)
        except (duckdb.IOException, RuntimeError):
            return build_features_with_events(config, data_symbol, bars), f"{source}_direct"
        persisted = cache_store.load_bars(data_symbol, scoped_timeframe, len(bars))
        if persisted:
            return build_features_with_events(config, data_symbol, persisted), source
        return build_features_with_events(config, data_symbol, bars), f"{source}_direct"

    if config.market_data.fetch_policy in {"cache_first", "cache_only"}:
        cached_result = load_cached_variant_bars(
            cache_store,
            data_symbol,
            multiplier,
            timespan,
            cache_limit=cache_limit_value,
            base_cache_limit=base_cache_limit,
            cache_symbol_candidates_fn=cache_symbol_candidates_fn,
            variant_timeframe_key_fn=variant_timeframe_key_fn,
            has_plausible_price_scale_fn=has_plausible_price_scale,
            write_store=write_store,
        )
        if cached_result is not None:
            cached_bars, cached_source = cached_result
            return build_features_with_events(config, data_symbol, cached_bars), cached_source
        if config.market_data.fetch_policy == "cache_only":
            raise RuntimeError(f"No cached DuckDB bars available for {data_symbol}/{scoped_timeframe}.")

    mt5_errors: list[str] = []
    if source_preference in {"broker_first", "broker_only"}:
        try:
            mt5_result = _try_mt5_fetch()
            if mt5_result is not None:
                return mt5_result
        except MT5Error as exc:
            mt5_errors.append(str(exc))
            if source_preference == "broker_only":
                raise RuntimeError(f"MT5 broker fetch failed for {broker_symbol or data_symbol}: {exc}") from exc
        except RuntimeError:
            raise

    try:
        if symbol_is_crypto(data_symbol):
            bars, source = load_crypto_network_bars(config, data_symbol, multiplier, timespan)
        else:
            mt5_result = _try_mt5_fetch()
            if mt5_result is None:
                raise ExternalMarketDataUnavailableError(f"No MT5 broker fetch path available for {broker_symbol or data_symbol}")
            return mt5_result
        if not has_plausible_price_scale(data_symbol, bars):
            raise RuntimeError(f"Fetched implausible price scale for {data_symbol}; refusing to persist suspect bars.")
        try:
            DuckDBMarketDataStore(config.mt5.database_path).upsert_bars(bars, timeframe=scoped_timeframe, source=source)
        except (duckdb.IOException, RuntimeError):
            return build_features_with_events(config, data_symbol, bars), f"{source}_direct"
        persisted = cache_store.load_bars(data_symbol, scoped_timeframe, len(bars))
        if persisted:
            return build_features_with_events(config, data_symbol, persisted), source
        return build_features_with_events(config, data_symbol, bars), f"{source}_direct"
    except (MT5Error, ExternalMarketDataUnavailableError):
        if source_preference not in {"broker_only", "external_only"} and broker_symbol:
            try:
                mt5_result = _try_mt5_fetch()
                if mt5_result is not None:
                    return mt5_result
            except MT5Error as exc:
                mt5_errors.append(str(exc))
        cached_result = load_cached_variant_bars(
            cache_store,
            data_symbol,
            multiplier,
            timespan,
            cache_limit=cache_limit_value,
            base_cache_limit=base_cache_limit,
            cache_symbol_candidates_fn=cache_symbol_candidates_fn,
            variant_timeframe_key_fn=variant_timeframe_key_fn,
            has_plausible_price_scale_fn=has_plausible_price_scale,
            write_store=write_store,
        )
        if cached_result is not None:
            cached_bars, cached_source = cached_result
            return build_features_with_events(config, data_symbol, cached_bars), cached_source
        if mt5_errors:
            raise RuntimeError("; ".join(mt5_errors)) from None
        raise
