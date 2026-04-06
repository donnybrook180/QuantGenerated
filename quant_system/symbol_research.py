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
from quant_system.agents.crypto import (
    CryptoBreakoutReclaimAgent,
    CryptoShortBreakdownAgent,
    CryptoShortReversionAgent,
    CryptoTrendPullbackAgent,
    CryptoVolatilityExpansionAgent,
)
from quant_system.agents.forex import (
    ForexBreakoutMomentumAgent,
    ForexRangeReversionAgent,
    ForexShortBreakdownMomentumAgent,
    ForexShortTrendContinuationAgent,
    ForexTrendContinuationAgent,
)
from quant_system.agents.ger40 import GER40FailedBreakoutShortAgent, GER40RangeRejectShortAgent
from quant_system.agents.stocks import (
    EventAwareRiskSentinelAgent,
    StockGapFadeAgent,
    StockGapAndGoAgent,
    StockNewsMomentumAgent,
    StockPostEarningsDriftAgent,
    StockPowerHourContinuationAgent,
    StockTrendBreakoutAgent,
)
from quant_system.agents.strategies import (
    OpeningRangeBreakoutAgent,
    OpeningRangeShortBreakdownAgent,
    VolatilityBreakoutAgent,
    VolatilityShortBreakdownAgent,
)
from quant_system.agents.us500 import (
    US500MomentumImpulseAgent,
    US500OpeningDriveShortReclaimAgent,
    US500ShortTrendRejectionAgent,
    US500ShortVWAPRejectAgent,
)
from quant_system.agents.trend import MeanReversionAgent, MomentumConfirmationAgent, RiskSentinelAgent, TrendAgent
from quant_system.agents.xauusd import XAUUSDShortBreakdownAgent, XAUUSDVolatilityBreakoutAgent
from quant_system.catalog_runtime import build_agents_from_catalog_paths
from quant_system.config import SystemConfig
from quant_system.costs import apply_ftmo_cost_profile
from quant_system.data.market_data import DuckDBMarketDataStore
from quant_system.execution.broker import SimulatedBroker
from quant_system.execution.engine import AgentCoordinator, EventDrivenEngine, ExecutionResult
from quant_system.integrations.polygon_data import PolygonDataClient, PolygonError
from quant_system.integrations.polygon_events import fetch_stock_event_flags
from quant_system.live.deploy import build_symbol_deployment, export_symbol_deployment
from quant_system.models import FeatureVector, MarketBar
from quant_system.monitoring.heartbeat import HeartbeatMonitor
from quant_system.plotting import plot_symbol_research
from quant_system.research.features import build_feature_library
from quant_system.risk.limits import RiskManager
from quant_system.symbols import (
    is_crypto_symbol as symbol_is_crypto,
    is_forex_symbol as symbol_is_forex,
    is_metal_symbol as symbol_is_metal,
    is_stock_symbol as symbol_is_stock,
    resolve_symbol_request,
)


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
    regime_filter_label: str = ""


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
    expectancy: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    payoff_ratio: float = 0.0
    avg_hold_bars: float = 0.0
    dominant_exit: str = ""
    dominant_exit_share_pct: float = 0.0
    execution_overrides: dict[str, float | int] | None = None
    walk_forward_windows: int = 0
    walk_forward_pass_rate_pct: float = 0.0
    walk_forward_avg_validation_pnl: float = 0.0
    walk_forward_avg_test_pnl: float = 0.0
    walk_forward_avg_validation_pf: float = 0.0
    walk_forward_avg_test_pf: float = 0.0
    component_count: int = 1
    combo_outperformance_score: float = 0.0
    combo_trade_overlap_pct: float = 0.0
    best_regime: str = ""
    best_regime_pnl: float = 0.0
    worst_regime: str = ""
    worst_regime_pnl: float = 0.0
    dominant_regime_share_pct: float = 0.0
    regime_filter_label: str = ""
    sparse_strategy: bool = False
    walk_forward_soft_pass_rate_pct: float = 0.0


def _symbol_slug(symbol: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in symbol).strip("_")


def _is_crypto_symbol(symbol: str) -> bool:
    return symbol_is_crypto(symbol)


def _is_metal_symbol(symbol: str) -> bool:
    return symbol_is_metal(symbol)


def _is_forex_symbol(symbol: str) -> bool:
    return symbol_is_forex(symbol)


def _is_stock_symbol(symbol: str) -> bool:
    return symbol_is_stock(symbol)


def _symbol_research_history_days(config: SystemConfig, symbol: str) -> int:
    base_history = max(config.symbol_research.history_days, config.polygon.history_days)
    if _is_crypto_symbol(symbol):
        return max(base_history, 365)
    if symbol.upper() == "US500":
        return max(base_history, 365)
    if _is_stock_symbol(symbol):
        return max(base_history, 365)
    if _is_metal_symbol(symbol) or _is_forex_symbol(symbol):
        return max(base_history, 180)
    return max(base_history, 180)


def _research_thresholds(symbol: str) -> dict[str, float | int]:
    if symbol.upper() == "US500":
        return {
            "validation_closed_trades": 2,
            "test_closed_trades": 1,
            "min_profit_factor": 1.0,
            "walk_forward_min_windows": 1,
            "walk_forward_min_pass_rate_pct": 25.0,
            "sparse_max_closed_trades": 18,
            "sparse_min_payoff_ratio": 1.75,
            "sparse_combined_closed_trades": 2,
            "sparse_walk_forward_min_pass_rate_pct": 20.0,
        }
    if _is_crypto_symbol(symbol):
        return {
            "validation_closed_trades": 2,
            "test_closed_trades": 1,
            "min_profit_factor": 1.0,
            "walk_forward_min_windows": 1,
            "walk_forward_min_pass_rate_pct": 40.0,
            "sparse_max_closed_trades": 20,
            "sparse_min_payoff_ratio": 1.75,
            "sparse_combined_closed_trades": 2,
            "sparse_walk_forward_min_pass_rate_pct": 25.0,
        }
    if _is_stock_symbol(symbol):
        return {
            "validation_closed_trades": 1,
            "test_closed_trades": 1,
            "min_profit_factor": 1.0,
            "walk_forward_min_windows": 1,
            "walk_forward_min_pass_rate_pct": 20.0,
            "sparse_max_closed_trades": 24,
            "sparse_min_payoff_ratio": 1.75,
            "sparse_combined_closed_trades": 2,
            "sparse_walk_forward_min_pass_rate_pct": 15.0,
        }
    return {
        "validation_closed_trades": 3,
        "test_closed_trades": 2,
        "min_profit_factor": 1.0,
        "walk_forward_min_windows": 1,
        "walk_forward_min_pass_rate_pct": 50.0,
        "sparse_max_closed_trades": 18,
        "sparse_min_payoff_ratio": 1.75,
        "sparse_combined_closed_trades": 2,
        "sparse_walk_forward_min_pass_rate_pct": 25.0,
    }


def _is_sparse_candidate(row: CandidateResult | dict[str, object], symbol: str) -> bool:
    thresholds = _research_thresholds(symbol)
    closed_trades = int(row.closed_trades if isinstance(row, CandidateResult) else row.get("closed_trades", 0))
    payoff_ratio = float(row.payoff_ratio if isinstance(row, CandidateResult) else row.get("payoff_ratio", 0.0))
    profit_factor = float(row.profit_factor if isinstance(row, CandidateResult) else row.get("profit_factor", 0.0))
    return (
        closed_trades > 0
        and closed_trades <= int(thresholds["sparse_max_closed_trades"])
        and payoff_ratio >= float(thresholds["sparse_min_payoff_ratio"])
        and profit_factor >= float(thresholds["min_profit_factor"])
    )


def _aggregate_profit_factor(*pnl_groups: list[float]) -> float:
    pnls = [pnl for group in pnl_groups for pnl in group]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)


def _meets_viability(row: CandidateResult | dict[str, object], symbol: str) -> bool:
    thresholds = _research_thresholds(symbol)
    realized_pnl = float(row.realized_pnl if isinstance(row, CandidateResult) else row.get("realized_pnl", 0.0))
    profit_factor = float(row.profit_factor if isinstance(row, CandidateResult) else row.get("profit_factor", 0.0))
    validation_closed_trades = int(row.validation_closed_trades if isinstance(row, CandidateResult) else row.get("validation_closed_trades", 0))
    test_closed_trades = int(row.test_closed_trades if isinstance(row, CandidateResult) else row.get("test_closed_trades", 0))
    validation_pnl = float(row.validation_pnl if isinstance(row, CandidateResult) else row.get("validation_pnl", 0.0))
    test_pnl = float(row.test_pnl if isinstance(row, CandidateResult) else row.get("test_pnl", 0.0))
    validation_profit_factor = float(row.validation_profit_factor if isinstance(row, CandidateResult) else row.get("validation_profit_factor", 0.0))
    test_profit_factor = float(row.test_profit_factor if isinstance(row, CandidateResult) else row.get("test_profit_factor", 0.0))
    walk_forward_windows = int(row.walk_forward_windows if isinstance(row, CandidateResult) else row.get("walk_forward_windows", 0))
    walk_forward_pass_rate_pct = float(row.walk_forward_pass_rate_pct if isinstance(row, CandidateResult) else row.get("walk_forward_pass_rate_pct", 0.0))
    walk_forward_avg_validation_pnl = float(
        row.walk_forward_avg_validation_pnl if isinstance(row, CandidateResult) else row.get("walk_forward_avg_validation_pnl", 0.0)
    )
    walk_forward_avg_test_pnl = float(
        row.walk_forward_avg_test_pnl if isinstance(row, CandidateResult) else row.get("walk_forward_avg_test_pnl", 0.0)
    )
    component_count = int(row.component_count if isinstance(row, CandidateResult) else row.get("component_count", 1))
    combo_outperformance_score = float(
        row.combo_outperformance_score if isinstance(row, CandidateResult) else row.get("combo_outperformance_score", 0.0)
    )
    combo_trade_overlap_pct = float(
        row.combo_trade_overlap_pct if isinstance(row, CandidateResult) else row.get("combo_trade_overlap_pct", 0.0)
    )
    sparse_strategy = _is_sparse_candidate(row, symbol)
    sparse_combined_closed_trades = validation_closed_trades + test_closed_trades
    sparse_pass_rate_threshold = (
        float(thresholds["sparse_walk_forward_min_pass_rate_pct"]) if sparse_strategy else float(thresholds["walk_forward_min_pass_rate_pct"])
    )
    sparse_window_pass_rate = float(
        row.walk_forward_soft_pass_rate_pct if isinstance(row, CandidateResult) else row.get("walk_forward_soft_pass_rate_pct", 0.0)
    )
    split_trade_requirement_met = (
        sparse_combined_closed_trades >= int(thresholds["sparse_combined_closed_trades"])
        if sparse_strategy
        else validation_closed_trades >= int(thresholds["validation_closed_trades"]) and test_closed_trades >= int(thresholds["test_closed_trades"])
    )
    split_pnl_requirement_met = (
        (validation_pnl + test_pnl) > 0.0 if sparse_strategy else validation_pnl > 0.0 and test_pnl > 0.0
    )
    split_pf_requirement_met = (
        max(validation_profit_factor, test_profit_factor) >= float(thresholds["min_profit_factor"])
        if sparse_strategy
        else validation_profit_factor >= float(thresholds["min_profit_factor"]) and test_profit_factor >= float(thresholds["min_profit_factor"])
    )
    walk_forward_pass_requirement_met = (
        sparse_window_pass_rate >= sparse_pass_rate_threshold
        if sparse_strategy
        else walk_forward_pass_rate_pct >= float(thresholds["walk_forward_min_pass_rate_pct"])
    )
    return (
        realized_pnl > 0.0
        and profit_factor >= float(thresholds["min_profit_factor"])
        and split_trade_requirement_met
        and split_pnl_requirement_met
        and split_pf_requirement_met
        and walk_forward_windows >= int(thresholds["walk_forward_min_windows"])
        and walk_forward_pass_requirement_met
        and walk_forward_avg_validation_pnl > 0.0
        and walk_forward_avg_test_pnl > 0.0
        and (
            component_count <= 1
            or (combo_outperformance_score >= 0.0 and combo_trade_overlap_pct <= 80.0)
        )
    )


