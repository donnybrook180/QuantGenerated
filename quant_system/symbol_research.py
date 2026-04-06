from __future__ import annotations

import asyncio
import csv
import itertools
import copy
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

from quant_system.app import export_closed_trade_artifacts
from quant_system.ai.models import AgentDescriptor
from quant_system.ai.storage import ExperimentStore
from quant_system.agents.base import Agent
from quant_system.agents.crypto import CryptoBreakoutReclaimAgent, CryptoTrendPullbackAgent, CryptoVolatilityExpansionAgent
from quant_system.agents.forex import ForexBreakoutMomentumAgent, ForexRangeReversionAgent, ForexTrendContinuationAgent
from quant_system.agents.strategies import OpeningRangeBreakoutAgent, VolatilityBreakoutAgent
from quant_system.agents.trend import MeanReversionAgent, MomentumConfirmationAgent, RiskSentinelAgent, TrendAgent
from quant_system.agents.xauusd import XAUUSDVolatilityBreakoutAgent
from quant_system.catalog_runtime import build_agents_from_catalog_paths
from quant_system.config import SystemConfig
from quant_system.data.market_data import DuckDBMarketDataStore
from quant_system.execution.broker import SimulatedBroker
from quant_system.execution.engine import AgentCoordinator, EventDrivenEngine, ExecutionResult
from quant_system.integrations.polygon_data import PolygonDataClient, PolygonError
from quant_system.models import FeatureVector, MarketBar
from quant_system.monitoring.heartbeat import HeartbeatMonitor
from quant_system.research.features import build_feature_library
from quant_system.risk.limits import RiskManager
from quant_system.symbols import resolve_symbol_request


ARTIFACTS_DIR = Path("artifacts")


@dataclass(slots=True)
class CandidateSpec:
    name: str
    description: str
    agents: list[Agent]
    code_path: str
    execution_overrides: dict[str, float | int] | None = None
    variant_label: str = ""
    timeframe_label: str = ""
    session_label: str = ""


@dataclass(slots=True)
class CandidateResult:
    name: str
    description: str
    archetype: str
    code_path: str
    realized_pnl: float
    closed_trades: int
    win_rate_pct: float
    profit_factor: float
    max_drawdown_pct: float
    total_costs: float
    trade_log_path: str = ""
    trade_analysis_path: str = ""
    variant_label: str = ""
    timeframe_label: str = ""
    session_label: str = ""
    train_pnl: float = 0.0
    validation_pnl: float = 0.0
    test_pnl: float = 0.0
    validation_profit_factor: float = 0.0
    test_profit_factor: float = 0.0
    validation_closed_trades: int = 0
    test_closed_trades: int = 0


def _symbol_slug(symbol: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in symbol).strip("_")


def _is_crypto_symbol(symbol: str) -> bool:
    upper = symbol.upper()
    return "BTC" in upper or "ETH" in upper


def _is_metal_symbol(symbol: str) -> bool:
    return "XAU" in symbol.upper()


def _is_forex_symbol(symbol: str) -> bool:
    upper = symbol.upper()
    return upper.endswith("USD") or upper.endswith("JPY") or upper.startswith("EUR") or upper.startswith("GBP") or upper.startswith("AUD")


def _symbol_research_history_days(config: SystemConfig, symbol: str) -> int:
    base_history = max(config.symbol_research.history_days, config.polygon.history_days)
    if _is_crypto_symbol(symbol):
        return max(base_history, 365)
    if _is_metal_symbol(symbol) or _is_forex_symbol(symbol):
        return max(base_history, 180)
    return max(base_history, 180)


def _build_engine(config: SystemConfig, agents: list[Agent]) -> EventDrivenEngine:
    broker = SimulatedBroker(
        initial_cash=config.execution.initial_cash,
        fee_bps=config.execution.fee_bps,
        commission_per_unit=config.execution.commission_per_unit,
        slippage_bps=config.execution.slippage_bps,
    )
    engine = EventDrivenEngine(
        coordinator=AgentCoordinator(agents, consensus_min_confidence=config.agents.consensus_min_confidence),
        broker=broker,
        risk_manager=RiskManager(config=config.risk, starting_equity=config.execution.initial_cash),
        heartbeat=HeartbeatMonitor(config.heartbeat),
        quantity=config.execution.order_size,
    )
    engine.min_bars_between_trades = config.execution.min_bars_between_trades
    engine.max_holding_bars = config.execution.max_holding_bars
    engine.stop_loss_atr_multiple = config.execution.stop_loss_atr_multiple
    engine.take_profit_atr_multiple = config.execution.take_profit_atr_multiple
    engine.break_even_atr_multiple = config.execution.break_even_atr_multiple
    engine.trailing_stop_atr_multiple = config.execution.trailing_stop_atr_multiple
    engine.stale_breakout_bars = config.execution.stale_breakout_bars
    engine.stale_breakout_atr_fraction = config.execution.stale_breakout_atr_fraction
    engine.structure_exit_bars = config.execution.structure_exit_bars
    return engine


def _with_execution_overrides(config: SystemConfig, overrides: dict[str, float | int] | None) -> SystemConfig:
    tuned = copy.deepcopy(config)
    if overrides:
        for key, value in overrides.items():
            setattr(tuned.execution, key, value)
    return tuned


def _configure_symbol_execution(config: SystemConfig, symbol: str) -> None:
    upper = symbol.upper()
    if "XAU" in upper:
        config.execution.min_bars_between_trades = 30
        config.execution.max_holding_bars = 18
        config.execution.stop_loss_atr_multiple = 1.4
        config.execution.take_profit_atr_multiple = 2.4
        config.execution.break_even_atr_multiple = 0.45
        config.execution.trailing_stop_atr_multiple = 0.85
        config.execution.stale_breakout_bars = 6
        config.execution.stale_breakout_atr_fraction = 0.2
        config.execution.structure_exit_bars = 4
    elif "BTC" in upper or "ETH" in upper:
        config.execution.min_bars_between_trades = 18
        config.execution.max_holding_bars = 30
        config.execution.stop_loss_atr_multiple = 1.6
        config.execution.take_profit_atr_multiple = 3.0
        config.execution.break_even_atr_multiple = 0.7
        config.execution.trailing_stop_atr_multiple = 1.1
        config.execution.stale_breakout_bars = 8
        config.execution.stale_breakout_atr_fraction = 0.18
        config.execution.structure_exit_bars = 5
    elif upper.endswith("USD") or upper.endswith("JPY") or upper.startswith("EUR") or upper.startswith("GBP") or upper.startswith("AUD"):
        config.execution.min_bars_between_trades = 10
        config.execution.max_holding_bars = 26
        config.execution.stop_loss_atr_multiple = 1.1
        config.execution.take_profit_atr_multiple = 2.1
        config.execution.break_even_atr_multiple = 0.6
        config.execution.trailing_stop_atr_multiple = 0.8
        config.execution.stale_breakout_bars = 6
        config.execution.stale_breakout_atr_fraction = 0.12
        config.execution.structure_exit_bars = 4
    else:
        config.execution.min_bars_between_trades = 12
        config.execution.max_holding_bars = 24
        config.execution.stop_loss_atr_multiple = 1.2
        config.execution.take_profit_atr_multiple = 2.4
        config.execution.break_even_atr_multiple = 0.8
        config.execution.trailing_stop_atr_multiple = 1.0
        config.execution.stale_breakout_bars = 5
        config.execution.stale_breakout_atr_fraction = 0.1
        config.execution.structure_exit_bars = 3


