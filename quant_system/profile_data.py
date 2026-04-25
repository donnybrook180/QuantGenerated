from __future__ import annotations

import copy

from quant_system.config import SystemConfig
from quant_system.costs import apply_prop_cost_profile
from quant_system.data.market_data import DuckDBMarketDataStore
from quant_system.execution_tuning import apply_execution_mode_overrides
from quant_system.integrations.mt5 import MT5Client
from quant_system.models import FeatureVector, MarketBar
from quant_system.profiles import StrategyProfile
from quant_system.research.features import build_feature_library
from quant_system.research.funding import apply_broker_funding_context, load_broker_funding_context


def _load_cached_bars(store: DuckDBMarketDataStore, symbol: str, timeframe: str) -> list[MarketBar]:
    return store.load_bars(symbol, timeframe, 50_000)


def _timeframe_to_mt5_label(multiplier: int, timespan: str) -> str:
    if timespan != "minute":
        return "M5"
    return {1: "M1", 5: "M5", 15: "M15", 30: "M30"}.get(multiplier, "M5")


def _history_bar_count(history_days: int, multiplier: int, symbol: str) -> int:
    if symbol.upper() in {"SPY", "QQQ", "AAPL", "AMD", "META", "MSFT", "NVDA", "TSLA"}:
        trading_minutes_per_day = 390
    else:
        trading_minutes_per_day = 24 * 60
    return max(int((history_days * trading_minutes_per_day) / max(multiplier, 1)), 500)


def _load_mt5_bars(
    config: SystemConfig,
    data_symbol: str,
    broker_symbol: str,
    multiplier: int,
    timespan: str,
    scoped_timeframe: str,
) -> tuple[list[MarketBar], str]:
    mt5_config = copy.deepcopy(config.mt5)
    mt5_config.symbol = broker_symbol
    mt5_config.timeframe = _timeframe_to_mt5_label(multiplier, timespan)
    mt5_config.history_bars = _history_bar_count(config.market_data.history_days, multiplier, data_symbol)
    client = MT5Client(mt5_config)
    client.initialize()
    try:
        bars = client.fetch_bars()
    finally:
        client.shutdown()
    if not bars:
        raise RuntimeError(f"No MT5 bars loaded for {broker_symbol}/{scoped_timeframe}.")
    store = DuckDBMarketDataStore(config.mt5.database_path)
    store.upsert_bars(bars, timeframe=scoped_timeframe, source="mt5")
    persisted = store.load_bars(data_symbol, scoped_timeframe, len(bars))
    return (persisted or bars), "mt5"


def configure_profile_execution(config: SystemConfig, profile: StrategyProfile) -> None:
    if profile.name == "us500_trend":
        config.execution.min_bars_between_trades = 10
        config.execution.max_holding_bars = 18
        config.execution.stop_loss_atr_multiple = 1.0
        config.execution.take_profit_atr_multiple = 2.2
        config.execution.break_even_atr_multiple = 0.7
        config.execution.trailing_stop_atr_multiple = 0.9
        config.execution.stale_breakout_bars = 4
        config.execution.stale_breakout_atr_fraction = 0.08
        config.execution.structure_exit_bars = 0
        config.execution.order_size = 1.0
    elif profile.name == "us100_trend":
        config.execution.min_bars_between_trades = 12
        config.execution.max_holding_bars = 24
        config.execution.stop_loss_atr_multiple = 1.2
        config.execution.take_profit_atr_multiple = 2.8
        config.execution.break_even_atr_multiple = 0.9
        config.execution.trailing_stop_atr_multiple = 1.0
        config.execution.stale_breakout_bars = 0
        config.execution.stale_breakout_atr_fraction = 0.0
        config.execution.structure_exit_bars = 0
    elif profile.name == "ger40_orb":
        config.execution.min_bars_between_trades = 6
        config.execution.max_holding_bars = 0
        config.execution.stop_loss_atr_multiple = 2.2
        config.execution.take_profit_atr_multiple = 1.2
        config.execution.break_even_atr_multiple = 0.45
        config.execution.trailing_stop_atr_multiple = 0.6
        config.execution.stale_breakout_bars = 5
        config.execution.stale_breakout_atr_fraction = 0.08
        config.execution.structure_exit_bars = 3
        config.execution.order_size = 1.0
    elif profile.name == "xauusd_volatility":
        config.execution.min_bars_between_trades = 30
        config.execution.max_holding_bars = 18
        config.execution.stop_loss_atr_multiple = 1.4
        config.execution.take_profit_atr_multiple = 2.4
        config.execution.break_even_atr_multiple = 0.45
        config.execution.trailing_stop_atr_multiple = 0.85
        config.execution.stale_breakout_bars = 6
        config.execution.stale_breakout_atr_fraction = 0.2
        config.execution.structure_exit_bars = 4
    apply_prop_cost_profile(config, profile.broker_symbol or profile.data_symbol, profile.broker_symbol)
    apply_execution_mode_overrides(config)