def _build_engine(config: SystemConfig, agents: list[Agent]) -> EventDrivenEngine:
    broker = SimulatedBroker(
        initial_cash=config.execution.initial_cash,
        fee_bps=config.execution.fee_bps,
        commission_per_unit=config.execution.commission_per_unit,
        slippage_bps=config.execution.slippage_bps,
        spread_points=config.execution.spread_points,
        contract_size=config.execution.contract_size,
        commission_mode=config.execution.commission_mode,
        commission_per_lot=config.execution.commission_per_lot,
        commission_notional_pct=config.execution.commission_notional_pct,
        overnight_cost_per_lot_day=config.execution.overnight_cost_per_lot_day,
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
    elif _is_stock_symbol(symbol):
        config.execution.min_bars_between_trades = 10
        config.execution.max_holding_bars = 18
        config.execution.stop_loss_atr_multiple = 1.25
        config.execution.take_profit_atr_multiple = 2.5
        config.execution.break_even_atr_multiple = 0.8
        config.execution.trailing_stop_atr_multiple = 0.95
        config.execution.stale_breakout_bars = 5
        config.execution.stale_breakout_atr_fraction = 0.12
        config.execution.structure_exit_bars = 3
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
    apply_ftmo_cost_profile(config, symbol)


def _load_symbol_features(config: SystemConfig, data_symbol: str) -> tuple[list[FeatureVector], str]:
    return _load_symbol_features_variant(config, data_symbol, config.polygon.multiplier, config.polygon.timespan)


def _research_variant_plan(profile_symbol: str, mode: str) -> tuple[list[tuple[str, int, str]], tuple[str, ...], bool]:
    if profile_symbol.upper() == "TSLA":
        return [("15m", 15, "minute")], ("midday",), True
    if profile_symbol.upper() == "GBPUSD":
        return [("15m", 15, "minute")], ("europe",), True
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
    if _is_stock_symbol(profile_symbol):
        if mode == "seed":
            return [("5m", 5, "minute")], ("us", "open"), True
        return [("5m", 5, "minute"), ("15m", 15, "minute")], ("us", "open", "power", "midday"), True
    return [("5m", 5, "minute")], ("all",), False


def _variant_timeframe_key(data_symbol: str, multiplier: int, timespan: str) -> str:
    return f"symbol_research_{_symbol_slug(data_symbol)}_{multiplier}_{timespan}"


def _detect_research_mode(config: SystemConfig, profile_symbol: str, data_symbol: str) -> str:
    requested_mode = config.symbol_research.mode
    if requested_mode in {"seed", "full"}:
        return requested_mode
    symbol_specific = _is_crypto_symbol(profile_symbol) or _is_metal_symbol(profile_symbol) or _is_forex_symbol(profile_symbol) or _is_stock_symbol(profile_symbol)
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
            return _build_features_with_events(config, data_symbol, cached), "duckdb_cache"
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
        return _build_features_with_events(config, data_symbol, persisted), "polygon"
    except PolygonError:
        cached = store.load_bars(data_symbol, scoped_timeframe, 50_000)
        if cached:
            return _build_features_with_events(config, data_symbol, cached), "duckdb_cache"
        raise


def _build_features_with_events(config: SystemConfig, data_symbol: str, bars: list[MarketBar]) -> list[FeatureVector]:
    if not bars:
        return []
    if not _is_stock_symbol(data_symbol):
        return build_feature_library(bars)
    try:
        event_flags = fetch_stock_event_flags(
            config.polygon.api_key,
            data_symbol,
            start_day=bars[0].timestamp.date(),
            end_day=bars[-1].timestamp.date(),
            max_retries=config.polygon.max_retries,
            backoff_seconds=config.polygon.retry_backoff_seconds,
        )
    except RuntimeError as exc:
        LOGGER.warning("Stock event enrichment failed for %s; continuing without event flags: %s", data_symbol, exc)
        return build_feature_library(bars)
    return build_feature_library(bars, event_flags)


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
    elif session_name == "open":
        return [
            feature for feature in features
            if feature.values.get("in_regular_session", 0.0) >= 1.0 and 0 <= feature.values.get("minutes_from_open", -1.0) < 90
        ]
    elif session_name == "power":
        return [feature for feature in features if int(feature.values.get("hour_of_day", feature.timestamp.hour)) in {18, 19}]
    elif session_name == "midday":
        return [feature for feature in features if int(feature.values.get("hour_of_day", feature.timestamp.hour)) in {15, 16, 17}]
    else:
        return features

    return [feature for feature in features if int(feature.values.get("hour_of_day", feature.timestamp.hour)) in allowed_hours]


def _filter_features_by_regime(features: list[FeatureVector], regime_label: str) -> list[FeatureVector]:
    if not regime_label:
        return features
    if regime_label.startswith("exclude:"):
        excluded = regime_label.removeprefix("exclude:")
        if excluded.startswith("trend_") and excluded.count("_") == 1:
            return [feature for feature in features if not _feature_regime_label(feature).startswith(excluded + "_")]
        if excluded.startswith("vol_") and excluded.count("_") == 1:
            return [feature for feature in features if not _feature_regime_label(feature).endswith("_" + excluded)]
        return [feature for feature in features if _feature_regime_label(feature) != excluded]
    if regime_label.startswith("trend_") and regime_label.count("_") == 1:
        return [feature for feature in features if _feature_regime_label(feature).startswith(regime_label + "_")]
    if regime_label.startswith("vol_") and regime_label.count("_") == 1:
        return [feature for feature in features if _feature_regime_label(feature).endswith("_" + regime_label)]
    return [feature for feature in features if _feature_regime_label(feature) == regime_label]


def _build_symbol_feature_variants(
    config: SystemConfig,
    profile_symbol: str,
    data_symbol: str,
) -> tuple[dict[str, list[FeatureVector]], str, str]:
    mode = _detect_research_mode(config, profile_symbol, data_symbol)
    if not (_is_crypto_symbol(profile_symbol) or _is_metal_symbol(profile_symbol) or _is_forex_symbol(profile_symbol) or _is_stock_symbol(profile_symbol)):
        features, data_source = _load_symbol_features(config, data_symbol)
        return {"default": features}, data_source, mode
    if _is_stock_symbol(profile_symbol):
        variants: dict[str, list[FeatureVector]] = {}
        data_sources: list[str] = []
        timeframe_specs, session_names, weekday_only = _research_variant_plan(profile_symbol, mode)
        for timeframe_label, multiplier, timespan in timeframe_specs:
            timeframe_features, data_source = _load_symbol_features_variant(config, data_symbol, multiplier, timespan)
            if weekday_only:
                timeframe_features = _filter_weekday_features(timeframe_features)
            data_sources.append(data_source)
            for session_name in session_names:
                filtered = [
                    feature
                    for feature in _filter_features_by_session(timeframe_features, session_name)
                    if feature.values.get("event_blackout", 0.0) < 1.0
                ]
                if len(filtered) < 50:
                    continue
                variants[f"{timeframe_label}_{session_name}"] = filtered
        resolved_source = "polygon" if "polygon" in data_sources else (data_sources[0] if data_sources else "unknown")
        return variants or {"default": []}, resolved_source, mode

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
    regime_filter_label: str = "",
) -> tuple[list[FeatureVector], str]:
    if not variant_label or variant_label == "default":
        features, data_source = _load_symbol_features(config, data_symbol)
        return _filter_features_by_regime(features, regime_filter_label), data_source

    timeframe_label, _, session_label = variant_label.partition("_")
    if timeframe_label.endswith("m") and timeframe_label[:-1].isdigit():
        multiplier = int(timeframe_label[:-1])
        timespan = "minute"
    else:
        features, data_source = _load_symbol_features(config, data_symbol)
        return _filter_features_by_regime(features, regime_filter_label), data_source

    features, data_source = _load_symbol_features_variant(config, data_symbol, multiplier, timespan)
    if _is_crypto_symbol(profile_symbol) or _is_metal_symbol(profile_symbol) or _is_forex_symbol(profile_symbol) or _is_stock_symbol(profile_symbol):
        features = _filter_weekday_features(features)
    features = _filter_features_by_session(features, session_label or "all")
    if _is_stock_symbol(profile_symbol):
        features = [feature for feature in features if feature.values.get("event_blackout", 0.0) < 1.0]
    return _filter_features_by_regime(features, regime_filter_label), data_source


def _evaluate_execution_candidate_set(
    config: SystemConfig,
    profile_symbol: str,
    data_symbol: str,
    selected_candidates: list[dict[str, object]],
) -> tuple[ExecutionResult, str, str]:
    return _run_candidate_bundle(config, profile_symbol, data_symbol, selected_candidates)


def _aggregate_execution_results(initial_cash: float, results: list[ExecutionResult]) -> ExecutionResult:
    combined_closed_trade_pnls: list[float] = []
    combined_closed_trades = []
    trades = 0
    realized_pnl = 0.0
    total_costs = 0.0
    locked = False
    max_drawdown = 0.0
    for result in results:
        combined_closed_trade_pnls.extend(result.closed_trade_pnls)
        combined_closed_trades.extend(result.closed_trades)
        trades += result.trades
        realized_pnl += result.realized_pnl
        total_costs += result.total_costs
        locked = locked or result.locked
        max_drawdown = max(max_drawdown, result.max_drawdown)
    wins = [pnl for pnl in combined_closed_trade_pnls if pnl > 0]
    losses = [pnl for pnl in combined_closed_trade_pnls if pnl < 0]
    win_rate_pct = (len(wins) / len(combined_closed_trade_pnls) * 100.0) if combined_closed_trade_pnls else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    return ExecutionResult(
        ending_equity=initial_cash + realized_pnl,
        realized_pnl=realized_pnl,
        trades=trades,
        locked=locked,
        max_drawdown=max_drawdown,
        win_rate_pct=win_rate_pct,
        profit_factor=profit_factor,
        total_costs=total_costs,
        closed_trade_pnls=combined_closed_trade_pnls,
        closed_trades=combined_closed_trades,
    )