def _load_symbol_features(config: SystemConfig, data_symbol: str) -> tuple[list[FeatureVector], str]:
    return _load_symbol_features_variant(config, data_symbol, config.polygon.multiplier, config.polygon.timespan)


def _research_variant_plan(profile_symbol: str, mode: str) -> tuple[list[tuple[str, int, str]], tuple[str, ...], bool]:
    if _is_crypto_symbol(profile_symbol):
        if mode == "seed":
            return [("5m", 5, "minute")], ("all", "europe"), True
        return [("5m", 5, "minute"), ("15m", 15, "minute")], ("all", "europe", "us", "overlap"), True
    if _is_metal_symbol(profile_symbol):
        if mode == "seed":
            return [("5m", 5, "minute")], ("europe", "us"), True
        return [("5m", 5, "minute"), ("15m", 15, "minute")], ("europe", "us", "overlap"), True
    if _is_forex_symbol(profile_symbol):
        if mode == "seed":
            return [("15m", 15, "minute")], ("europe", "overlap"), True
        return [("5m", 5, "minute"), ("15m", 15, "minute"), ("30m", 30, "minute")], ("europe", "us", "overlap"), True
    return [("5m", 5, "minute")], ("all",), False


def _variant_timeframe_key(data_symbol: str, multiplier: int, timespan: str) -> str:
    return f"symbol_research_{_symbol_slug(data_symbol)}_{multiplier}_{timespan}"


def _detect_research_mode(config: SystemConfig, profile_symbol: str, data_symbol: str) -> str:
    requested_mode = config.symbol_research.mode
    if requested_mode in {"seed", "full"}:
        return requested_mode
    symbol_specific = _is_crypto_symbol(profile_symbol) or _is_metal_symbol(profile_symbol) or _is_forex_symbol(profile_symbol)
    if not symbol_specific:
        return "full"

    store = DuckDBMarketDataStore(config.mt5.database_path)
    timeframe_specs, _, _ = _research_variant_plan(profile_symbol, "full")
    for _, multiplier, timespan in timeframe_specs:
        scoped_timeframe = _variant_timeframe_key(data_symbol, multiplier, timespan)
        bars = store.load_bars(data_symbol, scoped_timeframe, 2_500)
        if len(bars) < 500:
            return "seed"
    return "full"


def _load_symbol_features_variant(
    config: SystemConfig,
    data_symbol: str,
    multiplier: int,
    timespan: str,
) -> tuple[list[FeatureVector], str]:
    config.polygon.symbol = data_symbol
    store = DuckDBMarketDataStore(config.mt5.database_path)
    timeframe = f"{multiplier}_{timespan}"
    scoped_timeframe = f"symbol_research_{_symbol_slug(data_symbol)}_{timeframe}"

    if config.polygon.fetch_policy in {"cache_first", "cache_only"}:
        cached = store.load_bars(data_symbol, scoped_timeframe, 50_000)
        if cached:
            return build_feature_library(cached), "duckdb_cache"
        if config.polygon.fetch_policy == "cache_only":
            raise RuntimeError(f"No cached DuckDB bars available for {data_symbol}/{scoped_timeframe}.")

    try:
        variant_config = copy.deepcopy(config.polygon)
        variant_config.symbol = data_symbol
        variant_config.multiplier = multiplier
        variant_config.timespan = timespan
        variant_config.history_days = config.polygon.history_days
        client = PolygonDataClient(variant_config)
        bars = client.fetch_bars()
        store.upsert_bars(bars, timeframe=scoped_timeframe, source="polygon")
        persisted = store.load_bars(data_symbol, scoped_timeframe, len(bars))
        if not persisted:
            raise RuntimeError(f"No Polygon bars were loaded into DuckDB for {data_symbol}.")
        return build_feature_library(persisted), "polygon"
    except PolygonError:
        cached = store.load_bars(data_symbol, scoped_timeframe, 50_000)
        if cached:
            return build_feature_library(cached), "duckdb_cache"
        raise


def _filter_weekday_bars(bars: list[MarketBar]) -> list[MarketBar]:
    return [bar for bar in bars if bar.timestamp.weekday() < 5]


def _filter_weekday_features(features: list[FeatureVector]) -> list[FeatureVector]:
    return [feature for feature in features if feature.timestamp.weekday() < 5]


def _filter_features_by_session(features: list[FeatureVector], session_name: str) -> list[FeatureVector]:
    if session_name == "all":
        return features

    if session_name == "europe":
        allowed_hours = set(range(7, 13))
    elif session_name == "us":
        allowed_hours = set(range(13, 21))
    elif session_name == "overlap":
        allowed_hours = set(range(12, 17))
    else:
        return features

    return [feature for feature in features if int(feature.values.get("hour_of_day", feature.timestamp.hour)) in allowed_hours]


def _build_symbol_feature_variants(
    config: SystemConfig,
    profile_symbol: str,
    data_symbol: str,
) -> tuple[dict[str, list[FeatureVector]], str, str]:
    mode = _detect_research_mode(config, profile_symbol, data_symbol)
    if not (_is_crypto_symbol(profile_symbol) or _is_metal_symbol(profile_symbol) or _is_forex_symbol(profile_symbol)):
        features, data_source = _load_symbol_features(config, data_symbol)
        return {"default": features}, data_source, mode

    variants: dict[str, list[FeatureVector]] = {}
    data_sources: list[str] = []
    timeframe_specs, session_names, weekday_only = _research_variant_plan(profile_symbol, mode)

    for timeframe_label, multiplier, timespan in timeframe_specs:
        timeframe_features, data_source = _load_symbol_features_variant(config, data_symbol, multiplier, timespan)
        if weekday_only:
            timeframe_features = _filter_weekday_features(timeframe_features)
        data_sources.append(data_source)
        for session_name in session_names:
            filtered = _filter_features_by_session(timeframe_features, session_name)
            if len(filtered) < 50:
                continue
            variants[f"{timeframe_label}_{session_name}"] = filtered

    resolved_source = "polygon" if "polygon" in data_sources else (data_sources[0] if data_sources else "unknown")
    return variants or {"default": []}, resolved_source, mode


def load_execution_features_for_variant(
    config: SystemConfig,
    profile_symbol: str,
    data_symbol: str,
    variant_label: str,
) -> tuple[list[FeatureVector], str]:
    if not variant_label or variant_label == "default":
        return _load_symbol_features(config, data_symbol)

    timeframe_label, _, session_label = variant_label.partition("_")
    if timeframe_label.endswith("m") and timeframe_label[:-1].isdigit():
        multiplier = int(timeframe_label[:-1])
        timespan = "minute"
    else:
        return _load_symbol_features(config, data_symbol)

    features, data_source = _load_symbol_features_variant(config, data_symbol, multiplier, timespan)
    if _is_crypto_symbol(profile_symbol) or _is_metal_symbol(profile_symbol) or _is_forex_symbol(profile_symbol):
        features = _filter_weekday_features(features)
    return _filter_features_by_session(features, session_label or "all"), data_source


def _evaluate_execution_candidate_set(
    config: SystemConfig,
    profile_symbol: str,
    data_symbol: str,
    selected_candidates: list[dict[str, object]],
) -> tuple[ExecutionResult, str, str]:
    target_variant = str(selected_candidates[0].get("variant_label", "") or "")
    features, data_source = load_execution_features_for_variant(config, profile_symbol, data_symbol, target_variant)
    agents = build_agents_from_catalog_paths([str(row["code_path"]) for row in selected_candidates], config)
    engine = _build_engine(config, agents)
    result = asyncio.run(engine.run(features, sleep_seconds=0.0))
    return result, data_source, target_variant or "default"