def configure_profile_optimization(config: SystemConfig, profile: StrategyProfile) -> None:
    if profile.name == "us500_trend":
        config.optimization.train_bars = 160
        config.optimization.test_bars = 40
        config.optimization.step_bars = 40
        config.optimization.n_trials = 30
    elif profile.name == "us100_trend":
        config.optimization.train_bars = 120
        config.optimization.test_bars = 40
        config.optimization.step_bars = 40
        config.optimization.n_trials = 30
    elif profile.name == "ger40_orb":
        config.optimization.train_bars = 160
        config.optimization.test_bars = 40
        config.optimization.step_bars = 40
        config.optimization.n_trials = 30
    elif profile.name == "xauusd_volatility":
        config.optimization.train_bars = 240
        config.optimization.test_bars = 120
        config.optimization.step_bars = 60
        config.optimization.n_trials = 40


def load_features(config: SystemConfig, profile: StrategyProfile) -> tuple[list[FeatureVector], str]:
    config.market_data.symbol = profile.data_symbol
    if profile.name == "ger40_orb":
        config.market_data.history_days = max(config.market_data.history_days, 365)
    elif profile.name == "us500_trend":
        config.market_data.history_days = max(config.market_data.history_days, 365)
    config.mt5.symbol = profile.broker_symbol
    store = DuckDBMarketDataStore(config.mt5.database_path)
    timeframe = f"{config.market_data.multiplier}_{config.market_data.timespan}"
    scoped_timeframe = f"{profile.name}_{timeframe}"
    persisted_bars: list[MarketBar] = []
    data_source = "mt5"
    if config.market_data.fetch_policy in {"cache_first", "cache_only"}:
        persisted_bars = _load_cached_bars(store, config.market_data.symbol, scoped_timeframe)
        if persisted_bars:
            config.instrument.profile_name = profile.name
            config.instrument.data_symbol = config.market_data.symbol
            config.instrument.broker_symbol = config.mt5.symbol
            config.execution.symbol = config.market_data.symbol
            features = build_feature_library(persisted_bars)
            funding_context = load_broker_funding_context(config, profile.data_symbol, profile.broker_symbol)
            return apply_broker_funding_context(features, funding_context), "duckdb_cache"
        if config.market_data.fetch_policy == "cache_only":
            raise RuntimeError(f"No cached DuckDB bars available for {config.market_data.symbol}/{scoped_timeframe}.")
    persisted_bars, data_source = _load_mt5_bars(
        config,
        profile.data_symbol,
        profile.broker_symbol,
        config.market_data.multiplier,
        config.market_data.timespan,
        scoped_timeframe,
    )
    if profile.name == "ger40_orb":
        persisted_bars = scale_proxy_bars(persisted_bars, multiplier=500.0)
    if not persisted_bars:
        raise RuntimeError("No market data bars were loaded into DuckDB.")
    config.instrument.profile_name = profile.name
    config.instrument.data_symbol = config.market_data.symbol
    config.instrument.broker_symbol = config.mt5.symbol
    config.execution.symbol = config.market_data.symbol
    features = build_feature_library(persisted_bars)
    funding_context = load_broker_funding_context(config, profile.data_symbol, profile.broker_symbol)
    return apply_broker_funding_context(features, funding_context), data_source


def scale_proxy_bars(bars: list[MarketBar], multiplier: float) -> list[MarketBar]:
    return [
        MarketBar(
            timestamp=bar.timestamp,
            symbol=bar.symbol,
            open=bar.open * multiplier,
            high=bar.high * multiplier,
            low=bar.low * multiplier,
            close=bar.close * multiplier,
            volume=bar.volume,
        )
        for bar in bars
    ]


def load_shadow_features(config: SystemConfig, profile: StrategyProfile) -> tuple[list[FeatureVector], str]:
    if profile.name != "us100_trend":
        return load_features(config, profile)

    shadow_config = copy.deepcopy(config)
    shadow_config.market_data.symbol = profile.data_symbol
    shadow_config.market_data.timespan = "minute"
    shadow_config.market_data.multiplier = 1
    shadow_config.market_data.history_days = max(config.market_data.history_days, 45)
    shadow_config.mt5.symbol = profile.broker_symbol
    store = DuckDBMarketDataStore(shadow_config.mt5.database_path)
    timeframe = f"{shadow_config.market_data.multiplier}_{shadow_config.market_data.timespan}"
    scoped_timeframe = f"{profile.name}_shadow_{timeframe}"
    persisted_bars: list[MarketBar] = []
    data_source = "mt5"
    if shadow_config.market_data.fetch_policy in {"cache_first", "cache_only"}:
        persisted_bars = _load_cached_bars(store, shadow_config.market_data.symbol, scoped_timeframe)
        if persisted_bars:
            features = build_feature_library(persisted_bars)
            funding_context = load_broker_funding_context(shadow_config, profile.data_symbol, profile.broker_symbol)
            return apply_broker_funding_context(features, funding_context), "duckdb_cache"
        if shadow_config.market_data.fetch_policy == "cache_only":
            raise RuntimeError(f"No cached DuckDB bars available for {shadow_config.market_data.symbol}/{scoped_timeframe}.")
    persisted_bars, data_source = _load_mt5_bars(
        shadow_config,
        profile.data_symbol,
        profile.broker_symbol,
        shadow_config.market_data.multiplier,
        shadow_config.market_data.timespan,
        scoped_timeframe,
    )
    if not persisted_bars:
        raise RuntimeError("No shadow market data bars were loaded into DuckDB.")
    features = build_feature_library(persisted_bars)
    funding_context = load_broker_funding_context(shadow_config, profile.data_symbol, profile.broker_symbol)
    return apply_broker_funding_context(features, funding_context), data_source