def _run_candidate_bundle(
    config: SystemConfig,
    profile_symbol: str,
    data_symbol: str,
    candidates: list[dict[str, object]],
) -> tuple[ExecutionResult, str, str]:
    results: list[ExecutionResult] = []
    data_sources: list[str] = []
    variant_labels: list[str] = []
    for row in candidates:
        candidate_config = _with_execution_overrides(config, row.get("execution_overrides"))
        variant_label = str(row.get("variant_label", "") or "")
        regime_filter_label = str(row.get("regime_filter_label", "") or "")
        features, data_source = load_execution_features_for_variant(
            candidate_config,
            profile_symbol,
            data_symbol,
            variant_label,
            regime_filter_label,
        )
        agents = build_agents_from_catalog_paths([str(row["code_path"])], candidate_config)
        engine = _build_engine(candidate_config, agents)
        results.append(asyncio.run(engine.run(features, sleep_seconds=0.0)))
        data_sources.append(data_source)
        label = variant_label or "default"
        if regime_filter_label:
            label = f"{label}|{regime_filter_label}"
        variant_labels.append(f"{row['candidate_name']}@{label}")
    data_source_label = ",".join(sorted(set(data_sources))) if data_sources else "unknown"
    variant_label = ", ".join(variant_labels) if variant_labels else "default"
    return _aggregate_execution_results(config.execution.initial_cash, results), data_source_label, variant_label


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
            CandidateSpec(
                name="crypto_short_breakdown",
                description="Crypto short breakdown continuation",
                agents=[CryptoShortBreakdownAgent(), risk],
                code_path="quant_system.agents.crypto.CryptoShortBreakdownAgent",
            ),
            CandidateSpec(
                name="crypto_short_reversion",
                description="Crypto short mean reversion in downtrend",
                agents=[CryptoShortReversionAgent(), risk],
                code_path="quant_system.agents.crypto.CryptoShortReversionAgent",
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
        specs.append(
            CandidateSpec(
                name="xauusd_short_breakdown",
                description="XAUUSD short breakdown continuation",
                agents=[XAUUSDShortBreakdownAgent(lookback=max(6, config.agents.mean_reversion_window)), risk],
                code_path="quant_system.agents.xauusd.XAUUSDShortBreakdownAgent",
            )
        )
        return specs
    if upper.endswith("USD") or upper.endswith("JPY") or upper.startswith("EUR") or upper.startswith("GBP") or upper.startswith("AUD"):
        if upper == "GBPUSD":
            return [
                CandidateSpec(
                    name="forex_breakout_momentum",
                    description="GBPUSD-focused Europe-session breakout momentum",
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
                ),
            ]
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
            CandidateSpec(
                name="forex_short_trend_continuation",
                description="Forex short trend continuation",
                agents=[ForexShortTrendContinuationAgent(), risk],
                code_path="quant_system.agents.forex.ForexShortTrendContinuationAgent",
            ),
            CandidateSpec(
                name="forex_short_breakdown_momentum",
                description="Forex short breakdown momentum",
                agents=[ForexShortBreakdownMomentumAgent(), risk],
                code_path="quant_system.agents.forex.ForexShortBreakdownMomentumAgent",
            ),
        ]
    if _is_stock_symbol(data_symbol):
        stock_risk = EventAwareRiskSentinelAgent(allow_high_impact_day=False)
        if upper == "TSLA":
            return [
                CandidateSpec(
                    name="mean_reversion",
                    description="TSLA-focused midday mean reversion",
                    agents=[MeanReversionAgent(max(config.agents.mean_reversion_window - 2, 4), config.agents.mean_reversion_threshold * 0.85), stock_risk, risk],
                    code_path="quant_system.agents.trend.MeanReversionAgent",
                ),
            ]
        return [
            CandidateSpec(
                name="stock_trend_breakout",
                description="Stock trend breakout outside event blackout windows",
                agents=[StockTrendBreakoutAgent(), stock_risk, risk],
                code_path="quant_system.agents.stocks.StockTrendBreakoutAgent",
            ),
            CandidateSpec(
                name="stock_news_momentum",
                description="Stock post-news momentum on high-impact event days",
                agents=[StockNewsMomentumAgent(), EventAwareRiskSentinelAgent(allow_high_impact_day=True), risk],
                code_path="quant_system.agents.stocks.StockNewsMomentumAgent",
            ),
            CandidateSpec(
                name="stock_post_earnings_drift",
                description="Stock post-earnings drift continuation after the open",
                agents=[StockPostEarningsDriftAgent(), EventAwareRiskSentinelAgent(allow_high_impact_day=True), risk],
                code_path="quant_system.agents.stocks.StockPostEarningsDriftAgent",
            ),
            CandidateSpec(
                name="stock_gap_fade",
                description="Stock gap fade after overextended opening move",
                agents=[StockGapFadeAgent(), stock_risk, risk],
                code_path="quant_system.agents.stocks.StockGapFadeAgent",
            ),
            CandidateSpec(
                name="stock_gap_and_go",
                description="Stock gap-and-go continuation after the open",
                agents=[StockGapAndGoAgent(), stock_risk, risk],
                code_path="quant_system.agents.stocks.StockGapAndGoAgent",
            ),
            CandidateSpec(
                name="stock_power_hour_continuation",
                description="Stock power-hour continuation into the close",
                agents=[StockPowerHourContinuationAgent(), stock_risk, risk],
                code_path="quant_system.agents.stocks.StockPowerHourContinuationAgent",
            ),
            CandidateSpec(
                name="momentum",
                description="Momentum confirmation",
                agents=[MomentumConfirmationAgent(config.agents.mean_reversion_threshold * 0.85), stock_risk, risk],
                code_path="quant_system.agents.trend.MomentumConfirmationAgent",
            ),
            CandidateSpec(
                name="mean_reversion",
                description="Intraday mean reversion away from event windows",
                agents=[MeanReversionAgent(config.agents.mean_reversion_window, config.agents.mean_reversion_threshold), stock_risk, risk],
                code_path="quant_system.agents.trend.MeanReversionAgent",
            ),
            CandidateSpec(
                name="volatility_breakout",
                description="Generic volatility breakout outside event blackout windows",
                agents=[VolatilityBreakoutAgent(lookback=max(8, config.agents.mean_reversion_window)), stock_risk, risk],
                code_path="quant_system.agents.strategies.VolatilityBreakoutAgent",
            ),
        ]
    specs.extend(
        [
            CandidateSpec(
                name="volatility_short_breakdown",
                description="Generic short volatility breakdown",
                agents=[VolatilityShortBreakdownAgent(lookback=max(8, config.agents.mean_reversion_window)), risk],
                code_path="quant_system.agents.strategies.VolatilityShortBreakdownAgent",
            ),
            CandidateSpec(
                name="opening_range_short_breakdown",
                description="Opening range short breakdown",
                agents=[OpeningRangeShortBreakdownAgent(), risk],
                code_path="quant_system.agents.strategies.OpeningRangeShortBreakdownAgent",
            ),
        ]
    )
    return specs


def _score_result(name: str, description: str, archetype: str, code_path: str, result: ExecutionResult) -> CandidateResult:
    wins = [trade.pnl for trade in result.closed_trades if trade.pnl > 0]
    losses = [trade.pnl for trade in result.closed_trades if trade.pnl < 0]
    expectancy = mean(result.closed_trade_pnls) if result.closed_trade_pnls else 0.0
    avg_win = mean(wins) if wins else 0.0
    avg_loss = mean(losses) if losses else 0.0
    payoff_ratio = (avg_win / abs(avg_loss)) if avg_loss < 0 else (999.0 if avg_win > 0 else 0.0)
    avg_hold_bars = mean([trade.hold_bars for trade in result.closed_trades]) if result.closed_trades else 0.0
    exit_counts: dict[str, int] = {}
    for trade in result.closed_trades:
        exit_counts[trade.exit_reason] = exit_counts.get(trade.exit_reason, 0) + 1
    dominant_exit = max(exit_counts, key=exit_counts.get) if exit_counts else ""
    dominant_exit_share_pct = (
        (exit_counts[dominant_exit] / len(result.closed_trades) * 100.0) if dominant_exit and result.closed_trades else 0.0
    )
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
        expectancy=expectancy,
        avg_win=avg_win,
        avg_loss=avg_loss,
        payoff_ratio=payoff_ratio,
        avg_hold_bars=avg_hold_bars,
        dominant_exit=dominant_exit,
        dominant_exit_share_pct=dominant_exit_share_pct,
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
    scored.regime_filter_label = spec.regime_filter_label
    scored.execution_overrides = copy.deepcopy(spec.execution_overrides)
    _annotate_regime_metrics(scored, features, result.closed_trades)
    return scored


def _split_features(features: list[FeatureVector], symbol: str) -> tuple[list[FeatureVector], list[FeatureVector], list[FeatureVector]]:
    total = len(features)
    if total < 30:
        return features, [], []
    if _is_crypto_symbol(symbol):
        train_ratio = 0.5
        validation_ratio = 0.25
    elif _is_stock_symbol(symbol):
        train_ratio = 0.5
        validation_ratio = 0.25
    else:
        train_ratio = 0.6
        validation_ratio = 0.2
    train_end = max(int(total * train_ratio), 1)
    validation_end = max(int(total * (train_ratio + validation_ratio)), train_end + 1)
    train = features[:train_end]
    validation = features[train_end:validation_end]
    test = features[validation_end:]
    return train, validation, test


def _walk_forward_slices(features: list[FeatureVector], symbol: str) -> list[tuple[list[FeatureVector], list[FeatureVector], list[FeatureVector]]]:
    total = len(features)
    if total < 90:
        train, validation, test = _split_features(features, symbol)
        return [(train, validation, test)] if validation and test else []

    if _is_crypto_symbol(symbol):
        train_size = max(int(total * 0.45), 30)
        validation_size = max(int(total * 0.25), 10)
        test_size = max(int(total * 0.2), 10)
        step_size = max(int(total * 0.08), 10)
    elif _is_stock_symbol(symbol):
        train_size = max(int(total * 0.42), 30)
        validation_size = max(int(total * 0.22), 12)
        test_size = max(int(total * 0.22), 12)
        step_size = max(int(total * 0.06), 10)
    elif symbol.upper() == "US500":
        train_size = max(int(total * 0.45), 30)
        validation_size = max(int(total * 0.15), 10)
        test_size = max(int(total * 0.15), 10)
        step_size = max(int(total * 0.07), 10)
    else:
        train_size = max(int(total * 0.5), 30)
        validation_size = max(int(total * 0.2), 10)
        test_size = max(int(total * 0.2), 10)
        step_size = max(int(total * 0.1), 10)
    windows: list[tuple[list[FeatureVector], list[FeatureVector], list[FeatureVector]]] = []
    start = 0
    while True:
        train_end = start + train_size
        validation_end = train_end + validation_size
        test_end = validation_end + test_size
        if test_end > total:
            break
        windows.append(
            (
                features[start:train_end],
                features[train_end:validation_end],
                features[validation_end:test_end],
            )
        )
        start += step_size
    if not windows:
        train, validation, test = _split_features(features, symbol)
        if validation and test:
            windows.append((train, validation, test))
    return windows