def _candidate_specs(config: SystemConfig, data_symbol: str) -> list[CandidateSpec]:
    upper = data_symbol.upper()
    risk = RiskSentinelAgent(
        max_volatility=config.risk.max_volatility,
        min_relative_volume=config.agents.min_relative_volume,
    )
    specs = [
        CandidateSpec(
            name="trend",
            description="EMA trend continuation",
            agents=[
                TrendAgent(
                    fast_window=config.agents.trend_fast_window,
                    slow_window=config.agents.trend_slow_window,
                    min_trend_strength=config.agents.min_trend_strength,
                    min_relative_volume=config.agents.min_relative_volume,
                ),
                risk,
            ],
            code_path="quant_system.agents.trend.TrendAgent",
        ),
        CandidateSpec(
            name="momentum",
            description="Momentum confirmation",
            agents=[MomentumConfirmationAgent(config.agents.mean_reversion_threshold), risk],
            code_path="quant_system.agents.trend.MomentumConfirmationAgent",
        ),
        CandidateSpec(
            name="mean_reversion",
            description="Intraday mean reversion",
            agents=[MeanReversionAgent(config.agents.mean_reversion_window, config.agents.mean_reversion_threshold), risk],
            code_path="quant_system.agents.trend.MeanReversionAgent",
        ),
        CandidateSpec(
            name="volatility_breakout",
            description="Generic volatility breakout",
            agents=[VolatilityBreakoutAgent(lookback=max(8, config.agents.mean_reversion_window)), risk],
            code_path="quant_system.agents.strategies.VolatilityBreakoutAgent",
        ),
        CandidateSpec(
            name="opening_range_breakout",
            description="Opening range breakout",
            agents=[OpeningRangeBreakoutAgent(), risk],
            code_path="quant_system.agents.strategies.OpeningRangeBreakoutAgent",
        ),
    ]
    if "BTC" in upper or "ETH" in upper:
        return [
            CandidateSpec(
                name="crypto_trend_pullback",
                description="Crypto trend pullback continuation",
                agents=[CryptoTrendPullbackAgent(), risk],
                code_path="quant_system.agents.crypto.CryptoTrendPullbackAgent",
            ),
            CandidateSpec(
                name="crypto_breakout_reclaim",
                description="Crypto breakout reclaim",
                agents=[CryptoBreakoutReclaimAgent(), risk],
                code_path="quant_system.agents.crypto.CryptoBreakoutReclaimAgent",
            ),
            CandidateSpec(
                name="crypto_volatility_expansion",
                description="Crypto volatility expansion",
                agents=[CryptoVolatilityExpansionAgent(), risk],
                code_path="quant_system.agents.crypto.CryptoVolatilityExpansionAgent",
            ),
            CandidateSpec(
                name="crypto_volatility_breakout",
                description="24/7 crypto volatility breakout",
                agents=[VolatilityBreakoutAgent(lookback=16, allowed_hours=None), risk],
                code_path="quant_system.agents.strategies.VolatilityBreakoutAgent",
            ),
        ]
    if "XAU" in upper:
        specs.append(
            CandidateSpec(
                name="xauusd_volatility_breakout",
                description="XAUUSD-tuned volatility breakout",
                agents=[XAUUSDVolatilityBreakoutAgent(lookback=max(6, config.agents.mean_reversion_window)), risk],
                code_path="quant_system.agents.xauusd.XAUUSDVolatilityBreakoutAgent",
            )
        )
        return specs
    if upper.endswith("USD") or upper.endswith("JPY") or upper.startswith("EUR") or upper.startswith("GBP") or upper.startswith("AUD"):
        return [
            CandidateSpec(
                name="forex_trend_continuation",
                description="Forex trend continuation",
                agents=[ForexTrendContinuationAgent(), risk],
                code_path="quant_system.agents.forex.ForexTrendContinuationAgent",
            ),
            CandidateSpec(
                name="forex_range_reversion",
                description="Forex range reversion",
                agents=[ForexRangeReversionAgent(), risk],
                code_path="quant_system.agents.forex.ForexRangeReversionAgent",
            ),
            CandidateSpec(
                name="forex_breakout_momentum",
                description="Forex breakout momentum",
                agents=[ForexBreakoutMomentumAgent(), risk],
                code_path="quant_system.agents.forex.ForexBreakoutMomentumAgent",
            ),
        ]
    return specs


def _score_result(name: str, description: str, archetype: str, code_path: str, result: ExecutionResult) -> CandidateResult:
    return CandidateResult(
        name=name,
        description=description,
        archetype=archetype,
        code_path=code_path,
        realized_pnl=result.realized_pnl,
        closed_trades=len(result.closed_trades),
        win_rate_pct=result.win_rate_pct,
        profit_factor=result.profit_factor,
        max_drawdown_pct=result.max_drawdown * 100.0,
        total_costs=result.total_costs,
    )


def _run_candidate(
    config: SystemConfig,
    features: list[FeatureVector],
    spec: CandidateSpec,
    archetype: str,
    artifact_prefix: str,
) -> CandidateResult:
    candidate_config = _with_execution_overrides(config, spec.execution_overrides)
    engine = _build_engine(candidate_config, copy.deepcopy(spec.agents))
    result = asyncio.run(engine.run(features, sleep_seconds=0.0))
    trades_path, analysis_path = export_closed_trade_artifacts(
        result.closed_trades,
        result.realized_pnl,
        artifact_prefix,
    )
    scored = _score_result(spec.name, spec.description, archetype, spec.code_path, result)
    scored.trade_log_path = str(trades_path)
    scored.trade_analysis_path = str(analysis_path)
    scored.variant_label = spec.variant_label
    scored.timeframe_label = spec.timeframe_label
    scored.session_label = spec.session_label
    return scored


def _split_features(features: list[FeatureVector]) -> tuple[list[FeatureVector], list[FeatureVector], list[FeatureVector]]:
    total = len(features)
    if total < 30:
        return features, [], []
    train_end = max(int(total * 0.6), 1)
    validation_end = max(int(total * 0.8), train_end + 1)
    train = features[:train_end]
    validation = features[train_end:validation_end]
    test = features[validation_end:]
    return train, validation, test


def _run_candidate_with_splits(
    config: SystemConfig,
    features: list[FeatureVector],
    spec: CandidateSpec,
    archetype: str,
    artifact_prefix: str,
) -> CandidateResult:
    scored = _run_candidate(config, features, spec, archetype, artifact_prefix)
    train_features, validation_features, test_features = _split_features(features)

    def _eval_slice(slice_features: list[FeatureVector]) -> ExecutionResult | None:
        if len(slice_features) < 10:
            return None
        candidate_config = _with_execution_overrides(config, spec.execution_overrides)
        engine = _build_engine(candidate_config, copy.deepcopy(spec.agents))
        return asyncio.run(engine.run(slice_features, sleep_seconds=0.0))

    train_result = _eval_slice(train_features)
    validation_result = _eval_slice(validation_features)
    test_result = _eval_slice(test_features)

    if train_result is not None:
        scored.train_pnl = train_result.realized_pnl
    if validation_result is not None:
        scored.validation_pnl = validation_result.realized_pnl
        scored.validation_profit_factor = validation_result.profit_factor
        scored.validation_closed_trades = len(validation_result.closed_trades)
    if test_result is not None:
        scored.test_pnl = test_result.realized_pnl
        scored.test_profit_factor = test_result.profit_factor
        scored.test_closed_trades = len(test_result.closed_trades)

    return scored


def _default_variant_features(feature_variants: dict[str, list[FeatureVector]]) -> list[FeatureVector]:
    for preferred in ("5m_all", "default", "15m_all"):
        if preferred in feature_variants and feature_variants[preferred]:
            return feature_variants[preferred]
    for features in feature_variants.values():
        if features:
            return features
    return []


def _auto_improvement_specs(config: SystemConfig, symbol: str, results: list[CandidateResult]) -> list[CandidateSpec]:
    upper = symbol.upper()
    specs: list[CandidateSpec] = []
    result_map = {row.name: row for row in results}
    risk = RiskSentinelAgent(
        max_volatility=config.risk.max_volatility,
        min_relative_volume=config.agents.min_relative_volume,
    )

    if "BTC" in upper or "ETH" in upper:
        best = max(results, key=lambda item: (item.realized_pnl, item.profit_factor, item.closed_trades), default=None)
        best_name = best.name if best is not None else ""

        trend_result = result_map.get("crypto_trend_pullback")
        if trend_result is not None:
            specs.extend(
                [
                    CandidateSpec(
                        name="crypto_trend_pullback_looser",
                        description="Crypto trend pullback with looser entry and softer exits",
                        agents=[
                            CryptoTrendPullbackAgent(
                                lookback=10,
                                min_trend_strength=0.0006,
                                min_momentum_20=0.0006,
                                z_score_low=-2.2,
                                z_score_high=0.2,
                                min_relative_volume=0.7,
                                min_atr_proxy=0.0015,
                            ),
                            RiskSentinelAgent(max_volatility=config.risk.max_volatility * 1.8, min_relative_volume=0.7),
                        ],
                        code_path="quant_system.agents.crypto.CryptoTrendPullbackAgent",
                        execution_overrides={"structure_exit_bars": 0, "max_holding_bars": 42, "stale_breakout_bars": 12},
                    ),
                    CandidateSpec(
                        name="crypto_trend_pullback_patient",
                        description="Crypto trend pullback with wider stop and longer hold",
                        agents=[
                            CryptoTrendPullbackAgent(
                                lookback=14,
                                min_trend_strength=0.0007,
                                min_momentum_20=0.0008,
                                z_score_low=-2.0,
                                z_score_high=0.1,
                                min_relative_volume=0.75,
                                min_atr_proxy=0.0018,
                            ),
                            RiskSentinelAgent(max_volatility=config.risk.max_volatility * 2.0, min_relative_volume=0.75),
                        ],
                        code_path="quant_system.agents.crypto.CryptoTrendPullbackAgent",
                        execution_overrides={
                            "structure_exit_bars": 0,
                            "max_holding_bars": 48,
                            "stop_loss_atr_multiple": 2.1,
                            "take_profit_atr_multiple": 3.4,
                        },
                    ),
                ]
            )

        if best_name in {"crypto_breakout_reclaim", "crypto_trend_pullback"} or not results:
            specs.append(
                CandidateSpec(
                    name="crypto_breakout_reclaim_looser",
                    description="Crypto breakout reclaim with looser reclaim and softer exits",
                    agents=[
                        CryptoBreakoutReclaimAgent(
                            lookback=16,
                            reclaim_buffer=0.9965,
                            min_trend_strength=0.00045,
                            min_momentum_20=0.0005,
                            min_relative_volume=0.75,
                            min_atr_proxy=0.0015,
                        ),
                        RiskSentinelAgent(max_volatility=config.risk.max_volatility * 2.0, min_relative_volume=0.7),
                    ],
                    code_path="quant_system.agents.crypto.CryptoBreakoutReclaimAgent",
                    execution_overrides={"structure_exit_bars": 0, "stale_breakout_bars": 10, "max_holding_bars": 40},
                )
            )

        specs.append(
            CandidateSpec(
                name="crypto_volatility_expansion_selective",
                description="Crypto volatility expansion with higher-quality trigger",
                agents=[
                    CryptoVolatilityExpansionAgent(
                        lookback=20,
                        min_atr_proxy=0.0024,
                        min_trend_strength=0.00045,
                        min_momentum_5=0.0007,
                        min_momentum_20=0.001,
                        min_relative_volume=0.85,
                    ),
                    RiskSentinelAgent(max_volatility=config.risk.max_volatility * 2.0, min_relative_volume=0.8),
                ],
                code_path="quant_system.agents.crypto.CryptoVolatilityExpansionAgent",
                execution_overrides={"structure_exit_bars": 0, "stale_breakout_bars": 10, "max_holding_bars": 36},
            )
        )
    elif "XAU" in upper:
        specs.extend(
            [
                CandidateSpec(
                    name="xauusd_volatility_breakout_looser",
                    description="XAUUSD breakout with slightly looser entries and softer exits",
                    agents=[XAUUSDVolatilityBreakoutAgent(lookback=8), risk],
                    code_path="quant_system.agents.xauusd.XAUUSDVolatilityBreakoutAgent",
                    execution_overrides={"structure_exit_bars": 0, "stale_breakout_bars": 8, "max_holding_bars": 22},
                ),
                CandidateSpec(
                    name="xauusd_generic_breakout_selective",
                    description="XAUUSD generic breakout with tighter trade filtering",
                    agents=[VolatilityBreakoutAgent(lookback=10, allowed_hours={13, 14, 15, 16}), risk],
                    code_path="quant_system.agents.strategies.VolatilityBreakoutAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 7,
                        "take_profit_atr_multiple": 2.8,
                        "trailing_stop_atr_multiple": 0.9,
                    },
                ),
            ]
        )
    elif upper in {"US500", "US100"}:
        specs.extend(
            [
                CandidateSpec(
                    name=f"{upper.lower()}_trend_density",
                    description=f"{upper} trend candidate with slightly higher trade density",
                    agents=[
                        TrendAgent(
                            fast_window=8,
                            slow_window=24,
                            min_trend_strength=max(config.agents.min_trend_strength * 0.7, 0.0008),
                            min_relative_volume=max(config.agents.min_relative_volume * 0.9, 0.7),
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.trend.TrendAgent",
                    execution_overrides={"structure_exit_bars": 0, "stale_breakout_bars": 6, "max_holding_bars": 20},
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_momentum_selective",
                    description=f"{upper} momentum candidate with stricter holding logic",
                    agents=[MomentumConfirmationAgent(config.agents.mean_reversion_threshold * 0.8), risk],
                    code_path="quant_system.agents.trend.MomentumConfirmationAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 5,
                        "take_profit_atr_multiple": 2.6,
                        "trailing_stop_atr_multiple": 0.85,
                    },
                ),
            ]
        )
    elif upper == "GER40":
        specs.extend(
            [
                CandidateSpec(
                    name="ger40_orb_patient",
                    description="GER40 opening range breakout with slower stale exit",
                    agents=[OpeningRangeBreakoutAgent(), risk],
                    code_path="quant_system.agents.strategies.OpeningRangeBreakoutAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 7,
                        "stop_loss_atr_multiple": 2.4,
                        "take_profit_atr_multiple": 1.4,
                    },
                ),
                CandidateSpec(
                    name="ger40_volatility_breakout",
                    description="GER40 generic breakout candidate",
                    agents=[VolatilityBreakoutAgent(lookback=12, allowed_hours={14}), risk],
                    code_path="quant_system.agents.strategies.VolatilityBreakoutAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 5,
                        "max_holding_bars": 18,
                    },
                ),
            ]
        )
    elif upper.endswith("USD") or upper.endswith("JPY") or upper.startswith("EUR") or upper.startswith("GBP") or upper.startswith("AUD"):
        specs.extend(
            [
                CandidateSpec(
                    name="forex_trend_continuation_looser",
                    description="Forex trend continuation with higher trade density",
                    agents=[
                        ForexTrendContinuationAgent(
                            lookback=12,
                            min_trend_strength=0.00018,
                            min_momentum_20=0.00015,
                            min_relative_volume=0.65,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.forex.ForexTrendContinuationAgent",
                    execution_overrides={"structure_exit_bars": 0, "stale_breakout_bars": 7, "max_holding_bars": 30},
                ),
                CandidateSpec(
                    name="forex_breakout_momentum_patient",
                    description="Forex breakout momentum with slower exits",
                    agents=[
                        ForexBreakoutMomentumAgent(
                            lookback=16,
                            min_atr_proxy=0.00028,
                            min_momentum_5=0.00018,
                            min_momentum_20=0.00022,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.forex.ForexBreakoutMomentumAgent",
                    execution_overrides={"structure_exit_bars": 0, "stale_breakout_bars": 8, "max_holding_bars": 32},
                ),
            ]
        )
    return specs


def _parameter_sweep_specs(config: SystemConfig, symbol: str) -> list[CandidateSpec]:
    upper = symbol.upper()
    specs: list[CandidateSpec] = []

    if "BTC" in upper or "ETH" in upper:
        trend_variants = [
            ("balanced", 12, 0.00055, 0.00045, -2.1, 0.15, 0.65, 0.0014),
            ("dense", 9, 0.00035, 0.00030, -2.5, 0.40, 0.55, 0.0010),
            ("selective", 15, 0.00080, 0.00070, -1.9, 0.05, 0.75, 0.0018),
        ]
        for label, lookback, trend, mom20, z_low, z_high, rel_vol, atr in trend_variants:
            specs.append(
                CandidateSpec(
                    name=f"crypto_trend_pullback_sweep_{label}",
                    description=f"Crypto trend pullback sweep {label}",
                    agents=[
                        CryptoTrendPullbackAgent(
                            lookback=lookback,
                            min_trend_strength=trend,
                            min_momentum_20=mom20,
                            z_score_low=z_low,
                            z_score_high=z_high,
                            min_relative_volume=rel_vol,
                            min_atr_proxy=atr,
                        ),
                        RiskSentinelAgent(max_volatility=config.risk.max_volatility * 2.3, min_relative_volume=max(rel_vol - 0.05, 0.5)),
                    ],
                    code_path="quant_system.agents.crypto.CryptoTrendPullbackAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "max_holding_bars": 36 if label == "dense" else 48,
                        "stale_breakout_bars": 10 if label == "dense" else 14,
                        "min_bars_between_trades": 8 if label == "dense" else 12,
                    },
                )
            )

        reclaim_variants = [
            ("balanced", 16, 0.9965, 0.00040, 0.00045, 0.70, 0.0012),
            ("dense", 14, 0.9955, 0.00025, 0.00030, 0.60, 0.0010),
            ("selective", 20, 0.9975, 0.00060, 0.00065, 0.80, 0.0015),
        ]
        for label, lookback, reclaim, trend, mom20, rel_vol, atr in reclaim_variants:
            specs.append(
                CandidateSpec(
                    name=f"crypto_breakout_reclaim_sweep_{label}",
                    description=f"Crypto breakout reclaim sweep {label}",
                    agents=[
                        CryptoBreakoutReclaimAgent(
                            lookback=lookback,
                            reclaim_buffer=reclaim,
                            min_trend_strength=trend,
                            min_momentum_20=mom20,
                            min_relative_volume=rel_vol,
                            min_atr_proxy=atr,
                        ),
                        RiskSentinelAgent(max_volatility=config.risk.max_volatility * 2.4, min_relative_volume=max(rel_vol - 0.05, 0.5)),
                    ],
                    code_path="quant_system.agents.crypto.CryptoBreakoutReclaimAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "max_holding_bars": 40 if label == "dense" else 50,
                        "stale_breakout_bars": 9 if label == "dense" else 12,
                    },
                )
            )

        expansion_variants = [
            ("balanced", 18, 0.0022, 0.00035, 0.00055, 0.00085, 0.75),
            ("dense", 14, 0.0018, 0.00025, 0.00035, 0.00060, 0.65),
            ("selective", 22, 0.0028, 0.00050, 0.00075, 0.00110, 0.90),
        ]
        for label, lookback, atr, trend, mom5, mom20, rel_vol in expansion_variants:
            specs.append(
                CandidateSpec(
                    name=f"crypto_volatility_expansion_sweep_{label}",
                    description=f"Crypto volatility expansion sweep {label}",
                    agents=[
                        CryptoVolatilityExpansionAgent(
                            lookback=lookback,
                            min_atr_proxy=atr,
                            min_trend_strength=trend,
                            min_momentum_5=mom5,
                            min_momentum_20=mom20,
                            min_relative_volume=rel_vol,
                        ),
                        RiskSentinelAgent(max_volatility=config.risk.max_volatility * 2.5, min_relative_volume=max(rel_vol - 0.05, 0.55)),
                    ],
                    code_path="quant_system.agents.crypto.CryptoVolatilityExpansionAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "max_holding_bars": 34 if label == "dense" else 42,
                        "stale_breakout_bars": 8 if label == "dense" else 10,
                    },
                )
            )
    return specs


def _with_variant_name(spec: CandidateSpec, variant_label: str) -> CandidateSpec:
    if variant_label == "default":
        return spec
    timeframe_label, _, session_label = variant_label.partition("_")
    return CandidateSpec(
        name=f"{spec.name}__{variant_label}",
        description=f"{spec.description} [{variant_label}]",
        agents=spec.agents,
        code_path=spec.code_path,
        execution_overrides=spec.execution_overrides,
        variant_label=variant_label,
        timeframe_label=timeframe_label,
        session_label=session_label,
    )


def _analyze_trade_rows(path: str) -> dict[str, object]:
    trade_path = Path(path)
    if not trade_path.exists():
        return {}
    with trade_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return {"closed_trades": 0}

    exit_buckets: dict[str, float] = {}
    hour_buckets: dict[int, float] = {}
    pnls: list[float] = []
    for row in rows:
        pnl = float(row.get("pnl", "0") or 0.0)
        exit_reason = row.get("exit_reason", "unknown")
        entry_hour = int(float(row.get("entry_hour", "0") or 0.0))
        exit_buckets[exit_reason] = exit_buckets.get(exit_reason, 0.0) + pnl
        hour_buckets[entry_hour] = hour_buckets.get(entry_hour, 0.0) + pnl
        pnls.append(pnl)

    weakest_exit = min(exit_buckets.items(), key=lambda item: item[1]) if exit_buckets else None
    weakest_hour = min(hour_buckets.items(), key=lambda item: item[1]) if hour_buckets else None
    return {
        "closed_trades": len(rows),
        "mean_pnl": mean(pnls) if pnls else 0.0,
        "weakest_exit": weakest_exit[0] if weakest_exit else "",
        "weakest_exit_pnl": weakest_exit[1] if weakest_exit else 0.0,
        "weakest_hour": weakest_hour[0] if weakest_hour else None,
        "weakest_hour_pnl": weakest_hour[1] if weakest_hour else 0.0,
    }


def _second_pass_specs(config: SystemConfig, symbol: str, results: list[CandidateResult]) -> list[CandidateSpec]:
    upper = symbol.upper()
    specs: list[CandidateSpec] = []
    ranked = sorted(results, key=lambda item: (item.realized_pnl, item.profit_factor, item.closed_trades), reverse=True)
    best_tradeable = next((row for row in ranked if row.closed_trades > 0), None)
    if best_tradeable is None:
        return specs

    autopsy = _analyze_trade_rows(best_tradeable.trade_log_path)
    weakest_exit = str(autopsy.get("weakest_exit", ""))
    closed_trades = int(autopsy.get("closed_trades", 0) or 0)

    if "BTC" in upper or "ETH" in upper:
        if best_tradeable.name.startswith("crypto_trend_pullback"):
            if weakest_exit == "structure_exit":
                specs.append(
                    CandidateSpec(
                        name="crypto_trend_pullback_exit_relaxed",
                        description="Crypto trend pullback with structure exit disabled after autopsy",
                        agents=[
                            CryptoTrendPullbackAgent(
                                lookback=10,
                                min_trend_strength=0.0006,
                                min_momentum_20=0.0006,
                                z_score_low=-2.2,
                                z_score_high=0.2,
                                min_relative_volume=0.7,
                                min_atr_proxy=0.0015,
                            ),
                            RiskSentinelAgent(max_volatility=config.risk.max_volatility * 2.0, min_relative_volume=0.7),
                        ],
                        code_path="quant_system.agents.crypto.CryptoTrendPullbackAgent",
                        execution_overrides={
                            "structure_exit_bars": 0,
                            "stale_breakout_bars": 14,
                            "max_holding_bars": 54,
                            "stop_loss_atr_multiple": 2.2,
                            "take_profit_atr_multiple": 3.6,
                        },
                    )
                )
            if closed_trades <= 3:
                specs.append(
                    CandidateSpec(
                        name="crypto_trend_pullback_density",
                        description="Crypto trend pullback with more trade density",
                        agents=[
                            CryptoTrendPullbackAgent(
                                lookback=9,
                                min_trend_strength=0.00045,
                                min_momentum_20=0.00045,
                                z_score_low=-2.4,
                                z_score_high=0.35,
                                min_relative_volume=0.6,
                                min_atr_proxy=0.0012,
                            ),
                            RiskSentinelAgent(max_volatility=config.risk.max_volatility * 2.2, min_relative_volume=0.6),
                        ],
                        code_path="quant_system.agents.crypto.CryptoTrendPullbackAgent",
                        execution_overrides={"structure_exit_bars": 0, "max_holding_bars": 48, "min_bars_between_trades": 10},
                    )
                )
        elif best_tradeable.name.startswith("crypto_breakout_reclaim"):
            specs.append(
                CandidateSpec(
                    name="crypto_breakout_reclaim_patient",
                    description="Crypto breakout reclaim with slower exits after autopsy",
                    agents=[
                        CryptoBreakoutReclaimAgent(
                            lookback=14,
                            reclaim_buffer=0.996,
                            min_trend_strength=0.00035,
                            min_momentum_20=0.0004,
                            min_relative_volume=0.65,
                            min_atr_proxy=0.0012,
                        ),
                        RiskSentinelAgent(max_volatility=config.risk.max_volatility * 2.3, min_relative_volume=0.6),
                    ],
                    code_path="quant_system.agents.crypto.CryptoBreakoutReclaimAgent",
                    execution_overrides={"structure_exit_bars": 0, "stale_breakout_bars": 12, "max_holding_bars": 44},
                )
            )
    elif "XAU" in upper:
        if weakest_exit in {"signal_exit", "structure_exit"}:
            specs.append(
                CandidateSpec(
                    name="xauusd_volatility_breakout_exit_relaxed",
                    description="XAUUSD breakout with relaxed structure exit after autopsy",
                    agents=[XAUUSDVolatilityBreakoutAgent(lookback=8), RiskSentinelAgent(max_volatility=config.risk.max_volatility, min_relative_volume=0.75)],
                    code_path="quant_system.agents.xauusd.XAUUSDVolatilityBreakoutAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 9,
                        "max_holding_bars": 24,
                        "trailing_stop_atr_multiple": 0.95,
                    },
                )
            )
    elif upper in {"US500", "US100"}:
        if closed_trades <= 4:
            specs.append(
                CandidateSpec(
                    name=f"{upper.lower()}_trend_density_second_pass",
                    description=f"{upper} second-pass density variant",
                    agents=[
                        TrendAgent(
                            fast_window=7,
                            slow_window=22,
                            min_trend_strength=max(config.agents.min_trend_strength * 0.6, 0.0007),
                            min_relative_volume=0.65,
                        ),
                        RiskSentinelAgent(max_volatility=config.risk.max_volatility * 1.5, min_relative_volume=0.65),
                    ],
                    code_path="quant_system.agents.trend.TrendAgent",
                    execution_overrides={"structure_exit_bars": 0, "stale_breakout_bars": 6, "max_holding_bars": 22},
                )
            )
    elif upper == "GER40":
        if weakest_exit in {"stale_breakout", "structure_exit"}:
            specs.append(
                CandidateSpec(
                    name="ger40_orb_exit_relaxed",
                    description="GER40 ORB with relaxed stale/structure exit after autopsy",
                    agents=[OpeningRangeBreakoutAgent(), RiskSentinelAgent(max_volatility=config.risk.max_volatility, min_relative_volume=0.8)],
                    code_path="quant_system.agents.strategies.OpeningRangeBreakoutAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 8,
                        "take_profit_atr_multiple": 1.5,
                        "max_holding_bars": 0,
                    },
                )
            )
    elif upper.endswith("USD") or upper.endswith("JPY") or upper.startswith("EUR") or upper.startswith("GBP") or upper.startswith("AUD"):
        if best_tradeable.name.startswith("forex_trend_continuation") and closed_trades <= 4:
            specs.append(
                CandidateSpec(
                    name="forex_trend_continuation_second_pass",
                    description="Forex trend continuation second-pass density variant",
                    agents=[
                        ForexTrendContinuationAgent(
                            lookback=10,
                            min_trend_strength=0.00014,
                            min_momentum_20=0.00012,
                            min_relative_volume=0.6,
                        ),
                        RiskSentinelAgent(max_volatility=config.risk.max_volatility * 1.6, min_relative_volume=0.6),
                    ],
                    code_path="quant_system.agents.forex.ForexTrendContinuationAgent",
                    execution_overrides={"structure_exit_bars": 0, "stale_breakout_bars": 8, "max_holding_bars": 34},
                )
            )
        if weakest_exit in {"structure_exit", "signal_exit"}:
            specs.append(
                CandidateSpec(
                    name="forex_breakout_momentum_exit_relaxed",
                    description="Forex breakout momentum with relaxed exit after autopsy",
                    agents=[
                        ForexBreakoutMomentumAgent(
                            lookback=16,
                            min_atr_proxy=0.00025,
                            min_momentum_5=0.00016,
                            min_momentum_20=0.0002,
                        ),
                        RiskSentinelAgent(max_volatility=config.risk.max_volatility * 1.7, min_relative_volume=0.65),
                    ],
                    code_path="quant_system.agents.forex.ForexBreakoutMomentumAgent",
                    execution_overrides={"structure_exit_bars": 0, "stale_breakout_bars": 9, "max_holding_bars": 34},
                )
            )
    return specs