def _run_candidate_with_splits(
    config: SystemConfig,
    features: list[FeatureVector],
    spec: CandidateSpec,
    archetype: str,
    artifact_prefix: str,
) -> CandidateResult:
    scored = _run_candidate(config, features, spec, archetype, artifact_prefix)
    symbol = features[0].symbol if features else ""
    thresholds = _research_thresholds(symbol)
    scored.sparse_strategy = _is_sparse_candidate(scored, symbol)

    def _eval_slice(slice_features: list[FeatureVector]) -> ExecutionResult | None:
        if len(slice_features) < 10:
            return None
        candidate_config = _with_execution_overrides(config, spec.execution_overrides)
        engine = _build_engine(candidate_config, copy.deepcopy(spec.agents))
        return asyncio.run(engine.run(slice_features, sleep_seconds=0.0))

    windows = _walk_forward_slices(features, symbol)
    validation_pnls: list[float] = []
    test_pnls: list[float] = []
    validation_pfs: list[float] = []
    test_pfs: list[float] = []
    pass_count = 0
    soft_pass_count = 0
    last_train_result: ExecutionResult | None = None
    last_validation_result: ExecutionResult | None = None
    last_test_result: ExecutionResult | None = None

    for train_features, validation_features, test_features in windows:
        train_result = _eval_slice(train_features)
        validation_result = _eval_slice(validation_features)
        test_result = _eval_slice(test_features)
        if validation_result is None or test_result is None:
            continue
        last_train_result = train_result
        last_validation_result = validation_result
        last_test_result = test_result
        validation_pnls.append(validation_result.realized_pnl)
        test_pnls.append(test_result.realized_pnl)
        validation_pfs.append(validation_result.profit_factor)
        test_pfs.append(test_result.profit_factor)
        combined_closed_trades = len(validation_result.closed_trades) + len(test_result.closed_trades)
        combined_pnl = validation_result.realized_pnl + test_result.realized_pnl
        combined_pf = _aggregate_profit_factor(validation_result.closed_trade_pnls, test_result.closed_trade_pnls)
        if (
            len(validation_result.closed_trades) >= int(thresholds["validation_closed_trades"])
            and len(test_result.closed_trades) >= int(thresholds["test_closed_trades"])
            and validation_result.realized_pnl > 0.0
            and test_result.realized_pnl > 0.0
            and validation_result.profit_factor >= float(thresholds["min_profit_factor"])
            and test_result.profit_factor >= float(thresholds["min_profit_factor"])
        ):
            pass_count += 1
        if (
            scored.sparse_strategy
            and combined_closed_trades >= int(thresholds["sparse_combined_closed_trades"])
            and combined_pnl > 0.0
            and combined_pf >= float(thresholds["min_profit_factor"])
        ):
            soft_pass_count += 1

    if last_train_result is not None:
        scored.train_pnl = last_train_result.realized_pnl
    if last_validation_result is not None:
        scored.validation_pnl = last_validation_result.realized_pnl
        scored.validation_profit_factor = last_validation_result.profit_factor
        scored.validation_closed_trades = len(last_validation_result.closed_trades)
    if last_test_result is not None:
        scored.test_pnl = last_test_result.realized_pnl
        scored.test_profit_factor = last_test_result.profit_factor
        scored.test_closed_trades = len(last_test_result.closed_trades)
    scored.walk_forward_windows = len(validation_pnls)
    if validation_pnls:
        scored.walk_forward_avg_validation_pnl = mean(validation_pnls)
        scored.walk_forward_avg_validation_pf = mean(validation_pfs)
    if test_pnls:
        scored.walk_forward_avg_test_pnl = mean(test_pnls)
        scored.walk_forward_avg_test_pf = mean(test_pfs)
    if scored.walk_forward_windows > 0:
        scored.walk_forward_pass_rate_pct = pass_count / scored.walk_forward_windows * 100.0
        scored.walk_forward_soft_pass_rate_pct = soft_pass_count / scored.walk_forward_windows * 100.0

    return scored


def _default_variant_features(feature_variants: dict[str, list[FeatureVector]]) -> list[FeatureVector]:
    for preferred in ("5m_all", "default", "15m_all"):
        if preferred in feature_variants and feature_variants[preferred]:
            return feature_variants[preferred]
    for features in feature_variants.values():
        if features:
            return features
    return []


def _merge_execution_overrides(
    base: dict[str, float | int] | None,
    overrides: dict[str, float | int],
) -> dict[str, float | int]:
    merged = dict(base or {})
    merged.update(overrides)
    return merged