def _combined_specs(config: SystemConfig, specs: list[CandidateSpec], winners: list[CandidateResult]) -> list[CandidateSpec]:
    lookup = {spec.name: spec for spec in specs}
    positive = [
        winner
        for winner in winners
        if winner.name in lookup and winner.realized_pnl > 0 and winner.profit_factor >= 1.0
    ]
    positive = sorted(positive, key=lambda item: (item.realized_pnl, item.profit_factor), reverse=True)[:3]
    combined: list[CandidateSpec] = []
    for left, right in itertools.combinations(positive, 2):
        left_spec = lookup[left.name]
        right_spec = lookup[right.name]
        combo_agents = [agent for agent in left_spec.agents if agent.name != "risk_sentinel"]
        combo_agents.extend(agent for agent in right_spec.agents if agent.name != "risk_sentinel")
        combo_agents.append(
            RiskSentinelAgent(
                max_volatility=config.risk.max_volatility,
                min_relative_volume=config.agents.min_relative_volume,
            )
        )
        combined.append(
            CandidateSpec(
                name=f"{left.name}__plus__{right.name}",
                description=f"Combined {left.name} + {right.name}",
                agents=combo_agents,
                code_path=f"{left_spec.code_path};{right_spec.code_path}",
            )
        )
    return combined


def _component_set(code_path: str) -> set[str]:
    return {part.strip() for part in code_path.split(";") if part.strip()}


def select_execution_candidates(rows: list[dict[str, object]], max_candidates: int = 2) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    used_components: set[str] = set()
    target_variant: str | None = None
    viable_rows = [
        row
        for row in rows
        if int(row.get("validation_closed_trades", 0)) >= 3
        and int(row.get("test_closed_trades", 0)) >= 2
        and float(row.get("validation_pnl", 0.0)) > 0.0
        and float(row.get("test_pnl", 0.0)) > 0.0
        and float(row.get("validation_profit_factor", 0.0)) >= 1.0
        and float(row.get("test_profit_factor", 0.0)) >= 1.0
    ]
    ranked = sorted(
        viable_rows,
        key=lambda row: (
            bool(row.get("recommended")),
            float(row.get("test_pnl", 0.0)),
            float(row.get("validation_pnl", 0.0)),
            float(row.get("test_profit_factor", 0.0)),
            int(row.get("test_closed_trades", 0)),
        ),
        reverse=True,
    )
    for row in ranked:
        row_variant = str(row.get("variant_label", "") or "")
        if target_variant is not None and row_variant != target_variant:
            continue
        components = _component_set(str(row["code_path"]))
        if selected and components & used_components:
            continue
        selected.append(row)
        if target_variant is None:
            target_variant = row_variant
        used_components.update(components)
        if len(selected) >= max_candidates:
            break
    return selected