def _exit_family_specs(config: SystemConfig, symbol: str, specs: list[CandidateSpec]) -> list[CandidateSpec]:
    del config
    upper = symbol.upper()
    exit_specs: list[CandidateSpec] = []
    for spec in specs:
        if "__exit_" in spec.name:
            continue
        if "mean_reversion" in spec.name or "range_reversion" in spec.name:
            exit_specs.append(
                CandidateSpec(
                    name=f"{spec.name}__exit_quick",
                    description=f"{spec.description} with quick-fail mean reversion exits",
                    agents=spec.agents,
                    code_path=spec.code_path,
                    execution_overrides=_merge_execution_overrides(
                        spec.execution_overrides,
                        {
                            "max_holding_bars": 12 if "XAU" in upper else 16,
                            "take_profit_atr_multiple": 1.4,
                            "stale_breakout_bars": 3,
                            "structure_exit_bars": 2,
                        },
                    ),
                    variant_label=spec.variant_label,
                    timeframe_label=spec.timeframe_label,
                    session_label=spec.session_label,
                )
            )
            continue

        exit_specs.extend(
            [
                CandidateSpec(
                    name=f"{spec.name}__exit_trend",
                    description=f"{spec.description} with trend-runner exits",
                    agents=spec.agents,
                    code_path=spec.code_path,
                    execution_overrides=_merge_execution_overrides(
                        spec.execution_overrides,
                        {
                            "max_holding_bars": 0,
                            "take_profit_atr_multiple": 3.2,
                            "trailing_stop_atr_multiple": 1.2,
                            "stale_breakout_bars": 8,
                            "structure_exit_bars": 0,
                        },
                    ),
                    variant_label=spec.variant_label,
                    timeframe_label=spec.timeframe_label,
                    session_label=spec.session_label,
                ),
                CandidateSpec(
                    name=f"{spec.name}__exit_fastfail",
                    description=f"{spec.description} with fast-fail exits",
                    agents=spec.agents,
                    code_path=spec.code_path,
                    execution_overrides=_merge_execution_overrides(
                        spec.execution_overrides,
                        {
                            "max_holding_bars": 14 if "XAU" in upper else 18,
                            "take_profit_atr_multiple": 1.8,
                            "stale_breakout_bars": 4,
                            "structure_exit_bars": 2,
                        },
                    ),
                    variant_label=spec.variant_label,
                    timeframe_label=spec.timeframe_label,
                    session_label=spec.session_label,
                ),
            ]
        )
    return exit_specs


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
    elif _is_stock_symbol(symbol):
        specs.extend(
            [
                CandidateSpec(
                    name=f"{upper.lower()}_stock_news_momentum_patient",
                    description=f"{upper} news momentum with slower exits and wider event follow-through",
                    agents=[StockNewsMomentumAgent(min_relative_volume=1.25, min_atr_proxy=0.0036), EventAwareRiskSentinelAgent(True), risk],
                    code_path="quant_system.agents.stocks.StockNewsMomentumAgent",
                    execution_overrides={"structure_exit_bars": 0, "stale_breakout_bars": 7, "max_holding_bars": 24},
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_stock_gap_fade_selective",
                    description=f"{upper} selective gap fade with stricter extension filter",
                    agents=[StockGapFadeAgent(min_gap_proxy=0.005, min_relative_volume=1.1), EventAwareRiskSentinelAgent(False), risk],
                    code_path="quant_system.agents.stocks.StockGapFadeAgent",
                    execution_overrides={"structure_exit_bars": 1, "stale_breakout_bars": 4, "max_holding_bars": 16},
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_stock_gap_and_go_selective",
                    description=f"{upper} selective gap-and-go continuation with stricter opening filter",
                    agents=[StockGapAndGoAgent(min_relative_volume=1.3, min_atr_proxy=0.004), EventAwareRiskSentinelAgent(False), risk],
                    code_path="quant_system.agents.stocks.StockGapAndGoAgent",
                    execution_overrides={"structure_exit_bars": 0, "stale_breakout_bars": 5, "max_holding_bars": 18},
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_stock_post_earnings_drift_patient",
                    description=f"{upper} post-earnings drift with patient exits",
                    agents=[StockPostEarningsDriftAgent(min_relative_volume=1.05, max_minutes_from_open=180.0), EventAwareRiskSentinelAgent(True), risk],
                    code_path="quant_system.agents.stocks.StockPostEarningsDriftAgent",
                    execution_overrides={"structure_exit_bars": 0, "stale_breakout_bars": 8, "max_holding_bars": 28},
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_stock_power_hour_continuation_selective",
                    description=f"{upper} power-hour continuation with stronger momentum requirement",
                    agents=[StockPowerHourContinuationAgent(min_relative_volume=0.95, min_momentum_20=0.0035), EventAwareRiskSentinelAgent(False), risk],
                    code_path="quant_system.agents.stocks.StockPowerHourContinuationAgent",
                    execution_overrides={"structure_exit_bars": 0, "stale_breakout_bars": 4, "max_holding_bars": 14},
                ),
            ]
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
                CandidateSpec(
                    name=f"{upper.lower()}_short_trend_rejection",
                    description=f"{upper} short rejection after weak rebound",
                    agents=[US500ShortTrendRejectionAgent(config.agents.min_trend_strength), risk],
                    code_path="quant_system.agents.us500.US500ShortTrendRejectionAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 6,
                        "max_holding_bars": 22,
                        "take_profit_atr_multiple": 2.3,
                    },
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_opening_drive_short_reclaim",
                    description=f"{upper} short reclaim after failed opening drive",
                    agents=[US500OpeningDriveShortReclaimAgent(config.agents.min_trend_strength), risk],
                    code_path="quant_system.agents.us500.US500OpeningDriveShortReclaimAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 5,
                        "max_holding_bars": 20,
                        "take_profit_atr_multiple": 2.0,
                    },
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_short_trend_rejection_selective",
                    description=f"{upper} short rejection with stricter 16:00-only filter",
                    agents=[
                        US500ShortTrendRejectionAgent(
                            config.agents.min_trend_strength * 1.1,
                            rebound_z_limit=0.45,
                            allowed_hours={16},
                            min_relative_volume=0.95,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.us500.US500ShortTrendRejectionAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 4,
                        "max_holding_bars": 16,
                        "take_profit_atr_multiple": 2.1,
                        "trailing_stop_atr_multiple": 0.75,
                    },
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_short_trend_rejection_flat_high",
                    description=f"{upper} short rejection limited to flat/high-volatility regime",
                    agents=[
                        US500ShortTrendRejectionAgent(
                            config.agents.min_trend_strength * 1.08,
                            rebound_z_limit=0.42,
                            allowed_hours={16},
                            min_relative_volume=0.92,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.us500.US500ShortTrendRejectionAgent",
                    regime_filter_label="trend_flat_vol_high",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 4,
                        "max_holding_bars": 16,
                        "take_profit_atr_multiple": 2.15,
                        "trailing_stop_atr_multiple": 0.72,
                    },
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_short_trend_rejection_flat_high_dense",
                    description=f"{upper} denser short rejection in flat/high-volatility regime",
                    agents=[
                        US500ShortTrendRejectionAgent(
                            config.agents.min_trend_strength * 0.95,
                            rebound_z_limit=0.25,
                            allowed_hours={16},
                            min_relative_volume=0.88,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.us500.US500ShortTrendRejectionAgent",
                    regime_filter_label="trend_flat_vol_high",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 6,
                        "max_holding_bars": 22,
                        "take_profit_atr_multiple": 2.35,
                        "trailing_stop_atr_multiple": 0.85,
                    },
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_short_trend_rejection_flat_high_exit_optimized",
                    description=f"{upper} flat/high-volatility short rejection with trend-friendly exits",
                    agents=[
                        US500ShortTrendRejectionAgent(
                            config.agents.min_trend_strength * 1.02,
                            rebound_z_limit=0.4,
                            allowed_hours={16},
                            min_relative_volume=0.9,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.us500.US500ShortTrendRejectionAgent",
                    regime_filter_label="trend_flat_vol_high",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 6,
                        "stale_breakout_atr_fraction": 0.04,
                        "max_holding_bars": 0,
                        "stop_loss_atr_multiple": 1.0,
                        "take_profit_atr_multiple": 2.3,
                        "break_even_atr_multiple": 0.3,
                        "trailing_stop_atr_multiple": 0.6,
                    },
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_opening_drive_short_reclaim_selective",
                    description=f"{upper} short reclaim with tighter session and volume filter",
                    agents=[
                        US500OpeningDriveShortReclaimAgent(
                            config.agents.min_trend_strength * 1.15,
                            allowed_hours={15},
                            min_relative_volume=0.95,
                            max_session_position=0.48,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.us500.US500OpeningDriveShortReclaimAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 4,
                        "max_holding_bars": 14,
                        "take_profit_atr_multiple": 1.9,
                        "trailing_stop_atr_multiple": 0.7,
                    },
                ),
            ]
        )
        if upper == "US500":
            specs.extend(
                [
                    CandidateSpec(
                        name="us500_momentum_impulse",
                        description="US500 momentum impulse in strong uptrend and high participation",
                        agents=[
                            US500MomentumImpulseAgent(
                                config.agents.min_trend_strength * 1.05,
                                allowed_hours={16, 17, 18},
                                min_relative_volume=0.92,
                            ),
                            risk,
                        ],
                        code_path="quant_system.agents.us500.US500MomentumImpulseAgent",
                        execution_overrides={
                            "structure_exit_bars": 0,
                            "stale_breakout_bars": 5,
                            "max_holding_bars": 18,
                            "take_profit_atr_multiple": 2.4,
                            "trailing_stop_atr_multiple": 0.8,
                        },
                    ),
                    CandidateSpec(
                        name="us500_momentum_impulse_high_vol",
                        description="US500 momentum impulse focused on trend-up/high-volatility regime",
                        agents=[
                            US500MomentumImpulseAgent(
                                config.agents.min_trend_strength * 1.1,
                                allowed_hours={16, 17},
                                min_relative_volume=0.95,
                            ),
                            risk,
                        ],
                        code_path="quant_system.agents.us500.US500MomentumImpulseAgent",
                        regime_filter_label="trend_up_vol_high",
                        execution_overrides={
                            "structure_exit_bars": 0,
                            "stale_breakout_bars": 4,
                            "max_holding_bars": 16,
                            "take_profit_atr_multiple": 2.5,
                            "trailing_stop_atr_multiple": 0.78,
                        },
                    ),
                    CandidateSpec(
                        name="us500_short_vwap_reject",
                        description="US500 short rejection around VWAP in weak or flat tape",
                        agents=[
                            US500ShortVWAPRejectAgent(
                                config.agents.min_trend_strength,
                                allowed_hours={16, 17},
                                min_relative_volume=0.9,
                            ),
                            risk,
                        ],
                        code_path="quant_system.agents.us500.US500ShortVWAPRejectAgent",
                        execution_overrides={
                            "structure_exit_bars": 0,
                            "stale_breakout_bars": 5,
                            "max_holding_bars": 18,
                            "take_profit_atr_multiple": 2.2,
                            "trailing_stop_atr_multiple": 0.72,
                        },
                    ),
                    CandidateSpec(
                        name="us500_short_vwap_reject_flat_high",
                        description="US500 short VWAP rejection limited to flat/high-volatility regime",
                        agents=[
                            US500ShortVWAPRejectAgent(
                                config.agents.min_trend_strength * 0.9,
                                allowed_hours={16},
                                min_relative_volume=0.92,
                            ),
                            risk,
                        ],
                        code_path="quant_system.agents.us500.US500ShortVWAPRejectAgent",
                        regime_filter_label="trend_flat_vol_high",
                        execution_overrides={
                            "structure_exit_bars": 0,
                            "stale_breakout_bars": 4,
                            "max_holding_bars": 16,
                            "take_profit_atr_multiple": 2.15,
                            "trailing_stop_atr_multiple": 0.7,
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
                CandidateSpec(
                    name="ger40_range_reject_short",
                    description="GER40 short rejection below opening range",
                    agents=[GER40RangeRejectShortAgent(), risk],
                    code_path="quant_system.agents.ger40.GER40RangeRejectShortAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 6,
                        "max_holding_bars": 18,
                        "take_profit_atr_multiple": 1.9,
                    },
                ),
                CandidateSpec(
                    name="ger40_failed_breakout_short",
                    description="GER40 short after failed upside breakout",
                    agents=[GER40FailedBreakoutShortAgent(), risk],
                    code_path="quant_system.agents.ger40.GER40FailedBreakoutShortAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 5,
                        "max_holding_bars": 16,
                        "take_profit_atr_multiple": 1.8,
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
    elif _is_stock_symbol(symbol):
        if weakest_exit in {"stale_breakout", "structure_exit"}:
            specs.append(
                CandidateSpec(
                    name=f"{upper.lower()}_stock_news_momentum_exit_relaxed",
                    description=f"{upper} stock news momentum with relaxed structure exit after autopsy",
                    agents=[StockNewsMomentumAgent(min_relative_volume=1.2, min_atr_proxy=0.0035), EventAwareRiskSentinelAgent(True), RiskSentinelAgent(max_volatility=config.risk.max_volatility, min_relative_volume=config.agents.min_relative_volume)],
                    code_path="quant_system.agents.stocks.StockNewsMomentumAgent",
                    execution_overrides={"structure_exit_bars": 0, "stale_breakout_bars": 8, "max_holding_bars": 26},
                )
            )
        if closed_trades <= 4:
            specs.append(
                CandidateSpec(
                    name=f"{upper.lower()}_stock_post_earnings_drift_dense",
                    description=f"{upper} denser post-earnings drift variant",
                    agents=[StockPostEarningsDriftAgent(min_relative_volume=1.0, max_minutes_from_open=210.0), EventAwareRiskSentinelAgent(True), RiskSentinelAgent(max_volatility=config.risk.max_volatility, min_relative_volume=config.agents.min_relative_volume)],
                    code_path="quant_system.agents.stocks.StockPostEarningsDriftAgent",
                    execution_overrides={"structure_exit_bars": 0, "stale_breakout_bars": 7, "max_holding_bars": 30},
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
        if best_tradeable.name.startswith(f"{upper.lower()}_short_trend_rejection") or best_tradeable.name.startswith(
            f"{upper.lower()}_opening_drive_short_reclaim"
        ):
            specs.append(
                CandidateSpec(
                    name=f"{upper.lower()}_short_trend_rejection_second_pass",
                    description=f"{upper} second-pass short rejection focused on early weakness",
                    agents=[
                        US500ShortTrendRejectionAgent(
                            config.agents.min_trend_strength * 1.05,
                            rebound_z_limit=0.5,
                            allowed_hours={16},
                            min_relative_volume=0.9,
                        ),
                        RiskSentinelAgent(max_volatility=config.risk.max_volatility * 1.3, min_relative_volume=0.9),
                    ],
                    code_path="quant_system.agents.us500.US500ShortTrendRejectionAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 4,
                        "max_holding_bars": 14,
                        "take_profit_atr_multiple": 2.2,
                    },
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


def _component_names(candidate_name: str) -> list[str]:
    return [part.strip() for part in candidate_name.split("__plus__") if part.strip()]


def _trade_entry_timestamps(trade_log_path: str) -> set[str]:
    trade_path = Path(trade_log_path)
    if not trade_path.exists():
        return set()
    with trade_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return {str(row.get("entry_timestamp", "")).strip() for row in reader if str(row.get("entry_timestamp", "")).strip()}


def _feature_regime_label(feature: FeatureVector) -> str:
    trend_strength = feature.values.get("trend_strength", 0.0)
    atr_proxy = feature.values.get("atr_proxy", 0.0)
    if trend_strength >= 0.001:
        trend_label = "trend_up"
    elif trend_strength <= -0.001:
        trend_label = "trend_down"
    else:
        trend_label = "trend_flat"

    if atr_proxy >= 0.003:
        vol_label = "vol_high"
    elif atr_proxy <= 0.0012:
        vol_label = "vol_low"
    else:
        vol_label = "vol_mid"
    return f"{trend_label}_{vol_label}"


def _annotate_regime_metrics(result: CandidateResult, features: list[FeatureVector], trades) -> None:
    if not trades:
        return
    regime_by_timestamp = {trade.timestamp.isoformat(): _feature_regime_label(trade) for trade in features}
    regime_pnls: dict[str, list[float]] = {}
    for trade in trades:
        regime = regime_by_timestamp.get(trade.entry_timestamp.isoformat(), "unknown")
        regime_pnls.setdefault(regime, []).append(trade.pnl)
    if not regime_pnls:
        return
    best_regime = max(regime_pnls, key=lambda key: sum(regime_pnls[key]))
    worst_regime = min(regime_pnls, key=lambda key: sum(regime_pnls[key]))
    dominant_regime = max(regime_pnls, key=lambda key: len(regime_pnls[key]))
    total_trades = sum(len(values) for values in regime_pnls.values())
    result.best_regime = best_regime
    result.best_regime_pnl = sum(regime_pnls[best_regime])
    result.worst_regime = worst_regime
    result.worst_regime_pnl = sum(regime_pnls[worst_regime])
    result.dominant_regime_share_pct = (len(regime_pnls[dominant_regime]) / total_trades * 100.0) if total_trades else 0.0


def _annotate_combo_results(results: list[CandidateResult]) -> None:
    lookup = {row.name: row for row in results}
    for row in results:
        components = _component_names(row.name)
        row.component_count = len(components)
        if len(components) <= 1:
            continue
        component_rows = [lookup[name] for name in components if name in lookup]
        if len(component_rows) != len(components):
            continue
        best_component_validation = max(component.validation_pnl for component in component_rows)
        best_component_test = max(component.test_pnl for component in component_rows)
        row.combo_outperformance_score = min(
            row.validation_pnl - best_component_validation,
            row.test_pnl - best_component_test,
        )
        component_entries = [_trade_entry_timestamps(component.trade_log_path) for component in component_rows]
        if not component_entries:
            continue
        union_entries = set().union(*component_entries)
        overlap_entries = set.intersection(*component_entries) if len(component_entries) > 1 else component_entries[0]
        row.combo_trade_overlap_pct = (
            len(overlap_entries) / len(union_entries) * 100.0 if union_entries else 0.0
        )


def _regime_improvement_specs(specs: list[CandidateSpec], results: list[CandidateResult]) -> list[CandidateSpec]:
    lookup = {spec.name: spec for spec in specs}
    ranked = sorted(
        [row for row in results if row.best_regime and row.best_regime_pnl > 0.0 and row.worst_regime_pnl < 0.0],
        key=lambda item: (item.best_regime_pnl - abs(item.worst_regime_pnl), item.profit_factor, item.closed_trades),
        reverse=True,
    )
    generated: list[CandidateSpec] = []
    seen: set[tuple[str, str]] = set()
    for row in ranked[:4]:
        base_spec = lookup.get(row.name)
        if base_spec is None:
            continue
        key = (base_spec.name, row.best_regime)
        if key in seen:
            continue
        seen.add(key)
        generated.append(
            CandidateSpec(
                name=f"{base_spec.name}__regime_{row.best_regime}",
                description=f"{base_spec.description} focused on {row.best_regime}",
                agents=base_spec.agents,
                code_path=base_spec.code_path,
                execution_overrides=copy.deepcopy(base_spec.execution_overrides),
                variant_label=base_spec.variant_label,
                timeframe_label=base_spec.timeframe_label,
                session_label=base_spec.session_label,
                regime_filter_label=row.best_regime,
            )
        )
    return generated


def _regime_candidates_from_row(row: CandidateResult) -> list[str]:
    candidates: list[str] = []
    if row.best_regime:
        candidates.append(row.best_regime)
        best_parts = row.best_regime.split("_")
        if len(best_parts) >= 3:
            candidates.append("_".join(best_parts[:2]))
            candidates.append("_".join(best_parts[2:]))
    if row.worst_regime:
        candidates.append(f"exclude:{row.worst_regime}")
        worst_parts = row.worst_regime.split("_")
        if len(worst_parts) >= 3:
            candidates.append(f"exclude:{'_'.join(worst_parts[:2])}")
    deduped: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        if item and item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def _autopsy_improvement_specs(
    config: SystemConfig,
    symbol: str,
    specs: list[CandidateSpec],
    results: list[CandidateResult],
) -> list[CandidateSpec]:
    lookup = {spec.name: spec for spec in specs}
    if not (_is_crypto_symbol(symbol) or _is_stock_symbol(symbol)):
        return []
    near_misses = [
        row
        for row in sorted(results, key=lambda item: (item.realized_pnl, item.profit_factor, item.closed_trades), reverse=True)
        if row.realized_pnl > 0.0
        and row.test_pnl > 0.0
        and (row.validation_pnl <= 0.0 or row.validation_profit_factor < 1.0 or row.walk_forward_pass_rate_pct < 50.0)
        and row.best_regime_pnl > 0.0
    ]
    generated: list[CandidateSpec] = []
    seen: set[tuple[str, str]] = set()
    for row in near_misses[:5]:
        base_spec = lookup.get(row.name)
        if base_spec is None:
            continue
        overrides = copy.deepcopy(base_spec.execution_overrides) or {}
        if row.dominant_exit in {"structure_exit", "stale_breakout"}:
            overrides = _merge_execution_overrides(
                overrides,
                {
                    "structure_exit_bars": 0,
                    "stale_breakout_bars": max(int(overrides.get("stale_breakout_bars", 6)), 8),
                    "max_holding_bars": max(int(overrides.get("max_holding_bars", 24)), 24),
                },
            )
        if _is_stock_symbol(symbol):
            if row.name.startswith("mean_reversion__15m_midday"):
                generated.append(
                    CandidateSpec(
                        name=f"{base_spec.name}__autopsy_midday_dense",
                        description=f"{base_spec.description} autopsy-tuned for denser midday continuation mean reversion",
                        agents=[
                            MeanReversionAgent(max(config.agents.mean_reversion_window - 2, 4), config.agents.mean_reversion_threshold * 0.8),
                            EventAwareRiskSentinelAgent(allow_high_impact_day=False),
                            RiskSentinelAgent(max_volatility=config.risk.max_volatility, min_relative_volume=max(config.agents.min_relative_volume * 0.9, 0.7)),
                        ],
                        code_path="quant_system.agents.trend.MeanReversionAgent",
                        execution_overrides=_merge_execution_overrides(
                            overrides,
                            {"structure_exit_bars": 0, "stale_breakout_bars": 6, "max_holding_bars": 20},
                        ),
                        variant_label=base_spec.variant_label,
                        timeframe_label=base_spec.timeframe_label,
                        session_label=base_spec.session_label,
                        regime_filter_label=row.best_regime or "trend_up",
                    )
                )
            if row.name.startswith("momentum__15m_power"):
                generated.append(
                    CandidateSpec(
                        name=f"{base_spec.name}__autopsy_power_dense",
                        description=f"{base_spec.description} autopsy-tuned for denser power-hour continuation",
                        agents=[
                            MomentumConfirmationAgent(config.agents.mean_reversion_threshold * 0.65),
                            EventAwareRiskSentinelAgent(allow_high_impact_day=False),
                            RiskSentinelAgent(max_volatility=config.risk.max_volatility, min_relative_volume=max(config.agents.min_relative_volume * 0.9, 0.7)),
                        ],
                        code_path="quant_system.agents.trend.MomentumConfirmationAgent",
                        execution_overrides=_merge_execution_overrides(
                            overrides,
                            {"structure_exit_bars": 0, "stale_breakout_bars": 5, "max_holding_bars": 18},
                        ),
                        variant_label=base_spec.variant_label,
                        timeframe_label=base_spec.timeframe_label,
                        session_label=base_spec.session_label,
                        regime_filter_label=row.best_regime or "trend_up",
                    )
                )
        for regime_filter in _regime_candidates_from_row(row)[:3]:
            key = (base_spec.name, regime_filter)
            if key in seen:
                continue
            seen.add(key)
            generated.append(
                CandidateSpec(
                    name=f"{base_spec.name}__autopsy_{_symbol_slug(regime_filter)}",
                    description=f"{base_spec.description} autopsy-focused on {regime_filter}",
                    agents=base_spec.agents,
                    code_path=base_spec.code_path,
                    execution_overrides=overrides,
                    variant_label=base_spec.variant_label,
                    timeframe_label=base_spec.timeframe_label,
                    session_label=base_spec.session_label,
                    regime_filter_label=regime_filter,
                )
            )
    return generated


def _near_miss_optimizer_specs(symbol: str, specs: list[CandidateSpec], results: list[CandidateResult]) -> list[CandidateSpec]:
    lookup = {spec.name: spec for spec in specs}
    generated: list[CandidateSpec] = []
    seen: set[str] = set()
    thresholds = _research_thresholds(symbol)
    near_misses = [
        row
        for row in sorted(results, key=lambda item: (item.realized_pnl, item.profit_factor, item.closed_trades), reverse=True)
        if row.component_count == 1
        and row.name in lookup
        and row.realized_pnl > 0.0
        and row.profit_factor >= 1.0
        and not _meets_viability(row, symbol)
    ]
    for row in near_misses[:4]:
        base_spec = lookup[row.name]
        autopsy = _analyze_trade_rows(row.trade_log_path)
        weakest_exit = str(autopsy.get("weakest_exit", "") or "")
        base_overrides = base_spec.execution_overrides or {}

        patient_overrides = _merge_execution_overrides(
            base_overrides,
            {
                "structure_exit_bars": 0,
                "stale_breakout_bars": int(base_overrides.get("stale_breakout_bars", 5)) + 2,
                "max_holding_bars": 0 if row.sparse_strategy else int(base_overrides.get("max_holding_bars", 18)) + 4,
                "take_profit_atr_multiple": float(base_overrides.get("take_profit_atr_multiple", 2.2)) + 0.2,
                "break_even_atr_multiple": max(float(base_overrides.get("break_even_atr_multiple", 0.4)), 0.3),
                "trailing_stop_atr_multiple": max(float(base_overrides.get("trailing_stop_atr_multiple", 0.8)), 0.7),
            },
        )
        if weakest_exit == "stale_breakout":
            patient_overrides["stale_breakout_atr_fraction"] = max(float(base_overrides.get("stale_breakout_atr_fraction", 0.1)), 0.05)

        protective_overrides = _merge_execution_overrides(
            base_overrides,
            {
                "structure_exit_bars": 0,
                "stale_breakout_bars": max(int(base_overrides.get("stale_breakout_bars", 5)), 4),
                "stop_loss_atr_multiple": max(float(base_overrides.get("stop_loss_atr_multiple", 1.2)) - 0.1, 0.8),
                "break_even_atr_multiple": 0.25,
                "trailing_stop_atr_multiple": 0.55,
                "take_profit_atr_multiple": max(float(base_overrides.get("take_profit_atr_multiple", 2.0)), 2.0),
            },
        )
        dense_overrides = _merge_execution_overrides(
            base_overrides,
            {
                "min_bars_between_trades": max(int(base_overrides.get("min_bars_between_trades", 10)) - 3, 2),
                "stale_breakout_bars": int(base_overrides.get("stale_breakout_bars", 5)) + 1,
                "max_holding_bars": 0 if row.sparse_strategy else max(int(base_overrides.get("max_holding_bars", 18)) + 2, 18),
                "take_profit_atr_multiple": max(float(base_overrides.get("take_profit_atr_multiple", 2.0)), 2.0),
            },
        )

        variant_triplets: list[tuple[str, dict[str, float | int], str]] = [
            ("near_miss_patient", patient_overrides, "with patient near-miss optimization"),
            ("near_miss_protective", protective_overrides, "with protective near-miss optimization"),
        ]
        low_trade_near_miss = (
            row.validation_closed_trades < int(thresholds["validation_closed_trades"])
            or row.test_closed_trades < int(thresholds["test_closed_trades"])
            or row.sparse_strategy
        )
        if low_trade_near_miss:
            variant_triplets.append(
                ("near_miss_dense", dense_overrides, "with denser near-miss optimization")
            )

        for label, overrides, description_suffix in variant_triplets:
            candidate_name = f"{base_spec.name}__{label}"
            if candidate_name in seen:
                continue
            seen.add(candidate_name)
            generated.append(
                CandidateSpec(
                    name=candidate_name,
                    description=f"{base_spec.description} {description_suffix}",
                    agents=base_spec.agents,
                    code_path=base_spec.code_path,
                    execution_overrides=overrides,
                    variant_label=base_spec.variant_label,
                    timeframe_label=base_spec.timeframe_label,
                    session_label=base_spec.session_label,
                    regime_filter_label=base_spec.regime_filter_label,
                )
            )
            for regime_filter in _regime_candidates_from_row(row)[:2]:
                regime_name = f"{candidate_name}__{_symbol_slug(regime_filter)}"
                if regime_name in seen:
                    continue
                seen.add(regime_name)
                generated.append(
                    CandidateSpec(
                        name=regime_name,
                        description=f"{base_spec.description} {description_suffix} focused on {regime_filter}",
                        agents=base_spec.agents,
                        code_path=base_spec.code_path,
                        execution_overrides=overrides,
                        variant_label=base_spec.variant_label,
                        timeframe_label=base_spec.timeframe_label,
                        session_label=base_spec.session_label,
                        regime_filter_label=regime_filter,
                    )
                )
    return generated


def _execution_candidate_row_from_result(symbol: str, row: CandidateResult) -> dict[str, object]:
    return {
        "candidate_name": row.name,
        "symbol": symbol,
        "code_path": row.code_path,
        "realized_pnl": row.realized_pnl,
        "profit_factor": row.profit_factor,
        "closed_trades": row.closed_trades,
        "payoff_ratio": row.payoff_ratio,
        "validation_pnl": row.validation_pnl,
        "validation_profit_factor": row.validation_profit_factor,
        "validation_closed_trades": row.validation_closed_trades,
        "test_pnl": row.test_pnl,
        "test_profit_factor": row.test_profit_factor,
        "test_closed_trades": row.test_closed_trades,
        "walk_forward_windows": row.walk_forward_windows,
        "walk_forward_pass_rate_pct": row.walk_forward_pass_rate_pct,
        "walk_forward_soft_pass_rate_pct": row.walk_forward_soft_pass_rate_pct,
        "walk_forward_avg_validation_pnl": row.walk_forward_avg_validation_pnl,
        "walk_forward_avg_test_pnl": row.walk_forward_avg_test_pnl,
        "sparse_strategy": row.sparse_strategy,
        "component_count": row.component_count,
        "combo_outperformance_score": row.combo_outperformance_score,
        "combo_trade_overlap_pct": row.combo_trade_overlap_pct,
        "recommended": False,
        "variant_label": row.variant_label,
        "regime_filter_label": row.regime_filter_label,
        "execution_overrides": row.execution_overrides or {},
    }


def _near_miss_local_score(candidate: CandidateResult, execution_result: ExecutionResult) -> float:
    score = (
        candidate.validation_pnl * 3.0
        + candidate.test_pnl * 3.0
        + candidate.walk_forward_avg_validation_pnl * 1.5
        + candidate.walk_forward_avg_test_pnl * 1.5
        + execution_result.realized_pnl * 3.0
        + max(candidate.validation_profit_factor - 1.0, 0.0) * 0.5
        + max(candidate.test_profit_factor - 1.0, 0.0) * 0.75
        + max(execution_result.profit_factor - 1.0, 0.0) * 0.75
    )
    if execution_result.realized_pnl <= 0.0:
        score -= 5.0
    if candidate.validation_pnl <= 0.0:
        score -= 3.0
    if candidate.walk_forward_avg_validation_pnl <= 0.0:
        score -= 2.0
    return score


def _near_miss_local_optimizer(
    config: SystemConfig,
    symbol: str,
    data_symbol: str,
    specs: list[CandidateSpec],
    results: list[CandidateResult],
    symbol_slug: str,
) -> tuple[list[CandidateSpec], list[CandidateResult]]:
    lookup = {spec.name: spec for spec in specs}
    thresholds = _research_thresholds(symbol)
    prioritized = [
        row
        for row in sorted(
            results,
            key=lambda item: (
                item.realized_pnl,
                item.profit_factor,
                item.test_pnl,
                item.validation_pnl,
                item.closed_trades,
            ),
            reverse=True,
        )
        if row.component_count == 1
        and row.name in lookup
        and row.realized_pnl > 0.0
        and row.profit_factor >= 1.0
        and not _meets_viability(row, symbol)
    ]

    accepted_specs: list[CandidateSpec] = []
    accepted_results: list[CandidateResult] = []
    seen: set[str] = set()

    for base_row in prioritized[:3]:
        base_spec = lookup[base_row.name]
        base_execution, _, _ = _run_candidate_bundle(
            config,
            symbol,
            data_symbol,
            [_execution_candidate_row_from_result(symbol, base_row)],
        )
        base_score = _near_miss_local_score(base_row, base_execution)
        base_overrides = base_spec.execution_overrides or {}
        low_trade = (
            base_row.validation_closed_trades < int(thresholds["validation_closed_trades"])
            or base_row.test_closed_trades < int(thresholds["test_closed_trades"])
            or base_row.sparse_strategy
        )
        weak_validation = base_row.validation_pnl <= 0.0 or base_row.walk_forward_avg_validation_pnl <= 0.0

        override_variants: list[tuple[str, dict[str, float | int], str]] = []
        if weak_validation:
            override_variants.extend(
                [
                    (
                        "local_opt_consistency",
                        _merge_execution_overrides(
                            base_overrides,
                            {
                                "structure_exit_bars": 0,
                                "stale_breakout_bars": max(int(base_overrides.get("stale_breakout_bars", 5)), 5),
                                "break_even_atr_multiple": 0.25,
                                "trailing_stop_atr_multiple": 0.6,
                                "take_profit_atr_multiple": max(float(base_overrides.get("take_profit_atr_multiple", 2.0)), 2.0),
                            },
                        ),
                        "with local consistency optimization",
                    ),
                    (
                        "local_opt_validation",
                        _merge_execution_overrides(
                            base_overrides,
                            {
                                "structure_exit_bars": 0,
                                "stale_breakout_bars": int(base_overrides.get("stale_breakout_bars", 5)) + 1,
                                "stop_loss_atr_multiple": max(float(base_overrides.get("stop_loss_atr_multiple", 1.2)) - 0.05, 0.8),
                                "break_even_atr_multiple": 0.2,
                                "trailing_stop_atr_multiple": 0.55,
                            },
                        ),
                        "with validation-focused optimization",
                    ),
                ]
            )
        if low_trade:
            override_variants.append(
                (
                    "local_opt_density",
                    _merge_execution_overrides(
                        base_overrides,
                        {
                            "min_bars_between_trades": max(int(base_overrides.get("min_bars_between_trades", 10)) - 2, 2),
                            "max_holding_bars": 0 if base_row.sparse_strategy else max(int(base_overrides.get("max_holding_bars", 18)) + 2, 18),
                            "stale_breakout_bars": int(base_overrides.get("stale_breakout_bars", 5)) + 1,
                        },
                    ),
                    "with density optimization",
                )
            )
        if not override_variants:
            continue

        best_variant_score = base_score
        best_variant_spec: CandidateSpec | None = None
        best_variant_result: CandidateResult | None = None

        for label, overrides, suffix in override_variants:
            candidate_name = f"{base_spec.name}__{label}"
            if candidate_name in seen:
                continue
            seen.add(candidate_name)
            candidate_spec = CandidateSpec(
                name=candidate_name,
                description=f"{base_spec.description} {suffix}",
                agents=base_spec.agents,
                code_path=base_spec.code_path,
                execution_overrides=overrides,
                variant_label=base_spec.variant_label,
                timeframe_label=base_spec.timeframe_label,
                session_label=base_spec.session_label,
                regime_filter_label=base_spec.regime_filter_label,
            )
            features, _ = load_execution_features_for_variant(
                config,
                symbol,
                data_symbol,
                candidate_spec.variant_label,
                candidate_spec.regime_filter_label,
            )
            if not features:
                continue
            candidate_result = _run_candidate_with_splits(
                config,
                features,
                candidate_spec,
                "near_miss_local_optimized",
                f"{symbol_slug}_{candidate_spec.name}_symbol_candidate",
            )
            execution_result, _, _ = _run_candidate_bundle(
                config,
                symbol,
                data_symbol,
                [_execution_candidate_row_from_result(symbol, candidate_result)],
            )
            candidate_score = _near_miss_local_score(candidate_result, execution_result)
            if candidate_score > best_variant_score and execution_result.realized_pnl > base_execution.realized_pnl:
                best_variant_score = candidate_score
                best_variant_spec = candidate_spec
                best_variant_result = candidate_result

        if best_variant_spec is not None and best_variant_result is not None:
            accepted_specs.append(best_variant_spec)
            accepted_results.append(best_variant_result)

    return accepted_specs, accepted_results


def select_execution_candidates(rows: list[dict[str, object]], max_candidates: int = 3) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    used_components: set[str] = set()
    viable_rows = [row for row in rows if _meets_viability(row, str(row.get("symbol", "")))]
    ranked = sorted(
        viable_rows,
        key=lambda row: (
            bool(row.get("recommended")),
            float(row.get("combo_outperformance_score", 0.0)),
            max(float(row.get("walk_forward_pass_rate_pct", 0.0)), float(row.get("walk_forward_soft_pass_rate_pct", 0.0))),
            float(row.get("walk_forward_avg_test_pnl", 0.0)),
            float(row.get("test_pnl", 0.0)),
            float(row.get("validation_pnl", 0.0)),
            float(row.get("test_profit_factor", 0.0)),
            int(row.get("test_closed_trades", 0)),
        ),
        reverse=True,
    )
    for row in ranked:
        components = _component_set(str(row["code_path"]))
        if selected and components & used_components:
            continue
        selected.append(row)
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
                "expectancy",
                "avg_win",
                "avg_loss",
                "payoff_ratio",
                "avg_hold_bars",
                "dominant_exit",
                "dominant_exit_share_pct",
                "component_count",
                "combo_outperformance_score",
                "combo_trade_overlap_pct",
                "best_regime",
                "best_regime_pnl",
                "worst_regime",
                "worst_regime_pnl",
                "dominant_regime_share_pct",
                "regime_filter_label",
                "walk_forward_windows",
                "walk_forward_pass_rate_pct",
                "walk_forward_avg_validation_pnl",
                "walk_forward_avg_test_pnl",
                "walk_forward_avg_validation_pf",
                "walk_forward_avg_test_pf",
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
                    f"{row.expectancy:.5f}",
                    f"{row.avg_win:.5f}",
                    f"{row.avg_loss:.5f}",
                    f"{row.payoff_ratio:.5f}",
                    f"{row.avg_hold_bars:.5f}",
                    row.dominant_exit,
                    f"{row.dominant_exit_share_pct:.5f}",
                    row.component_count,
                    f"{row.combo_outperformance_score:.5f}",
                    f"{row.combo_trade_overlap_pct:.5f}",
                    row.best_regime,
                    f"{row.best_regime_pnl:.5f}",
                    row.worst_regime,
                    f"{row.worst_regime_pnl:.5f}",
                    f"{row.dominant_regime_share_pct:.5f}",
                    row.regime_filter_label,
                    row.walk_forward_windows,
                    f"{row.walk_forward_pass_rate_pct:.5f}",
                    f"{row.walk_forward_avg_validation_pnl:.5f}",
                    f"{row.walk_forward_avg_test_pnl:.5f}",
                    f"{row.walk_forward_avg_validation_pf:.5f}",
                    f"{row.walk_forward_avg_test_pf:.5f}",
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
            f"  trade_metrics: expectancy={row.expectancy:.2f} avg_win={row.avg_win:.2f} "
            f"avg_loss={row.avg_loss:.2f} payoff={row.payoff_ratio:.2f} avg_hold={row.avg_hold_bars:.1f}"
        )
        lines.append(
            f"  exits: dominant={row.dominant_exit or 'none'} share={row.dominant_exit_share_pct:.2f}%"
        )
        lines.append(
            f"  regimes: best={row.best_regime or 'none'} pnl={row.best_regime_pnl:.2f} "
            f"worst={row.worst_regime or 'none'} pnl={row.worst_regime_pnl:.2f} "
            f"dominant_share={row.dominant_regime_share_pct:.2f}%"
        )
        if row.regime_filter_label:
            lines.append(f"  regime_filter: {row.regime_filter_label}")
        lines.append(
            f"  walk_forward: windows={row.walk_forward_windows} pass_rate={row.walk_forward_pass_rate_pct:.2f}% "
            f"avg_val_pnl={row.walk_forward_avg_validation_pnl:.2f} avg_test_pnl={row.walk_forward_avg_test_pnl:.2f} "
            f"avg_val_pf={row.walk_forward_avg_validation_pf:.2f} avg_test_pf={row.walk_forward_avg_test_pf:.2f}"
        )
        if row.sparse_strategy:
            lines.append(f"  sparse_strategy: soft_pass_rate={row.walk_forward_soft_pass_rate_pct:.2f}%")
        if row.component_count > 1:
            lines.append(
                f"  combo_validation: components={row.component_count} outperformance={row.combo_outperformance_score:.2f} "
                f"trade_overlap={row.combo_trade_overlap_pct:.2f}%"
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
        if _meets_viability(row, symbol)
    ]
    lines.extend(["", "Recommended active agents"])
    if winners:
        for row in winners[:3]:
            lines.append(f"- {row.name} ({row.description})")
    else:
        lines.append("No candidate met the positive-PnL and PF>=1.0 threshold.")
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, txt_path


def _candidate_failure_reasons(row: CandidateResult, symbol: str) -> list[str]:
    reasons: list[str] = []
    thresholds = _research_thresholds(symbol)
    validation_min = int(thresholds["validation_closed_trades"])
    test_min = int(thresholds["test_closed_trades"])
    wf_pass_min = float(thresholds["walk_forward_min_pass_rate_pct"])
    sparse_strategy = _is_sparse_candidate(row, symbol)
    if sparse_strategy:
        combined_closed = row.validation_closed_trades + row.test_closed_trades
        combined_required = int(thresholds["sparse_combined_closed_trades"])
        if combined_closed < combined_required:
            reasons.append(f"combined validation/test trades too low ({combined_closed} < {combined_required})")
        if (row.validation_pnl + row.test_pnl) <= 0.0:
            reasons.append(f"combined validation/test pnl <= 0 ({row.validation_pnl + row.test_pnl:.2f})")
        if max(row.validation_profit_factor, row.test_profit_factor) < 1.0:
            reasons.append(
                f"combined validation/test PF too low ({max(row.validation_profit_factor, row.test_profit_factor):.2f} < 1.00)"
            )
        wf_pass_min = float(thresholds["sparse_walk_forward_min_pass_rate_pct"])
    else:
        if row.validation_closed_trades < validation_min:
            reasons.append(f"validation trades too low ({row.validation_closed_trades} < {validation_min})")
        if row.test_closed_trades < test_min:
            reasons.append(f"test trades too low ({row.test_closed_trades} < {test_min})")
        if row.validation_pnl <= 0.0:
            reasons.append(f"validation pnl <= 0 ({row.validation_pnl:.2f})")
        if row.test_pnl <= 0.0:
            reasons.append(f"test pnl <= 0 ({row.test_pnl:.2f})")
        if row.validation_profit_factor < 1.0:
            reasons.append(f"validation PF < 1.0 ({row.validation_profit_factor:.2f})")
        if row.test_profit_factor < 1.0:
            reasons.append(f"test PF < 1.0 ({row.test_profit_factor:.2f})")
    if row.walk_forward_windows < 1:
        reasons.append("no walk-forward windows")
    effective_pass_rate = row.walk_forward_soft_pass_rate_pct if sparse_strategy else row.walk_forward_pass_rate_pct
    if effective_pass_rate < wf_pass_min:
        reasons.append(f"walk-forward pass rate too low ({effective_pass_rate:.2f}% < {wf_pass_min:.0f}%)")
    if row.walk_forward_avg_validation_pnl <= 0.0:
        reasons.append(f"walk-forward avg validation pnl <= 0 ({row.walk_forward_avg_validation_pnl:.2f})")
    if row.walk_forward_avg_test_pnl <= 0.0:
        reasons.append(f"walk-forward avg test pnl <= 0 ({row.walk_forward_avg_test_pnl:.2f})")
    if row.component_count > 1 and row.combo_outperformance_score < 0.0:
        reasons.append(f"combo underperformed components ({row.combo_outperformance_score:.2f})")
    if row.component_count > 1 and row.combo_trade_overlap_pct > 80.0:
        reasons.append(f"combo overlap too high ({row.combo_trade_overlap_pct:.2f}% > 80%)")
    return reasons


def _export_viability_autopsy(symbol: str, rows: list[CandidateResult], execution_validation_summary: str) -> Path:
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    path = ARTIFACTS_DIR / f"{_symbol_slug(symbol)}_viability_autopsy.txt"
    ranked = sorted(rows, key=lambda item: (item.realized_pnl, item.profit_factor, item.closed_trades), reverse=True)
    counts: dict[str, int] = {}
    near_misses: list[tuple[CandidateResult, list[str]]] = []
    for row in ranked:
        reasons = _candidate_failure_reasons(row, symbol)
        for reason in reasons:
            counts[reason] = counts.get(reason, 0) + 1
        if reasons:
            near_misses.append((row, reasons))

    lines = [
        f"Viability autopsy: {symbol}",
        f"Execution validation summary: {execution_validation_summary}",
        "",
        "Top blockers",
    ]
    for reason, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:8]:
        lines.append(f"- {reason}: {count}")
    lines.extend(["", "Top near-misses"])
    for row, reasons in near_misses[:8]:
        lines.append(
            f"- {row.name}: pnl={row.realized_pnl:.2f} pf={row.profit_factor:.2f} "
            f"val={row.validation_pnl:.2f}/{row.validation_profit_factor:.2f}/{row.validation_closed_trades} "
            f"test={row.test_pnl:.2f}/{row.test_profit_factor:.2f}/{row.test_closed_trades} "
            f"wf={row.walk_forward_pass_rate_pct:.2f}%"
        )
        lines.append(f"  reasons: {', '.join(reasons)}")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


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
    if _is_stock_symbol(resolved.profile_symbol) and config.symbol_research.mode == "auto" and effective_mode == "seed":
        full_config = copy.deepcopy(config)
        full_config.symbol_research.mode = "full"
        full_mode_variants, full_mode_source, full_mode = _build_symbol_feature_variants(
            full_config,
            resolved.profile_symbol,
            resolved.data_symbol,
        )
        if full_mode == "full" and any(features for features in full_mode_variants.values()):
            feature_variants = full_mode_variants
            data_source = full_mode_source
            effective_mode = full_mode
    default_features = _default_variant_features(feature_variants)
    if not default_features:
        raise RuntimeError(f"No usable feature variants were generated for {resolved.profile_symbol}.")
    singles = _candidate_specs(config, resolved.profile_symbol)
    symbol_slug = _symbol_slug(resolved.profile_symbol)
    results: list[CandidateResult] = []
    explored_entry_exit_specs: list[CandidateSpec] = []
    for variant_label, features in feature_variants.items():
        if not features:
            continue
        variant_specs = [_with_variant_name(spec, variant_label) for spec in singles]
        exit_family_specs = _exit_family_specs(config, resolved.profile_symbol, variant_specs)
        explored_entry_exit_specs.extend(variant_specs + exit_family_specs)
        results.extend(
            _run_candidate_with_splits(
                config,
                features,
                spec,
                "single" if "__exit_" not in spec.name else "entry_exit_family",
                f"{symbol_slug}_{spec.name}_{variant_label}_symbol_candidate",
            )
            for spec in (variant_specs + exit_family_specs)
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
    regime_specs = _regime_improvement_specs(explored_entry_exit_specs + sweep_specs + improvement_specs + second_pass_specs, results)
    if regime_specs:
        results.extend(
            _run_candidate_with_splits(
                config,
                load_execution_features_for_variant(
                    config,
                    resolved.profile_symbol,
                    resolved.data_symbol,
                    spec.variant_label,
                    spec.regime_filter_label,
                )[0],
                spec,
                "regime_improved",
                f"{symbol_slug}_{spec.name}_symbol_candidate",
            )
            for spec in regime_specs
        )
    autopsy_specs = _autopsy_improvement_specs(
        config,
        resolved.profile_symbol,
        explored_entry_exit_specs + sweep_specs + improvement_specs + second_pass_specs + regime_specs,
        results,
    )
    if autopsy_specs:
        results.extend(
            _run_candidate_with_splits(
                config,
                load_execution_features_for_variant(
                    config,
                    resolved.profile_symbol,
                    resolved.data_symbol,
                    spec.variant_label,
                    spec.regime_filter_label,
                )[0],
                spec,
                "autopsy_improved",
                f"{symbol_slug}_{spec.name}_symbol_candidate",
            )
            for spec in autopsy_specs
        )
    near_miss_specs = _near_miss_optimizer_specs(
        resolved.profile_symbol,
        explored_entry_exit_specs + sweep_specs + improvement_specs + second_pass_specs + regime_specs + autopsy_specs,
        results,
    )
    if near_miss_specs:
        results.extend(
            _run_candidate_with_splits(
                config,
                load_execution_features_for_variant(
                    config,
                    resolved.profile_symbol,
                    resolved.data_symbol,
                    spec.variant_label,
                    spec.regime_filter_label,
                )[0],
                spec,
                "near_miss_optimized",
                f"{symbol_slug}_{spec.name}_symbol_candidate",
            )
            for spec in near_miss_specs
        )
    local_optimized_specs, local_optimized_results = _near_miss_local_optimizer(
        config,
        resolved.profile_symbol,
        resolved.data_symbol,
        explored_entry_exit_specs + sweep_specs + improvement_specs + second_pass_specs + regime_specs + autopsy_specs + near_miss_specs,
        results,
        symbol_slug,
    )
    results.extend(local_optimized_results)
    combos = _combined_specs(
        config,
        (
            explored_entry_exit_specs
            + sweep_specs
            + improvement_specs
            + second_pass_specs
            + regime_specs
            + autopsy_specs
            + near_miss_specs
            + local_optimized_specs
        ),
        results,
    )
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
    _annotate_combo_results(results)
    csv_path, txt_path = _export_results(resolved.profile_symbol, resolved.broker_symbol, data_source, results)
    plot_paths = plot_symbol_research(resolved.profile_symbol, results)
    ranked = sorted(
        results,
        key=lambda item: (
            _meets_viability(item, resolved.profile_symbol),
            item.combo_outperformance_score,
            item.walk_forward_pass_rate_pct,
            item.walk_forward_avg_test_pnl,
            item.walk_forward_avg_validation_pnl,
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
        if _meets_viability(row, resolved.profile_symbol)
    ]
    best = viable_ranked[0] if viable_ranked else None
    recommended = [row.name for row in viable_ranked[:3]]
    profile_name = f"symbol::{_symbol_slug(resolved.profile_symbol)}"

    selected_execution_candidates = select_execution_candidates(
        [
            {
                "candidate_name": row.name,
                "symbol": resolved.profile_symbol,
                "code_path": row.code_path,
                "realized_pnl": row.realized_pnl,
                "profit_factor": row.profit_factor,
                "closed_trades": row.closed_trades,
                "payoff_ratio": row.payoff_ratio,
                "validation_pnl": row.validation_pnl,
                "validation_profit_factor": row.validation_profit_factor,
                "validation_closed_trades": row.validation_closed_trades,
                "test_pnl": row.test_pnl,
                "test_profit_factor": row.test_profit_factor,
                "test_closed_trades": row.test_closed_trades,
                "walk_forward_windows": row.walk_forward_windows,
                "walk_forward_pass_rate_pct": row.walk_forward_pass_rate_pct,
                "walk_forward_soft_pass_rate_pct": row.walk_forward_soft_pass_rate_pct,
                "walk_forward_avg_validation_pnl": row.walk_forward_avg_validation_pnl,
                "walk_forward_avg_test_pnl": row.walk_forward_avg_test_pnl,
                "sparse_strategy": row.sparse_strategy,
                "component_count": row.component_count,
                "combo_outperformance_score": row.combo_outperformance_score,
                "combo_trade_overlap_pct": row.combo_trade_overlap_pct,
                "recommended": row.name in recommended,
                "variant_label": row.variant_label,
                "regime_filter_label": row.regime_filter_label,
                "execution_overrides": row.execution_overrides or {},
            }
            for row in results
        ],
        max_candidates=3,
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
        sparse_execution = any(bool(row.get("sparse_strategy")) for row in selected_execution_candidates)
        min_execution_closed_trades = 1 if sparse_execution else 2
        if (
            execution_validation_result.realized_pnl <= 0.0
            or execution_validation_result.profit_factor < 1.0
            or len(execution_validation_result.closed_trades) < min_execution_closed_trades
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
    autopsy_path = _export_viability_autopsy(resolved.profile_symbol, results, execution_validation_summary)
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
    deployment_path = None
    if selected_execution_candidates:
        deployment = build_symbol_deployment(
            profile_name=profile_name,
            symbol=resolved.profile_symbol,
            data_symbol=resolved.data_symbol,
            broker_symbol=resolved.broker_symbol,
            research_run_id=run_id,
            execution_set_id=execution_set_id,
            execution_validation_summary=execution_validation_summary,
            selected_candidates=selected_execution_candidates,
        )
        deployment_path = export_symbol_deployment(deployment)

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
        f"Viability autopsy: {autopsy_path}",
    ]
    if plot_paths:
        lines.append("Plots: " + ", ".join(str(path) for path in plot_paths))
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
            "No viable candidate met the symbol-specific viability rules "
            "(validation/test robustness, walk-forward robustness, and execution consistency)."
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
    if deployment_path is not None:
        lines.append(f"Live deployment: {deployment_path}")
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
    if resolved.profile_symbol.upper() == "US500":
        lines.append("Split ratio: train 60% / validation 20% / test 20% ; walk-forward windows use 45% / 15% / 15%")
    elif _is_crypto_symbol(resolved.profile_symbol):
        lines.append("Split ratio: train 60% / validation 20% / test 20% ; walk-forward windows use 45% / 25% / 20%")
    elif _is_stock_symbol(resolved.profile_symbol):
        lines.append("Split ratio: train 50% / validation 25% / test 25% ; walk-forward windows use 42% / 22% / 22%")
    else:
        lines.append("Split ratio: train 60% / validation 20% / test 20% ; walk-forward windows use 50% / 20% / 20%")
    return lines