def _export_results(symbol: str, broker_symbol: str, data_source: str, rows: list[CandidateResult]) -> tuple[Path, Path]:
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    slug = _symbol_slug(symbol)
    csv_path = ARTIFACTS_DIR / f"{slug}_symbol_research.csv"
    txt_path = ARTIFACTS_DIR / f"{slug}_symbol_research.txt"

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "name",
                "description",
                "archetype",
                "realized_pnl",
                "closed_trades",
                "win_rate_pct",
                "profit_factor",
                "max_drawdown_pct",
                "total_costs",
                "train_pnl",
                "validation_pnl",
                "validation_profit_factor",
                "validation_closed_trades",
                "test_pnl",
                "test_profit_factor",
                "test_closed_trades",
                "trade_log_path",
                "trade_analysis_path",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.name,
                    row.description,
                    row.archetype,
                    f"{row.realized_pnl:.5f}",
                    row.closed_trades,
                    f"{row.win_rate_pct:.5f}",
                    f"{row.profit_factor:.5f}",
                    f"{row.max_drawdown_pct:.5f}",
                    f"{row.total_costs:.5f}",
                    f"{row.train_pnl:.5f}",
                    f"{row.validation_pnl:.5f}",
                    f"{row.validation_profit_factor:.5f}",
                    row.validation_closed_trades,
                    f"{row.test_pnl:.5f}",
                    f"{row.test_profit_factor:.5f}",
                    row.test_closed_trades,
                    row.trade_log_path,
                    row.trade_analysis_path,
                ]
            )

    ranked = sorted(rows, key=lambda item: (item.realized_pnl, item.profit_factor, item.closed_trades), reverse=True)
    lines = [
        f"Symbol research: {symbol}",
        f"Broker symbol: {broker_symbol}",
        f"Data source: {data_source}",
        "",
        "Ranked candidates",
    ]
    for row in ranked:
        lines.append(
            f"{row.name} [{row.archetype}]: pnl={row.realized_pnl:.2f} closed={row.closed_trades} "
            f"pf={row.profit_factor:.2f} win_rate={row.win_rate_pct:.2f}% dd={row.max_drawdown_pct:.2f}%"
        )
        lines.append(
            f"  splits: train_pnl={row.train_pnl:.2f} val_pnl={row.validation_pnl:.2f} "
            f"val_pf={row.validation_profit_factor:.2f} val_closed={row.validation_closed_trades} "
            f"test_pnl={row.test_pnl:.2f} test_pf={row.test_profit_factor:.2f} test_closed={row.test_closed_trades}"
        )
        lines.append(f"  trades: {row.trade_log_path}")
        lines.append(f"  analysis: {row.trade_analysis_path}")
    winners = [
        row
        for row in ranked
        if row.validation_closed_trades >= 3
        and row.test_closed_trades >= 2
        and row.validation_pnl > 0
        and row.test_pnl > 0
        and row.validation_profit_factor >= 1.0
        and row.test_profit_factor >= 1.0
    ]
    lines.extend(["", "Recommended active agents"])
    if winners:
        for row in winners[:3]:
            lines.append(f"- {row.name} ({row.description})")
    else:
        lines.append("No candidate met the positive-PnL and PF>=1.0 threshold.")
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, txt_path


def run_symbol_research(data_symbol: str, broker_symbol: str | None = None) -> list[str]:
    config = SystemConfig()
    resolved = resolve_symbol_request(data_symbol, broker_symbol)
    config.polygon.history_days = _symbol_research_history_days(config, resolved.profile_symbol)
    _configure_symbol_execution(config, resolved.profile_symbol)
    feature_variants, data_source, effective_mode = _build_symbol_feature_variants(
        config,
        resolved.profile_symbol,
        resolved.data_symbol,
    )
    default_features = _default_variant_features(feature_variants)
    if not default_features:
        raise RuntimeError(f"No usable feature variants were generated for {resolved.profile_symbol}.")
    singles = _candidate_specs(config, resolved.profile_symbol)
    symbol_slug = _symbol_slug(resolved.profile_symbol)
    results: list[CandidateResult] = []
    for variant_label, features in feature_variants.items():
        if not features:
            continue
        results.extend(
            _run_candidate_with_splits(
                config,
                features,
                _with_variant_name(spec, variant_label),
                "single",
                f"{symbol_slug}_{spec.name}_{variant_label}_symbol_candidate",
            )
            for spec in singles
        )
    sweep_specs = _parameter_sweep_specs(config, resolved.profile_symbol)
    if sweep_specs:
        for variant_label, features in feature_variants.items():
            if not features:
                continue
            results.extend(
                _run_candidate_with_splits(
                    config,
                    features,
                    _with_variant_name(spec, variant_label),
                    "parameter_sweep",
                    f"{symbol_slug}_{spec.name}_{variant_label}_symbol_candidate",
                )
                for spec in sweep_specs
            )
    improvement_specs = _auto_improvement_specs(config, resolved.profile_symbol, results)
    if improvement_specs:
        results.extend(
            _run_candidate_with_splits(
                config,
                default_features,
                spec,
                "auto_improved",
                f"{symbol_slug}_{spec.name}_symbol_candidate",
            )
            for spec in improvement_specs
        )
    second_pass_specs = _second_pass_specs(config, resolved.profile_symbol, results)
    if second_pass_specs:
        results.extend(
            _run_candidate_with_splits(
                config,
                default_features,
                spec,
                "auto_second_pass",
                f"{symbol_slug}_{spec.name}_symbol_candidate",
            )
            for spec in second_pass_specs
        )
    combos = _combined_specs(config, singles + sweep_specs + improvement_specs + second_pass_specs, results)
    results.extend(
        _run_candidate_with_splits(
            config,
            default_features,
            spec,
            "combined",
            f"{symbol_slug}_{spec.name}_symbol_candidate",
        )
        for spec in combos
    )
    csv_path, txt_path = _export_results(resolved.profile_symbol, resolved.broker_symbol, data_source, results)
    ranked = sorted(
        results,
        key=lambda item: (
            item.validation_closed_trades >= 3
            and item.test_closed_trades >= 2
            and item.validation_pnl > 0
            and item.test_pnl > 0
            and item.validation_profit_factor >= 1.0
            and item.test_profit_factor >= 1.0,
            item.test_pnl,
            item.validation_pnl,
            item.test_profit_factor,
            item.test_closed_trades,
        ),
        reverse=True,
    )
    viable_ranked = [
        row
        for row in ranked
        if row.validation_closed_trades >= 3
        and row.test_closed_trades >= 2
        and row.validation_pnl > 0
        and row.test_pnl > 0
        and row.validation_profit_factor >= 1.0
        and row.test_profit_factor >= 1.0
    ]
    best = viable_ranked[0] if viable_ranked else None
    recommended = [row.name for row in viable_ranked[:3]]
    profile_name = f"symbol::{_symbol_slug(resolved.profile_symbol)}"

    selected_execution_candidates = select_execution_candidates(
        [
            {
                "candidate_name": row.name,
                "code_path": row.code_path,
                "realized_pnl": row.realized_pnl,
                "profit_factor": row.profit_factor,
                "closed_trades": row.closed_trades,
                "validation_pnl": row.validation_pnl,
                "validation_profit_factor": row.validation_profit_factor,
                "validation_closed_trades": row.validation_closed_trades,
                "test_pnl": row.test_pnl,
                "test_profit_factor": row.test_profit_factor,
                "test_closed_trades": row.test_closed_trades,
                "recommended": row.name in recommended,
            }
            for row in results
        ],
        max_candidates=2,
    )
    execution_set_id: int | None = None
    execution_validation_summary = "not_run"
    if selected_execution_candidates:
        execution_validation_result, execution_validation_source, execution_variant = _evaluate_execution_candidate_set(
            config,
            resolved.profile_symbol,
            resolved.data_symbol,
            selected_execution_candidates,
        )
        execution_validation_summary = (
            f"variant={execution_variant} data_source={execution_validation_source} "
            f"pnl={execution_validation_result.realized_pnl:.2f} "
            f"pf={execution_validation_result.profit_factor:.2f} "
            f"closed={len(execution_validation_result.closed_trades)}"
        )
        if (
            execution_validation_result.realized_pnl <= 0.0
            or execution_validation_result.profit_factor < 1.0
            or len(execution_validation_result.closed_trades) < 2
        ):
            selected_execution_candidates = []
            recommended = []
            execution_validation_summary += " -> rejected"
        else:
            recommended = [str(row["candidate_name"]) for row in selected_execution_candidates]
            execution_validation_summary += " -> accepted"
    store = ExperimentStore(config.ai.experiment_database_path)
    run_id = store.record_symbol_research_run(
        profile_name=profile_name,
        data_symbol=resolved.data_symbol,
        broker_symbol=resolved.broker_symbol,
        data_source=data_source,
        candidates=results,
        recommended_names=recommended,
    )
    if selected_execution_candidates:
        execution_set_id = store.record_symbol_execution_set(
            profile_name=profile_name,
            symbol_research_run_id=run_id,
            selected_candidates=selected_execution_candidates,
        )
    descriptors = [
        AgentDescriptor(
            profile_name=profile_name,
            agent_name=row.name,
            lifecycle_scope="active",
            class_name=row.name,
            code_path=row.code_path,
            description=row.description,
            is_active=row.name in recommended,
            variant_label=row.variant_label,
            timeframe_label=row.timeframe_label,
            session_label=row.session_label,
        )
        for row in results
    ]
    store.promote_symbol_research_candidates(
        profile_name=profile_name,
        data_symbol=resolved.data_symbol,
        broker_symbol=resolved.broker_symbol,
        descriptors=descriptors,
        candidates=results,
        recommended_names=recommended,
        symbol_research_run_id=run_id,
    )

    lines = [
        f"Requested symbol: {resolved.requested_symbol}",
        f"Symbol: {resolved.profile_symbol}",
        f"Data symbol: {resolved.data_symbol}",
        f"Broker symbol: {resolved.broker_symbol}",
        f"Catalog profile: {profile_name}",
        f"Data source: {data_source}",
        f"Candidates tested: {len(results)}",
        f"Research CSV: {csv_path}",
        f"Research report: {txt_path}",
    ]
    if best is not None:
        lines.extend(
            [
                f"Best candidate: {best.name}",
                f"Best PnL: {best.realized_pnl:.2f}",
                f"Best profit factor: {best.profit_factor:.2f}",
                f"Best closed trades: {best.closed_trades}",
                f"Validation: pnl={best.validation_pnl:.2f} pf={best.validation_profit_factor:.2f} closed={best.validation_closed_trades}",
                f"Test: pnl={best.test_pnl:.2f} pf={best.test_profit_factor:.2f} closed={best.test_closed_trades}",
            ]
        )
    else:
        lines.append("Best candidate: none")
        lines.append(
            "No viable candidate met the minimum viability rules "
            "(validation_closed_trades >= 3, test_closed_trades >= 2, validation/test pnl > 0, validation/test PF >= 1.0)."
        )
    lines.append("Recommended active agents: " + (", ".join(recommended) if recommended else "none"))
    lines.append(
        "Execution set: "
        + (
            ", ".join(str(row["candidate_name"]) for row in selected_execution_candidates)
            if selected_execution_candidates
            else "none"
        )
    )
    lines.append(f"Execution set id: {execution_set_id if execution_set_id is not None else 'none'}")
    lines.append(f"Execution validation: {execution_validation_summary}")
    lines.append(f"Research history days: {config.polygon.history_days}")
    lines.append(f"Research mode: {effective_mode}")
    if config.symbol_research.mode == "auto":
        lines.append(
            "Research mode selection: "
            + (
                "full because all required timeframe caches were found."
                if effective_mode == "full"
                else "seed because one or more full-research timeframe caches were missing."
            )
        )
    lines.append(
        "Split ratio: train 60% / validation 20% / test 20%"
    )
    return lines
