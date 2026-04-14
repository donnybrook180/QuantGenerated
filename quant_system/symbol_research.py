from __future__ import annotations

import asyncio
import csv
import itertools
import copy
import json
import random
import duckdb
from dataclasses import dataclass
from math import isfinite, sqrt
from pathlib import Path
from statistics import mean

from quant_system.ai.models import AgentDescriptor
from quant_system.ai.storage import ExperimentStore
from quant_system.agents.base import Agent
from quant_system.artifacts import research_reports_dir
from quant_system.agents.crypto import (
    CryptoBreakoutReclaimAgent,
    EthLiquiditySweepReversalAgent,
    CryptoMomentumContinuationAgent,
    CryptoShortBreakdownAgent,
    CryptoShortReversionAgent,
    CryptoTrendPullbackAgent,
    CryptoVWAPReversionAgent,
    CryptoVolatilityExpansionAgent,
)
from quant_system.agents.forex import (
    EURUSDLondonFalseBreakReversalAgent,
    EURUSDLondonRangeReclaimAgent,
    EURUSDNYOverlapContinuationAgent,
    EURUSDPostNewsReclaimAgent,
    GBPUSDLondonBreakoutReclaimAgent,
    GBPUSDLondonRangeFadeAgent,
    GBPUSDOverlapImpulseAgent,
    GBPUSDPriorDaySweepReversalAgent,
    ForexBreakoutMomentumAgent,
    ForexCarryTrendAgent,
    ForexRangeReversionAgent,
    ForexShortBreakdownMomentumAgent,
    ForexShortTrendContinuationAgent,
    ForexTrendContinuationAgent,
)
from quant_system.agents.ger40 import (
    GER40EuropeMeanReversionLongAgent,
    GER40EuropeMeanReversionShortAgent,
    GER40FailedBreakoutShortAgent,
    GER40MiddayBreakoutLongAgent,
    GER40MiddayBreakoutShortAgent,
    GER40OpeningDriveFadeLongAgent,
    GER40RangeReclaimLongAgent,
    GER40RangeRejectShortAgent,
)
from quant_system.agents.eu50 import EU50OpenReclaimLongAgent
from quant_system.agents.session import SessionEntryFilterAgent
from quant_system.agents.stocks import (
    EventAwareRiskSentinelAgent,
    StockEventOpenDriveContinuationAgent,
    StockGapFadeAgent,
    StockGapAndGoAgent,
    StockGapOpenReclaimAgent,
    StockNewsMomentumAgent,
    StockPremarketSweepReversalAgent,
    StockPostEarningsDriftAgent,
    StockPowerHourContinuationAgent,
    StockTrendBreakoutAgent,
)
from quant_system.agents.us100 import PriorDayFailedBounceShortAgent
from quant_system.agents.strategies import (
    AfternoonDownsideContinuationAgent,
    FailedBreakdownReclaimLongAgent,
    FailedBounceShortAgent,
    JP225AsiaContinuationLongAgent,
    JP225OpenDriveMeanReversionLongAgent,
    OpeningRangeBreakoutAgent,
    OpeningRangeShortBreakdownAgent,
    VolatilityBreakoutAgent,
    VolatilityShortBreakdownAgent,
)
from quant_system.agents.us500 import (
    US500FlatHighReversalAgent,
    US500FlatTapeMeanReversionAgent,
    US500OvernightGapFadeAgent,
    US500MomentumImpulseAgent,
    US500OpeningDriveShortReclaimAgent,
    US500ShortTrendRejectionAgent,
    US500ShortVWAPRejectAgent,
)
from quant_system.agents.trend import MeanReversionAgent, MomentumConfirmationAgent, RiskSentinelAgent, TrendAgent
from quant_system.agents.xauusd import XAUUSDShortBreakdownAgent, XAUUSDVWAPReclaimAgent, XAUUSDVolatilityBreakoutAgent
from quant_system.catalog_runtime import build_agents_from_catalog_paths
from quant_system.config import SystemConfig
from quant_system.costs import apply_ftmo_cost_profile
from quant_system.data.market_data import DuckDBMarketDataStore
from quant_system.execution.broker import SimulatedBroker
from quant_system.execution.engine import AgentCoordinator, EventDrivenEngine, ExecutionResult
from quant_system.execution_tuning import apply_execution_mode_overrides
from quant_system.integrations.binance_data import BinanceError, BinanceKlineClient
from quant_system.integrations.kraken_data import KrakenError, KrakenOHLCClient
from quant_system.integrations.mt5 import MT5Client, MT5Error
from quant_system.live.deploy import build_symbol_deployment, export_symbol_deployment
from quant_system.models import FeatureVector, MarketBar
from quant_system.monitoring.heartbeat import HeartbeatMonitor
from quant_system.plotting import plot_symbol_research
from quant_system.regime import map_regime_label_to_unified
from quant_system.research.cross_asset import apply_cross_asset_context, supports_cross_asset_context
from quant_system.research.features import build_feature_library
from quant_system.research.funding import apply_broker_funding_context, load_broker_funding_context
from quant_system.risk.limits import RiskManager
from quant_system.symbols import (
    is_crypto_symbol as symbol_is_crypto,
    is_forex_symbol as symbol_is_forex,
    is_metal_symbol as symbol_is_metal,
    is_stock_symbol as symbol_is_stock,
    resolve_symbol_request,
)


class ExternalMarketDataUnavailableError(RuntimeError):
    pass


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
    reference_filter_label: str = ""
    cross_filter_label: str = ""
    allowed_variants: tuple[str, ...] = ()


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
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    payoff_ratio: float = 0.0
    avg_hold_bars: float = 0.0
    best_trade_share_pct: float = 0.0
    equity_new_high_share_pct: float = 0.0
    max_consecutive_losses: int = 0
    equity_quality_score: float = 0.0
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
    best_unified_regime: str = ""
    best_regime_pnl: float = 0.0
    worst_regime: str = ""
    worst_unified_regime: str = ""
    worst_regime_pnl: float = 0.0
    dominant_regime_share_pct: float = 0.0
    regime_trade_count_by_label: str = "{}"
    regime_pnl_by_label: str = "{}"
    regime_pf_by_label: str = "{}"
    regime_win_rate_by_label: str = "{}"
    regime_stability_score: float = 0.0
    regime_loss_ratio: float = 0.0
    regime_filter_label: str = ""
    reference_filter_label: str = ""
    cross_filter_label: str = ""
    broker_swap_available: bool = False
    broker_swap_long: float = 0.0
    broker_swap_short: float = 0.0
    broker_preferred_carry_side: str = ""
    broker_carry_spread: float = 0.0
    mc_simulations: int = 0
    mc_pnl_median: float = 0.0
    mc_pnl_p05: float = 0.0
    mc_pnl_p95: float = 0.0
    mc_max_drawdown_pct_median: float = 0.0
    mc_max_drawdown_pct_p95: float = 0.0
    mc_loss_probability_pct: float = 0.0
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


def _uses_continuous_session_stream(symbol: str) -> bool:
    return _is_crypto_symbol(symbol) or _is_metal_symbol(symbol) or _is_forex_symbol(symbol)


def _should_skip_weekends(symbol: str) -> bool:
    return _uses_continuous_session_stream(symbol)


def _session_allowed_hours(session_label: str) -> set[int] | None:
    if session_label == "europe":
        return set(range(7, 13))
    if session_label == "us":
        return set(range(13, 21))
    if session_label == "overlap":
        return set(range(12, 17))
    if session_label == "power":
        return {18, 19}
    if session_label == "midday":
        return {15, 16, 17}
    return None


def _with_session_gate(agents: list[Agent], session_label: str, symbol: str) -> list[Agent]:
    if not _uses_continuous_session_stream(symbol):
        return agents
    allowed_hours = _session_allowed_hours(session_label)
    if not allowed_hours:
        return agents
    return [*agents, SessionEntryFilterAgent(allowed_hours)]


def _symbol_research_history_days(config: SystemConfig, symbol: str) -> int:
    base_history = max(config.symbol_research.history_days, config.market_data.history_days)
    if symbol.upper() == "ETH":
        return max(base_history, 1460)
    if _is_crypto_symbol(symbol):
        return max(base_history, 365)
    if symbol.upper() == "US500":
        return max(base_history, 365)
    if _is_stock_symbol(symbol):
        return max(base_history, 730)
    if _is_metal_symbol(symbol) or _is_forex_symbol(symbol):
        return max(base_history, 180)
    return max(base_history, 180)


def _research_thresholds(symbol: str) -> dict[str, float | int]:
    if symbol.upper() == "US100":
        return {
            "validation_closed_trades": 3,
            "test_closed_trades": 0,
            "min_profit_factor": 1.0,
            "walk_forward_min_windows": 1,
            "walk_forward_min_pass_rate_pct": 0.0,
            "sparse_max_closed_trades": 20,
            "sparse_min_payoff_ratio": 1.6,
            "sparse_combined_closed_trades": 3,
            "sparse_walk_forward_min_pass_rate_pct": 0.0,
            "core_use_combined_splits": 1,
            "core_combined_closed_trades": 4,
            "core_allow_positive_validation_only": 1,
        }
    if symbol.upper() == "EURUSD":
        return {
            "validation_closed_trades": 1,
            "test_closed_trades": 1,
            "min_profit_factor": 1.0,
            "walk_forward_min_windows": 1,
            "walk_forward_min_pass_rate_pct": 0.0,
            "sparse_max_closed_trades": 18,
            "sparse_min_payoff_ratio": 1.5,
            "sparse_combined_closed_trades": 2,
            "sparse_walk_forward_min_pass_rate_pct": 0.0,
            "core_use_combined_splits": 1,
            "core_combined_closed_trades": 2,
            "core_allow_positive_validation_only": 0,
        }
    if symbol.upper() == "GBPUSD":
        return {
            "validation_closed_trades": 1,
            "test_closed_trades": 0,
            "min_profit_factor": 1.0,
            "walk_forward_min_windows": 1,
            "walk_forward_min_pass_rate_pct": 0.0,
            "sparse_max_closed_trades": 12,
            "sparse_min_payoff_ratio": 1.5,
            "sparse_combined_closed_trades": 0,
            "sparse_walk_forward_min_pass_rate_pct": 0.0,
            "core_use_combined_splits": 1,
            "core_combined_closed_trades": 2,
            "core_allow_positive_validation_only": 0,
        }
    if symbol.upper() == "US500":
        return {
            "validation_closed_trades": 2,
            "test_closed_trades": 1,
            "min_profit_factor": 1.0,
            "walk_forward_min_windows": 1,
            "walk_forward_min_pass_rate_pct": 0.0,
            "sparse_max_closed_trades": 18,
            "sparse_min_payoff_ratio": 1.6,
            "sparse_combined_closed_trades": 2,
            "sparse_walk_forward_min_pass_rate_pct": 0.0,
            "core_use_combined_splits": 1,
            "core_combined_closed_trades": 3,
            "core_allow_positive_validation_only": 1,
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


def _metric_map_from_row(row: CandidateResult | dict[str, object], field_name: str) -> dict[str, float]:
    raw = getattr(row, field_name) if isinstance(row, CandidateResult) else row.get(field_name, "{}")
    if isinstance(raw, dict):
        payload = raw
    else:
        try:
            payload = json.loads(str(raw or "{}"))
        except json.JSONDecodeError:
            return {}
    result: dict[str, float] = {}
    for key, value in payload.items():
        try:
            result[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return result


def _meets_regime_specialist_viability(row: CandidateResult | dict[str, object], symbol: str) -> bool:
    if _meets_viability(row, symbol):
        return False
    thresholds = _research_thresholds(symbol)
    realized_pnl = float(row.realized_pnl if isinstance(row, CandidateResult) else row.get("realized_pnl", 0.0))
    profit_factor = float(row.profit_factor if isinstance(row, CandidateResult) else row.get("profit_factor", 0.0))
    validation_pnl = float(row.validation_pnl if isinstance(row, CandidateResult) else row.get("validation_pnl", 0.0))
    test_pnl = float(row.test_pnl if isinstance(row, CandidateResult) else row.get("test_pnl", 0.0))
    validation_profit_factor = float(
        row.validation_profit_factor if isinstance(row, CandidateResult) else row.get("validation_profit_factor", 0.0)
    )
    test_profit_factor = float(row.test_profit_factor if isinstance(row, CandidateResult) else row.get("test_profit_factor", 0.0))
    walk_forward_windows = int(row.walk_forward_windows if isinstance(row, CandidateResult) else row.get("walk_forward_windows", 0))
    walk_forward_pass_rate_pct = float(
        row.walk_forward_pass_rate_pct if isinstance(row, CandidateResult) else row.get("walk_forward_pass_rate_pct", 0.0)
    )
    walk_forward_soft_pass_rate_pct = float(
        row.walk_forward_soft_pass_rate_pct if isinstance(row, CandidateResult) else row.get("walk_forward_soft_pass_rate_pct", 0.0)
    )
    best_regime = str(row.best_regime if isinstance(row, CandidateResult) else row.get("best_regime", "") or "")
    best_regime_pnl = float(row.best_regime_pnl if isinstance(row, CandidateResult) else row.get("best_regime_pnl", 0.0))
    regime_stability_score = float(
        row.regime_stability_score if isinstance(row, CandidateResult) else row.get("regime_stability_score", 0.0)
    )
    regime_loss_ratio = float(
        row.regime_loss_ratio if isinstance(row, CandidateResult) else row.get("regime_loss_ratio", 999.0)
    )
    regime_trade_counts = _metric_map_from_row(row, "regime_trade_count_by_label")
    regime_pf_by_label = _metric_map_from_row(row, "regime_pf_by_label")
    best_regime_trade_count = int(regime_trade_counts.get(best_regime, 0.0))
    best_regime_pf = float(regime_pf_by_label.get(best_regime, 0.0))
    effective_pass_rate = max(walk_forward_pass_rate_pct, walk_forward_soft_pass_rate_pct)
    best_trade_share_pct = float(row.best_trade_share_pct if isinstance(row, CandidateResult) else row.get("best_trade_share_pct", 0.0))
    equity_quality_score = float(
        row.equity_quality_score if isinstance(row, CandidateResult) else row.get("equity_quality_score", 0.0)
    )
    combined_closed_trades = int(
        (row.validation_closed_trades + row.test_closed_trades)
        if isinstance(row, CandidateResult)
        else (row.get("validation_closed_trades", 0) or 0) + (row.get("test_closed_trades", 0) or 0)
    )
    if symbol.upper() == "GBPUSD":
        regime_filter_label = str(
            row.regime_filter_label if isinstance(row, CandidateResult) else row.get("regime_filter_label", "") or ""
        )
        payoff_ratio = float(row.payoff_ratio if isinstance(row, CandidateResult) else row.get("payoff_ratio", 0.0))
        closed_trades = int(row.closed_trades if isinstance(row, CandidateResult) else row.get("closed_trades", 0))
        if (
            best_regime == "trend_flat_vol_mid"
            and regime_filter_label == "trend_flat_vol_mid"
            and realized_pnl > 0.0
            and profit_factor >= 1.2
            and payoff_ratio >= 1.75
            and closed_trades >= 3
            and best_regime_trade_count >= 3
            and best_regime_pnl > 0.0
            and best_regime_pf >= 1.2
            and regime_stability_score >= 0.9
            and regime_loss_ratio <= 0.25
            and equity_quality_score >= 0.3
            and walk_forward_windows >= 1
            and combined_closed_trades == 0
        ):
            return True
    return (
        realized_pnl > 0.0
        and profit_factor >= float(thresholds["min_profit_factor"])
        and bool(best_regime)
        and best_regime_pnl > 0.0
        and best_regime_trade_count >= max(2, int(thresholds["sparse_combined_closed_trades"]))
        and combined_closed_trades >= max(2, int(thresholds["sparse_combined_closed_trades"]))
        and best_regime_pf >= float(thresholds["min_profit_factor"])
        and (validation_pnl > 0.0 or test_pnl > 0.0)
        and max(validation_profit_factor, test_profit_factor, best_regime_pf) >= float(thresholds["min_profit_factor"])
        and walk_forward_windows >= int(thresholds["walk_forward_min_windows"])
        and effective_pass_rate >= float(thresholds["sparse_walk_forward_min_pass_rate_pct"])
        and regime_stability_score >= 0.65
        and regime_loss_ratio <= 0.75
        and equity_quality_score >= 0.35
        and best_trade_share_pct <= 80.0
        and _meets_monte_carlo_viability(row)
    )


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
    best_regime = str(row.best_regime if isinstance(row, CandidateResult) else row.get("best_regime", "") or "")
    best_regime_pnl = float(row.best_regime_pnl if isinstance(row, CandidateResult) else row.get("best_regime_pnl", 0.0))
    regime_stability_score = float(
        row.regime_stability_score if isinstance(row, CandidateResult) else row.get("regime_stability_score", 0.0)
    )
    regime_loss_ratio = float(
        row.regime_loss_ratio if isinstance(row, CandidateResult) else row.get("regime_loss_ratio", 999.0)
    )
    best_trade_share_pct = float(row.best_trade_share_pct if isinstance(row, CandidateResult) else row.get("best_trade_share_pct", 0.0))
    equity_quality_score = float(
        row.equity_quality_score if isinstance(row, CandidateResult) else row.get("equity_quality_score", 0.0)
    )
    sparse_strategy = _is_sparse_candidate(row, symbol)
    core_use_combined_splits = bool(thresholds.get("core_use_combined_splits", 0))
    core_combined_closed_trades = int(thresholds.get("core_combined_closed_trades", 0) or 0)
    core_allow_positive_validation_only = bool(thresholds.get("core_allow_positive_validation_only", 0))
    sparse_combined_closed_trades = validation_closed_trades + test_closed_trades
    sparse_pass_rate_threshold = (
        float(thresholds["sparse_walk_forward_min_pass_rate_pct"]) if sparse_strategy else float(thresholds["walk_forward_min_pass_rate_pct"])
    )
    sparse_window_pass_rate = float(
        row.walk_forward_soft_pass_rate_pct if isinstance(row, CandidateResult) else row.get("walk_forward_soft_pass_rate_pct", 0.0)
    )
    if sparse_strategy:
        split_trade_requirement_met = sparse_combined_closed_trades >= int(thresholds["sparse_combined_closed_trades"])
        split_pnl_requirement_met = (validation_pnl + test_pnl) > 0.0
        split_pf_requirement_met = max(validation_profit_factor, test_profit_factor) >= float(thresholds["min_profit_factor"])
    elif core_use_combined_splits:
        combined_closed = validation_closed_trades + test_closed_trades
        combined_pnl = validation_pnl + test_pnl
        split_trade_requirement_met = combined_closed >= max(1, core_combined_closed_trades)
        split_pnl_requirement_met = (
            validation_pnl > 0.0 if core_allow_positive_validation_only else combined_pnl > 0.0
        )
        split_pf_requirement_met = max(validation_profit_factor, test_profit_factor, profit_factor) >= float(
            thresholds["min_profit_factor"]
        )
    else:
        split_trade_requirement_met = validation_closed_trades >= int(thresholds["validation_closed_trades"]) and test_closed_trades >= int(thresholds["test_closed_trades"])
        split_pnl_requirement_met = validation_pnl > 0.0 and test_pnl > 0.0
        split_pf_requirement_met = validation_profit_factor >= float(thresholds["min_profit_factor"]) and test_profit_factor >= float(thresholds["min_profit_factor"])
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
        and (
            walk_forward_avg_validation_pnl > 0.0
            and (walk_forward_avg_test_pnl > 0.0 or core_allow_positive_validation_only)
        )
        and bool(best_regime)
        and best_regime_pnl > 0.0
        and regime_stability_score >= 0.50
        and regime_loss_ratio <= 1.25
        and equity_quality_score >= 0.45
        and best_trade_share_pct <= 70.0
        and (
            component_count <= 1
            or (combo_outperformance_score >= 0.0 and combo_trade_overlap_pct <= 80.0)
        )
        and _meets_monte_carlo_viability(row)
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
    apply_execution_mode_overrides(tuned)
    return tuned


def _configure_symbol_execution(config: SystemConfig, symbol: str, broker_symbol: str | None = None) -> None:
    upper = symbol.upper()
    if upper == "USDJPY":
        # USDJPY research can explode in notional terms because forex uses 100k contract size.
        # Keep research on mini-size here so viability is driven by signal quality, not oversized exposure.
        config.execution.order_size = min(config.execution.order_size, 0.01)
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
    apply_ftmo_cost_profile(config, symbol, broker_symbol)
    apply_execution_mode_overrides(config)


def _load_symbol_features(config: SystemConfig, data_symbol: str) -> tuple[list[FeatureVector], str]:
    broker_symbol = config.symbol_research.broker_symbol.strip() or None
    return _load_symbol_features_variant(config, data_symbol, config.market_data.multiplier, config.market_data.timespan, broker_symbol)


def _research_variant_plan(profile_symbol: str, mode: str) -> tuple[list[tuple[str, int, str]], tuple[str, ...], bool]:
    if profile_symbol.upper() in {"TSLA", "NVDA"}:
        if mode == "seed":
            return [("5m", 5, "minute"), ("15m", 15, "minute")], ("open", "power"), True
        return [("5m", 5, "minute"), ("15m", 15, "minute")], ("us", "open", "power", "midday"), True
    if profile_symbol.upper() == "GBPUSD":
        return [("15m", 15, "minute"), ("30m", 30, "minute")], ("europe", "overlap"), True
    if profile_symbol.upper() == "GER40":
        if mode == "seed":
            return [("5m", 5, "minute"), ("15m", 15, "minute")], ("open", "europe"), True
        return [("5m", 5, "minute"), ("15m", 15, "minute")], ("open", "europe", "midday"), True
    if profile_symbol.upper() == "ETH":
        if mode == "seed":
            return [("5m", 5, "minute"), ("15m", 15, "minute"), ("30m", 30, "minute"), ("1h", 60, "minute")], ("europe", "overlap", "us"), True
        return [("5m", 5, "minute"), ("15m", 15, "minute"), ("30m", 30, "minute"), ("1h", 60, "minute")], ("europe", "overlap", "us"), True
    if _is_crypto_symbol(profile_symbol):
        if mode == "seed":
            return [("5m", 5, "minute"), ("1h", 60, "minute")], ("all", "europe"), True
        return [("5m", 5, "minute"), ("15m", 15, "minute"), ("30m", 30, "minute"), ("1h", 60, "minute")], ("all", "europe", "us", "overlap"), True
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


def _cache_symbol_candidates(data_symbol: str) -> list[str]:
    return [data_symbol]


def _aggregate_minute_bars(bars: list[MarketBar], target_multiplier: int, source_multiplier: int) -> list[MarketBar]:
    if not bars or target_multiplier <= source_multiplier or target_multiplier % source_multiplier != 0:
        return []
    ratio = target_multiplier // source_multiplier
    aggregated: list[MarketBar] = []
    bucket: list[MarketBar] = []
    current_bucket_key: tuple[int, int, int, int] | None = None

    def flush_bucket(items: list[MarketBar], bucket_key: tuple[int, int, int, int] | None) -> None:
        if len(items) != ratio or bucket_key is None:
            return
        bucket_minute = bucket_key[3] % 60
        aggregated.append(
            MarketBar(
                timestamp=items[0].timestamp.replace(minute=bucket_minute, second=0, microsecond=0),
                symbol=items[0].symbol,
                open=items[0].open,
                high=max(item.high for item in items),
                low=min(item.low for item in items),
                close=items[-1].close,
                volume=sum(item.volume for item in items),
            )
        )

    for bar in bars:
        minute_bucket = (bar.timestamp.minute // target_multiplier) * target_multiplier
        bucket_key = (bar.timestamp.year, bar.timestamp.month, bar.timestamp.day, (bar.timestamp.hour * 60) + minute_bucket)
        if current_bucket_key != bucket_key:
            flush_bucket(bucket, current_bucket_key)
            bucket = [bar]
            current_bucket_key = bucket_key
        else:
            bucket.append(bar)

    flush_bucket(bucket, current_bucket_key)
    return aggregated


def _has_plausible_price_scale(data_symbol: str, bars: list[MarketBar]) -> bool:
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


def _load_crypto_network_bars(config: SystemConfig, data_symbol: str, multiplier: int, timespan: str) -> tuple[list[MarketBar], str]:
    errors: list[str] = []
    try:
        bars = BinanceKlineClient(
            symbol=data_symbol,
            multiplier=multiplier,
            timespan=timespan,
            history_days=config.market_data.history_days,
        ).fetch_bars()
        return bars, "binance"
    except BinanceError as exc:
        errors.append(str(exc))

    try:
        bars = KrakenOHLCClient(
            symbol=data_symbol,
            multiplier=multiplier,
            timespan=timespan,
            history_days=config.market_data.history_days,
        ).fetch_bars()
        return bars, "kraken"
    except KrakenError as exc:
        errors.append(str(exc))

    raise RuntimeError("; ".join(errors))


def _cache_bar_limit(config: SystemConfig, multiplier: int, timespan: str) -> int:
    if timespan == "minute":
        minutes = max(config.market_data.history_days * 24 * 60, multiplier)
        return max(50_000, int(minutes / max(multiplier, 1)) + 512)
    return 50_000


def _mt5_bar_limit(config: SystemConfig, symbol: str, multiplier: int, timespan: str) -> int:
    if timespan != "minute":
        return 0
    trading_minutes_per_day = 24 * 60 if _uses_continuous_session_stream(symbol) else 8 * 60
    estimated = int((config.market_data.history_days * trading_minutes_per_day) / max(multiplier, 1))
    return max(2_500, estimated + 512)


def _normalize_bars_symbol(bars: list[MarketBar], target_symbol: str) -> list[MarketBar]:
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


def _load_mt5_network_bars(
    config: SystemConfig,
    profile_symbol: str,
    data_symbol: str,
    broker_symbol: str,
    multiplier: int,
    timespan: str,
) -> tuple[list[MarketBar], str]:
    if timespan != "minute":
        raise MT5Error(f"Unsupported MT5 timespan {timespan}.")
    timeframe_map = {1: "M1", 5: "M5", 15: "M15", 30: "M30", 60: "H1"}
    timeframe = timeframe_map.get(multiplier)
    if timeframe is None:
        raise MT5Error(f"Unsupported MT5 minute multiplier {multiplier}.")
    mt5_config = copy.deepcopy(config.mt5)
    mt5_config.symbol = broker_symbol
    mt5_config.timeframe = timeframe
    mt5_config.history_bars = _mt5_bar_limit(config, profile_symbol, multiplier, timespan)
    client = MT5Client(mt5_config)
    try:
        client.initialize()
        bars = client.fetch_bars(mt5_config.history_bars)
    finally:
        try:
            client.shutdown()
        except Exception:
            pass
    normalized = _normalize_bars_symbol(bars, data_symbol)
    if not normalized:
        raise MT5Error(f"No MT5 bars returned for {broker_symbol}/{timeframe}.")
    return normalized, "mt5"


def _detect_research_mode(config: SystemConfig, profile_symbol: str, data_symbol: str) -> str:
    requested_mode = config.symbol_research.mode
    if requested_mode in {"seed", "full"}:
        return requested_mode
    symbol_specific = _is_crypto_symbol(profile_symbol) or _is_metal_symbol(profile_symbol) or _is_forex_symbol(profile_symbol) or _is_stock_symbol(profile_symbol)
    if not symbol_specific:
        return "full"

    store = DuckDBMarketDataStore(config.mt5.database_path, read_only=True)
    timeframe_specs, _, _ = _research_variant_plan(profile_symbol, "full")
    for _, multiplier, timespan in timeframe_specs:
        scoped_timeframe = _variant_timeframe_key(data_symbol, multiplier, timespan)
        has_sufficient_cache = False
        for cache_symbol in _cache_symbol_candidates(data_symbol):
            scoped = _variant_timeframe_key(cache_symbol, multiplier, timespan)
            bars = store.load_bars(cache_symbol, scoped, 2_500)
            if len(bars) >= 500:
                has_sufficient_cache = True
                break
            if timespan == "minute" and multiplier in {15, 30}:
                base_bars = store.load_bars(cache_symbol, _variant_timeframe_key(cache_symbol, 5, "minute"), 50_000)
                aggregated = _aggregate_minute_bars(base_bars, multiplier, 5) if base_bars else []
                if len(aggregated) >= 500:
                    has_sufficient_cache = True
                    break
        if not has_sufficient_cache:
            return "seed"
    return "full"


def _load_symbol_features_variant(
    config: SystemConfig,
    data_symbol: str,
    multiplier: int,
    timespan: str,
    broker_symbol: str | None = None,
    profile_symbol: str | None = None,
) -> tuple[list[FeatureVector], str]:
    cache_store = DuckDBMarketDataStore(config.mt5.database_path, read_only=True)
    timeframe = f"{multiplier}_{timespan}"
    scoped_timeframe = f"symbol_research_{_symbol_slug(data_symbol)}_{timeframe}"
    cache_limit = _cache_bar_limit(config, multiplier, timespan)
    base_cache_limit = _cache_bar_limit(config, 5, "minute")
    resolved_profile_symbol = profile_symbol or data_symbol
    source_preference = config.symbol_research.source_preference

    def _try_mt5_fetch() -> tuple[list[FeatureVector], str] | None:
        if not broker_symbol or source_preference in {"external_only", "cache_only"}:
            return None
        bars, source = _load_mt5_network_bars(
            config,
            resolved_profile_symbol,
            data_symbol,
            broker_symbol,
            multiplier,
            timespan,
        )
        if not _has_plausible_price_scale(data_symbol, bars):
            raise RuntimeError(f"Fetched implausible MT5 price scale for {data_symbol}; refusing to persist suspect bars.")
        try:
            DuckDBMarketDataStore(config.mt5.database_path).upsert_bars(bars, timeframe=scoped_timeframe, source=source)
        except (duckdb.IOException, RuntimeError):
            return _build_features_with_events(config, data_symbol, bars), f"{source}_direct"
        persisted = cache_store.load_bars(data_symbol, scoped_timeframe, len(bars))
        if persisted:
            return _build_features_with_events(config, data_symbol, persisted), source
        return _build_features_with_events(config, data_symbol, bars), f"{source}_direct"

    if config.market_data.fetch_policy in {"cache_first", "cache_only"}:
        for cache_symbol in _cache_symbol_candidates(data_symbol):
            cached = cache_store.load_bars(cache_symbol, _variant_timeframe_key(cache_symbol, multiplier, timespan), cache_limit)
            if cached and _has_plausible_price_scale(data_symbol, cached):
                return _build_features_with_events(config, data_symbol, cached), "duckdb_cache"
            if timespan == "minute" and multiplier in {15, 30, 60}:
                base_cached = cache_store.load_bars(
                    cache_symbol, _variant_timeframe_key(cache_symbol, 5, "minute"), base_cache_limit
                )
                if base_cached and _has_plausible_price_scale(data_symbol, base_cached):
                    aggregated = _aggregate_minute_bars(base_cached, multiplier, 5)
                    if aggregated:
                        return _build_features_with_events(config, data_symbol, aggregated), "duckdb_cache_aggregated"
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
        if _is_crypto_symbol(data_symbol):
            bars, source = _load_crypto_network_bars(config, data_symbol, multiplier, timespan)
        else:
            mt5_result = _try_mt5_fetch()
            if mt5_result is None:
                raise ExternalMarketDataUnavailableError(f"No MT5 broker fetch path available for {broker_symbol or data_symbol}")
            return mt5_result
        if not _has_plausible_price_scale(data_symbol, bars):
            raise RuntimeError(f"Fetched implausible price scale for {data_symbol}; refusing to persist suspect bars.")
        try:
            DuckDBMarketDataStore(config.mt5.database_path).upsert_bars(bars, timeframe=scoped_timeframe, source=source)
        except (duckdb.IOException, RuntimeError):
            return _build_features_with_events(config, data_symbol, bars), f"{source}_direct"
        persisted = cache_store.load_bars(data_symbol, scoped_timeframe, len(bars))
        if persisted:
            return _build_features_with_events(config, data_symbol, persisted), source
        return _build_features_with_events(config, data_symbol, bars), f"{source}_direct"
    except (MT5Error, ExternalMarketDataUnavailableError):
        if source_preference not in {"broker_only", "external_only"} and broker_symbol:
            try:
                mt5_result = _try_mt5_fetch()
                if mt5_result is not None:
                    return mt5_result
            except MT5Error as exc:
                mt5_errors.append(str(exc))
        for cache_symbol in _cache_symbol_candidates(data_symbol):
            cached = cache_store.load_bars(cache_symbol, _variant_timeframe_key(cache_symbol, multiplier, timespan), cache_limit)
            if cached and _has_plausible_price_scale(data_symbol, cached):
                return _build_features_with_events(config, data_symbol, cached), "duckdb_cache"
            if timespan == "minute" and multiplier in {15, 30, 60}:
                base_cached = cache_store.load_bars(
                    cache_symbol, _variant_timeframe_key(cache_symbol, 5, "minute"), base_cache_limit
                )
                if base_cached and _has_plausible_price_scale(data_symbol, base_cached):
                    aggregated = _aggregate_minute_bars(base_cached, multiplier, 5)
                    if aggregated:
                        return _build_features_with_events(config, data_symbol, aggregated), "duckdb_cache_aggregated"
        if mt5_errors:
            raise RuntimeError("; ".join(mt5_errors)) from None
        raise


def _build_features_with_events(config: SystemConfig, data_symbol: str, bars: list[MarketBar]) -> list[FeatureVector]:
    if not bars:
        return []
    funding_context = load_broker_funding_context(config, data_symbol, config.mt5.symbol)
    if not _is_stock_symbol(data_symbol):
        features = build_feature_library(bars)
        features = apply_broker_funding_context(features, funding_context)
        if supports_cross_asset_context(data_symbol):
            multiplier, timespan = _infer_bars_timeframe(bars)
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
    except RuntimeError as exc:
        _ = exc
        features = build_feature_library(bars)
    else:
        features = build_feature_library(bars, event_flags)
    features = apply_broker_funding_context(features, funding_context)
    if supports_cross_asset_context(data_symbol):
        multiplier, timespan = _infer_bars_timeframe(bars)
        features = apply_cross_asset_context(
            features,
            config.mt5.database_path,
            data_symbol,
            multiplier,
            timespan,
        )
    return features


def _infer_bars_timeframe(bars: list[MarketBar]) -> tuple[int, str]:
    if len(bars) < 2:
        return 5, "minute"
    delta_seconds = int((bars[1].timestamp - bars[0].timestamp).total_seconds())
    if delta_seconds <= 0:
        return 5, "minute"
    return max(delta_seconds // 60, 1), "minute"


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


def _filter_features_by_cross_context(features: list[FeatureVector], cross_filter_label: str) -> list[FeatureVector]:
    if not cross_filter_label:
        return features
    label = cross_filter_label.strip().lower()
    if label == "risk_on_confirm":
        return [feature for feature in features if feature.values.get("cross_risk_on_score", 0.0) > 0.0]
    if label == "us100_breakout_confirm":
        return [
            feature
            for feature in features
            if feature.values.get("cross_us100_breakout_confirm", 0.0) > 0.0
            and feature.values.get("cross_us100_reentry_warning", 0.0) <= 0.0
            and feature.values.get("cross_risk_on_score", 0.0) > -0.15
        ]
    if label == "risk_off_confirm":
        return [feature for feature in features if feature.values.get("cross_risk_on_score", 0.0) < 0.0]
    if label == "gold_tailwind_confirm":
        return [feature for feature in features if feature.values.get("cross_gold_macro_tailwind_score", 0.0) > 0.0]
    return features


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
            timeframe_features, data_source = _load_symbol_features_variant(
                config,
                data_symbol,
                multiplier,
                timespan,
                config.symbol_research.broker_symbol.strip() or None,
                profile_symbol,
            )
            if weekday_only:
                timeframe_features = _filter_weekday_features(timeframe_features)
            data_sources.append(data_source)
            for session_name in session_names:
                filtered = _filter_features_by_session(timeframe_features, session_name)
                if len(filtered) < 50:
                    continue
                variants[f"{timeframe_label}_{session_name}"] = filtered
        resolved_source = "mt5" if "mt5" in data_sources else ("duckdb_cache" if "duckdb_cache" in data_sources else (data_sources[0] if data_sources else "unknown"))
        return variants or {"default": []}, resolved_source, mode

    variants: dict[str, list[FeatureVector]] = {}
    data_sources: list[str] = []
    timeframe_specs, session_names, weekday_only = _research_variant_plan(profile_symbol, mode)

    for timeframe_label, multiplier, timespan in timeframe_specs:
        timeframe_features, data_source = _load_symbol_features_variant(
            config,
            data_symbol,
            multiplier,
            timespan,
            config.symbol_research.broker_symbol.strip() or None,
            profile_symbol,
        )
        if weekday_only:
            timeframe_features = _filter_weekday_features(timeframe_features)
        data_sources.append(data_source)
        for session_name in session_names:
            filtered = timeframe_features if _uses_continuous_session_stream(profile_symbol) else _filter_features_by_session(timeframe_features, session_name)
            if len(filtered) < 50:
                continue
            variants[f"{timeframe_label}_{session_name}"] = filtered

    resolved_source = "mt5" if "mt5" in data_sources else ("duckdb_cache" if "duckdb_cache" in data_sources else (data_sources[0] if data_sources else "unknown"))
    return variants or {"default": []}, resolved_source, mode


def load_execution_features_for_variant(
    config: SystemConfig,
    profile_symbol: str,
    data_symbol: str,
    variant_label: str,
    regime_filter_label: str = "",
    cross_filter_label: str = "",
) -> tuple[list[FeatureVector], str]:
    if not variant_label or variant_label == "default":
        features, data_source = _load_symbol_features(config, data_symbol)
        features = _filter_features_by_cross_context(features, cross_filter_label)
        return _filter_features_by_regime(features, regime_filter_label), data_source

    timeframe_label, _, session_label = variant_label.partition("_")
    if timeframe_label.endswith("m") and timeframe_label[:-1].isdigit():
        multiplier = int(timeframe_label[:-1])
        timespan = "minute"
    elif timeframe_label.endswith("h") and timeframe_label[:-1].isdigit():
        multiplier = int(timeframe_label[:-1]) * 60
        timespan = "minute"
    else:
        features, data_source = _load_symbol_features(config, data_symbol)
        features = _filter_features_by_cross_context(features, cross_filter_label)
        return _filter_features_by_regime(features, regime_filter_label), data_source

    features, data_source = _load_symbol_features_variant(
        config,
        data_symbol,
        multiplier,
        timespan,
        config.symbol_research.broker_symbol.strip() or None,
        profile_symbol,
    )
    if _should_skip_weekends(profile_symbol) or _is_stock_symbol(profile_symbol):
        features = _filter_weekday_features(features)
    if not _uses_continuous_session_stream(profile_symbol):
        features = _filter_features_by_session(features, session_label or "all")
    features = _filter_features_by_cross_context(features, cross_filter_label)
    return _filter_features_by_regime(features, regime_filter_label), data_source


def _evaluate_execution_candidate_set(
    config: SystemConfig,
    profile_symbol: str,
    data_symbol: str,
    selected_candidates: list[dict[str, object]],
) -> tuple[ExecutionResult, str, str]:
    return _run_candidate_bundle(config, profile_symbol, data_symbol, selected_candidates)


def _execution_path_metrics(result: ExecutionResult) -> dict[str, float]:
    pnls = list(result.closed_trade_pnls)
    if not pnls:
        return {
            "best_trade_share_pct": 100.0,
            "equity_new_high_share_pct": 0.0,
            "time_under_water_pct": 100.0,
            "max_consecutive_losses": 0.0,
            "equity_quality_score": 0.0,
        }
    wins = [pnl for pnl in pnls if pnl > 0.0]
    gross_profit = sum(wins)
    best_trade_share_pct = (max(wins) / gross_profit * 100.0) if wins and gross_profit > 0.0 else 100.0
    equity = 0.0
    peak = 0.0
    new_high_count = 0
    underwater_count = 0
    current_loss_streak = 0
    max_consecutive_losses = 0
    for pnl in pnls:
        equity += pnl
        if equity >= peak:
            peak = equity
            new_high_count += 1
        else:
            underwater_count += 1
        if pnl < 0.0:
            current_loss_streak += 1
            max_consecutive_losses = max(max_consecutive_losses, current_loss_streak)
        else:
            current_loss_streak = 0
    trade_count = len(pnls)
    equity_new_high_share_pct = (new_high_count / trade_count * 100.0) if trade_count > 0 else 0.0
    time_under_water_pct = (underwater_count / trade_count * 100.0) if trade_count > 0 else 100.0
    quality_components = [
        min(max(result.profit_factor, 0.0), 3.0) / 3.0,
        min(max(equity_new_high_share_pct, 0.0), 100.0) / 100.0,
        1.0 - min(best_trade_share_pct, 100.0) / 100.0,
        1.0 - min(time_under_water_pct, 100.0) / 100.0,
        1.0 - (max_consecutive_losses / trade_count if trade_count > 0 else 1.0),
    ]
    return {
        "best_trade_share_pct": best_trade_share_pct,
        "equity_new_high_share_pct": equity_new_high_share_pct,
        "time_under_water_pct": time_under_water_pct,
        "max_consecutive_losses": float(max_consecutive_losses),
        "equity_quality_score": sum(quality_components) / float(len(quality_components)) if quality_components else 0.0,
    }


def _execution_result_score(result: ExecutionResult, candidate_set: list[dict[str, object]]) -> tuple[float, float, float, float, int]:
    metrics = _execution_path_metrics(result)
    distinct_regimes = len({str(row.get("best_regime", "") or "") for row in candidate_set if str(row.get("best_regime", "") or "")})
    specialist_count = sum(1 for row in candidate_set if str(row.get("promotion_tier", "")) == "specialist")
    score = (
        result.realized_pnl * 1.0
        + max(result.profit_factor - 1.0, 0.0) * 250.0
        + metrics["equity_quality_score"] * 200.0
        + metrics["equity_new_high_share_pct"] * 2.0
        - metrics["time_under_water_pct"] * 1.5
        - metrics["best_trade_share_pct"] * 1.0
        - metrics["max_consecutive_losses"] * 15.0
        + distinct_regimes * 40.0
        - specialist_count * 10.0
    )
    return (
        score,
        metrics["equity_quality_score"],
        result.realized_pnl,
        result.profit_factor,
        len(result.closed_trades),
    )


def _derive_symbol_status(
    selected_execution_candidates: list[dict[str, object]],
    execution_validation_summary: str,
) -> str:
    if not selected_execution_candidates:
        return "research_only"
    tiers = {str(row.get("promotion_tier", "") or "") for row in selected_execution_candidates}
    if "accepted_with_reduced_risk" in execution_validation_summary:
        return "reduced_risk_only"
    if tiers and tiers <= {"specialist"}:
        return "reduced_risk_only"
    return "live_ready"


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


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    variance = sum((value - avg) ** 2 for value in values) / float(len(values) - 1)
    return sqrt(max(variance, 0.0))


def _sharpe_ratio(pnls: list[float]) -> float:
    if len(pnls) < 2:
        return 0.0
    deviation = _stddev(pnls)
    if deviation <= 0.0:
        return 0.0
    value = mean(pnls) / deviation
    return value if isfinite(value) else 0.0


def _sortino_ratio(pnls: list[float]) -> float:
    if len(pnls) < 2:
        return 0.0
    downside = [value for value in pnls if value < 0.0]
    if not downside:
        return 999.0 if mean(pnls) > 0.0 else 0.0
    downside_deviation = sqrt(sum(value**2 for value in downside) / float(len(downside)))
    if downside_deviation <= 0.0:
        return 0.0
    value = mean(pnls) / downside_deviation
    return value if isfinite(value) else 0.0


def _calmar_ratio(realized_pnl: float, max_drawdown: float, initial_cash: float) -> float:
    if initial_cash <= 0.0 or max_drawdown <= 0.0:
        return 999.0 if realized_pnl > 0.0 else 0.0
    total_return_pct = realized_pnl / initial_cash
    value = total_return_pct / max_drawdown
    return value if isfinite(value) else 0.0


def _meets_monte_carlo_viability(row: CandidateResult | dict[str, object]) -> bool:
    mc_simulations = int(row.mc_simulations if isinstance(row, CandidateResult) else row.get("mc_simulations", 0) or 0)
    mc_pnl_p05 = float(row.mc_pnl_p05 if isinstance(row, CandidateResult) else row.get("mc_pnl_p05", 0.0) or 0.0)
    mc_loss_probability_pct = float(
        row.mc_loss_probability_pct if isinstance(row, CandidateResult) else row.get("mc_loss_probability_pct", 0.0) or 0.0
    )
    return mc_simulations > 0 and mc_pnl_p05 > 0.0 and mc_loss_probability_pct <= 10.0


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = min(max(quantile, 0.0), 1.0) * float(len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _max_drawdown_from_pnls(pnls: list[float], initial_cash: float) -> float:
    if initial_cash <= 0.0:
        return 0.0
    equity = initial_cash
    peak = initial_cash
    max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        if peak > 0.0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return max_drawdown


def _monte_carlo_summary(pnls: list[float], initial_cash: float, simulations: int = 500) -> dict[str, float]:
    if not pnls:
        return {
            "mc_simulations": 0.0,
            "mc_pnl_median": 0.0,
            "mc_pnl_p05": 0.0,
            "mc_pnl_p95": 0.0,
            "mc_max_drawdown_pct_median": 0.0,
            "mc_max_drawdown_pct_p95": 0.0,
            "mc_loss_probability_pct": 0.0,
        }
    rng = random.Random(7)
    pnl_totals: list[float] = []
    max_drawdowns_pct: list[float] = []
    loss_count = 0
    trade_count = len(pnls)
    for _ in range(simulations):
        sampled = [pnls[rng.randrange(trade_count)] for _ in range(trade_count)]
        total_pnl = float(sum(sampled))
        pnl_totals.append(total_pnl)
        max_drawdowns_pct.append(_max_drawdown_from_pnls(sampled, initial_cash) * 100.0)
        if total_pnl < 0.0:
            loss_count += 1
    return {
        "mc_simulations": float(simulations),
        "mc_pnl_median": _percentile(pnl_totals, 0.50),
        "mc_pnl_p05": _percentile(pnl_totals, 0.05),
        "mc_pnl_p95": _percentile(pnl_totals, 0.95),
        "mc_max_drawdown_pct_median": _percentile(max_drawdowns_pct, 0.50),
        "mc_max_drawdown_pct_p95": _percentile(max_drawdowns_pct, 0.95),
        "mc_loss_probability_pct": (loss_count / float(simulations)) * 100.0,
    }


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
        session_label = str(row.get("session_label", "") or "")
        regime_filter_label = str(row.get("regime_filter_label", "") or "")
        features, data_source = load_execution_features_for_variant(
            candidate_config,
            profile_symbol,
            data_symbol,
            variant_label,
            regime_filter_label,
            str(row.get("cross_filter_label", "") or ""),
        )
        prebuilt_agents = row.get("agents")
        if isinstance(prebuilt_agents, list) and prebuilt_agents:
            agents = copy.deepcopy(prebuilt_agents)
        else:
            agents = build_agents_from_catalog_paths([str(row["code_path"])], candidate_config)
        symbol = features[0].symbol if features else ""
        agents = _with_session_gate(agents, session_label, symbol)
        engine = _build_engine(candidate_config, agents)
        results.append(asyncio.run(engine.run(features, sleep_seconds=0.0)))
        data_sources.append(data_source)
        label = variant_label or "default"
        if regime_filter_label:
            label = f"{label}|{regime_filter_label}"
        cross_filter_label = str(row.get("cross_filter_label", "") or "")
        if cross_filter_label:
            label = f"{label}|{cross_filter_label}"
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
        if "ETH" in upper:
            return [
                CandidateSpec(
                    name="crypto_vwap_reversion",
                    description="ETH selective VWAP/z-score mean reversion",
                    agents=[
                        CryptoVWAPReversionAgent(
                            z_score_entry=1.2,
                            min_relative_volume=0.55,
                            max_trend_strength=0.0015,
                            min_atr_proxy=0.0007,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.crypto.CryptoVWAPReversionAgent",
                ),
                CandidateSpec(
                    name="eth_liquidity_sweep_reversal",
                    description="ETH selective liquidity sweep reversal",
                    agents=[
                        EthLiquiditySweepReversalAgent(
                            sweep_margin=0.0003,
                            min_relative_volume=0.55,
                            min_atr_proxy=0.0005,
                            max_trend_strength=0.0020,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.crypto.EthLiquiditySweepReversalAgent",
                ),
                CandidateSpec(
                    name="crypto_short_reversion",
                    description="ETH short mean reversion in downtrend",
                    agents=[
                        CryptoShortReversionAgent(
                            lookback=12,
                            min_negative_trend=-0.0006,
                            z_score_low=0.2,
                            z_score_high=3.2,
                            min_relative_volume=0.50,
                            min_atr_proxy=0.0006,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.crypto.CryptoShortReversionAgent",
                ),
                CandidateSpec(
                    name="crypto_short_reversion_late_europe",
                    description="ETH short mean reversion focused on late Europe handoff",
                    agents=[
                        CryptoShortReversionAgent(
                            lookback=10,
                            min_negative_trend=-0.0006,
                            z_score_low=0.1,
                            z_score_high=3.2,
                            min_relative_volume=0.50,
                            min_atr_proxy=0.0006,
                        ),
                        SessionEntryFilterAgent({11, 12}),
                        risk,
                    ],
                    code_path="quant_system.agents.crypto.CryptoShortReversionAgent",
                    allowed_variants=("15m_europe",),
                ),
                CandidateSpec(
                    name="crypto_short_reversion_europe_noon",
                    description="ETH short mean reversion limited to Europe noon reversals",
                    agents=[
                        CryptoShortReversionAgent(
                            lookback=10,
                            min_negative_trend=-0.0006,
                            z_score_low=0.1,
                            z_score_high=3.2,
                            min_relative_volume=0.50,
                            min_atr_proxy=0.0006,
                        ),
                        SessionEntryFilterAgent({12}),
                        risk,
                    ],
                    code_path="quant_system.agents.crypto.CryptoShortReversionAgent",
                    allowed_variants=("15m_europe",),
                ),
                CandidateSpec(
                    name="crypto_vwap_reversion_us_core",
                    description="ETH VWAP reversion focused on core US reversal hours",
                    agents=[
                        CryptoVWAPReversionAgent(
                            z_score_entry=1.2,
                            min_relative_volume=0.55,
                            max_trend_strength=0.0015,
                            min_atr_proxy=0.0007,
                        ),
                        SessionEntryFilterAgent({14, 16, 17}),
                        risk,
                    ],
                    code_path="quant_system.agents.crypto.CryptoVWAPReversionAgent",
                    allowed_variants=("15m_us",),
                ),
                CandidateSpec(
                    name="crypto_vwap_reversion_us_hour17",
                    description="ETH VWAP reversion limited to the 30m US 17:00 bar",
                    agents=[
                        CryptoVWAPReversionAgent(
                            z_score_entry=1.2,
                            min_relative_volume=0.55,
                            max_trend_strength=0.0015,
                            min_atr_proxy=0.0007,
                        ),
                        SessionEntryFilterAgent({17}),
                        risk,
                    ],
                    code_path="quant_system.agents.crypto.CryptoVWAPReversionAgent",
                    allowed_variants=("30m_us",),
                ),
            ]
        specs = [
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
        if "BTC" in upper:
            specs.extend(
                [
                    CandidateSpec(
                        name="btc_trend_pullback_high_beta",
                        description="BTC trend pullback continuation in stronger trend regimes",
                        agents=[
                            CryptoTrendPullbackAgent(
                                lookback=10,
                                min_trend_strength=0.00045,
                                min_momentum_20=0.00035,
                                z_score_low=-2.4,
                                z_score_high=0.25,
                                min_relative_volume=0.55,
                                min_atr_proxy=0.0009,
                            ),
                            risk,
                        ],
                        code_path="quant_system.agents.crypto.CryptoTrendPullbackAgent",
                        regime_filter_label="trend_up_vol_mid",
                        execution_overrides={
                            "structure_exit_bars": 0,
                            "stale_breakout_bars": 10,
                            "max_holding_bars": 42,
                        },
                    ),
                    CandidateSpec(
                        name="btc_breakout_reclaim_trend",
                        description="BTC breakout reclaim continuation for trend-up volatility regimes",
                        agents=[
                            CryptoBreakoutReclaimAgent(
                                lookback=14,
                                reclaim_buffer=0.9955,
                                min_trend_strength=0.00025,
                                min_momentum_20=0.00030,
                                min_relative_volume=0.60,
                                min_atr_proxy=0.0009,
                            ),
                            risk,
                        ],
                        code_path="quant_system.agents.crypto.CryptoBreakoutReclaimAgent",
                        regime_filter_label="trend_up_vol_high",
                        execution_overrides={
                            "structure_exit_bars": 0,
                            "stale_breakout_bars": 9,
                            "max_holding_bars": 40,
                        },
                    ),
                    CandidateSpec(
                        name="btc_vwap_reversion_flat_mid",
                        description="BTC VWAP mean reversion for flat mid-volatility tape",
                        agents=[
                            CryptoVWAPReversionAgent(
                                z_score_entry=1.35,
                                min_relative_volume=0.55,
                                max_trend_strength=0.0012,
                                min_atr_proxy=0.0007,
                            ),
                            risk,
                        ],
                        code_path="quant_system.agents.crypto.CryptoVWAPReversionAgent",
                        regime_filter_label="trend_flat_vol_mid",
                        execution_overrides={
                            "structure_exit_bars": 1,
                            "stale_breakout_bars": 4,
                            "max_holding_bars": 18,
                            "take_profit_atr_multiple": 1.35,
                            "trailing_stop_atr_multiple": 0.45,
                        },
                    ),
                    CandidateSpec(
                        name="btc_liquidity_sweep_reversal",
                        description="BTC liquidity sweep reversal after failed intraday extension",
                        agents=[
                            EthLiquiditySweepReversalAgent(
                                lookback=20,
                                sweep_margin=0.00045,
                                min_relative_volume=0.58,
                                min_atr_proxy=0.0007,
                                max_trend_strength=0.0014,
                            ),
                            risk,
                        ],
                        code_path="quant_system.agents.crypto.EthLiquiditySweepReversalAgent",
                        allowed_variants=("15m_overlap", "15m_us", "1h_us"),
                        regime_filter_label="trend_flat_vol_mid",
                        execution_overrides={
                            "structure_exit_bars": 1,
                            "stale_breakout_bars": 5,
                            "max_holding_bars": 16,
                            "take_profit_atr_multiple": 1.45,
                            "trailing_stop_atr_multiple": 0.50,
                        },
                    ),
                    CandidateSpec(
                        name="btc_momentum_continuation_overlap",
                        description="BTC momentum continuation with denser participation threshold",
                        agents=[
                            CryptoMomentumContinuationAgent(
                                min_momentum_5=0.00018,
                                min_momentum_20=0.00028,
                                min_trend_strength=0.00012,
                                min_relative_volume=0.50,
                                min_atr_proxy=0.0006,
                            ),
                            risk,
                        ],
                        code_path="quant_system.agents.crypto.CryptoMomentumContinuationAgent",
                        allowed_variants=("15m_overlap", "15m_us"),
                        regime_filter_label="trend_up_vol_mid",
                        execution_overrides={
                            "structure_exit_bars": 0,
                            "stale_breakout_bars": 8,
                            "max_holding_bars": 28,
                        },
                    ),
                ]
            )
        return specs
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
                name="xauusd_volatility_breakout_cross_tailwind",
                description="XAUUSD-tuned volatility breakout with cross-asset gold tailwind confirmation",
                agents=[XAUUSDVolatilityBreakoutAgent(lookback=max(6, config.agents.mean_reversion_window)), risk],
                code_path="quant_system.agents.xauusd.XAUUSDVolatilityBreakoutAgent",
                cross_filter_label="gold_tailwind_confirm",
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
        specs.append(
            CandidateSpec(
                name="xauusd_vwap_reclaim",
                description="XAUUSD VWAP reclaim after oversold washout",
                agents=[XAUUSDVWAPReclaimAgent(), risk],
                code_path="quant_system.agents.xauusd.XAUUSDVWAPReclaimAgent",
            )
        )
        return specs
    if upper.endswith("USD") or upper.endswith("JPY") or upper.startswith("EUR") or upper.startswith("GBP") or upper.startswith("AUD"):
        if upper == "EURUSD":
            return [
                CandidateSpec(
                    name="eurusd_carry_trend",
                    description="EURUSD carry-style continuation using USD and yield tailwind proxies",
                    agents=[
                        ForexCarryTrendAgent(
                            lookback=24,
                            min_pair_macro_bias=0.00016,
                            min_trend_strength=0.00012,
                            min_momentum_20=0.00010,
                            min_relative_volume=0.58,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.forex.ForexCarryTrendAgent",
                    allowed_variants=("30m_europe", "30m_overlap", "30m_us"),
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 8,
                        "max_holding_bars": 28,
                        "take_profit_atr_multiple": 2.25,
                        "trailing_stop_atr_multiple": 0.9,
                    },
                ),
                CandidateSpec(
                    name="forex_breakout_momentum",
                    description="EURUSD breakout momentum baseline",
                    agents=[ForexBreakoutMomentumAgent(), risk],
                    code_path="quant_system.agents.forex.ForexBreakoutMomentumAgent",
                ),
                CandidateSpec(
                    name="forex_short_breakdown_momentum",
                    description="EURUSD short breakdown momentum baseline",
                    agents=[ForexShortBreakdownMomentumAgent(), risk],
                    code_path="quant_system.agents.forex.ForexShortBreakdownMomentumAgent",
                ),
                CandidateSpec(
                    name="eurusd_london_range_reclaim",
                    description="EURUSD London range reclaim",
                    agents=[
                        EURUSDLondonRangeReclaimAgent(
                            max_abs_trend_strength=0.00075,
                            min_distance_to_vwap=0.00016,
                            min_relative_volume=0.62,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.forex.EURUSDLondonRangeReclaimAgent",
                    execution_overrides={
                        "structure_exit_bars": 1,
                        "stale_breakout_bars": 5,
                        "max_holding_bars": 14,
                        "take_profit_atr_multiple": 1.3,
                        "trailing_stop_atr_multiple": 0.55,
                    },
                ),
                CandidateSpec(
                    name="eurusd_london_false_break_reversal",
                    description="EURUSD London false-break reversal around prior-day and overnight levels",
                    agents=[
                        EURUSDLondonFalseBreakReversalAgent(
                            breakout_margin=0.00014,
                            reclaim_margin=0.00004,
                            max_abs_trend_strength=0.00095,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.forex.EURUSDLondonFalseBreakReversalAgent",
                    regime_filter_label="trend_flat_vol_mid",
                    execution_overrides={
                        "structure_exit_bars": 1,
                        "stale_breakout_bars": 4,
                        "max_holding_bars": 12,
                        "take_profit_atr_multiple": 1.45,
                        "trailing_stop_atr_multiple": 0.5,
                    },
                ),
                CandidateSpec(
                    name="eurusd_ny_overlap_continuation",
                    description="EURUSD NY-overlap trend continuation",
                    agents=[
                        EURUSDNYOverlapContinuationAgent(
                            min_trend_strength=0.0002,
                            min_momentum_20=0.00016,
                            min_relative_volume=0.72,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.forex.EURUSDNYOverlapContinuationAgent",
                    allowed_variants=("15m_overlap",),
                    regime_filter_label="trend_flat_vol_mid",
                    execution_overrides={
                        "structure_exit_bars": 2,
                        "stale_breakout_bars": 4,
                        "max_holding_bars": 18,
                        "take_profit_atr_multiple": 1.8,
                        "trailing_stop_atr_multiple": 0.7,
                    },
                ),
                CandidateSpec(
                    name="eurusd_ny_overlap_continuation_selective",
                    description="EURUSD NY-overlap trend continuation selective",
                    agents=[
                        EURUSDNYOverlapContinuationAgent(
                            min_trend_strength=0.00024,
                            min_momentum_20=0.00018,
                            min_relative_volume=0.78,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.forex.EURUSDNYOverlapContinuationAgent",
                    allowed_variants=("15m_overlap",),
                    regime_filter_label="trend_flat_vol_mid",
                    execution_overrides={
                        "structure_exit_bars": 2,
                        "stale_breakout_bars": 3,
                        "max_holding_bars": 16,
                        "take_profit_atr_multiple": 1.65,
                        "trailing_stop_atr_multiple": 0.65,
                    },
                ),
                CandidateSpec(
                    name="eurusd_post_news_reclaim",
                    description="EURUSD post-news VWAP reclaim",
                    agents=[
                        EURUSDPostNewsReclaimAgent(
                            min_relative_volume=0.78,
                            max_abs_trend_strength=0.0013,
                            reclaim_margin=0.00005,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.forex.EURUSDPostNewsReclaimAgent",
                    regime_filter_label="trend_flat_vol_high",
                    execution_overrides={
                        "structure_exit_bars": 1,
                        "stale_breakout_bars": 3,
                        "max_holding_bars": 10,
                        "take_profit_atr_multiple": 1.25,
                        "trailing_stop_atr_multiple": 0.45,
                    },
                ),
            ]
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
                    allowed_variants=("15m_europe",),
                ),
                CandidateSpec(
                    name="forex_short_breakdown_momentum",
                    description="GBPUSD short breakdown momentum baseline",
                    agents=[
                        ForexShortBreakdownMomentumAgent(
                            lookback=16,
                            min_atr_proxy=0.00028,
                            min_momentum_5=-0.00018,
                            min_momentum_20=-0.00022,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.forex.ForexShortBreakdownMomentumAgent",
                    allowed_variants=("15m_europe",),
                ),
                CandidateSpec(
                    name="forex_range_reversion",
                    description="GBPUSD range reversion baseline",
                    agents=[
                        ForexRangeReversionAgent(
                            lookback=16,
                            min_z_score=-1.15,
                            max_trend_strength=0.00075,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.forex.ForexRangeReversionAgent",
                    allowed_variants=("15m_europe", "30m_europe"),
                ),
                CandidateSpec(
                    name="gbpusd_range_reversion_overlap",
                    description="GBPUSD overlap-session range reversion extension",
                    agents=[
                        ForexRangeReversionAgent(
                            lookback=14,
                            min_z_score=-1.05,
                            max_trend_strength=0.0009,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.forex.ForexRangeReversionAgent",
                    allowed_variants=("15m_overlap",),
                    regime_filter_label="trend_flat_vol_mid",
                    execution_overrides={
                        "structure_exit_bars": 1,
                        "stale_breakout_bars": 2,
                        "max_holding_bars": 8,
                        "take_profit_atr_multiple": 1.1,
                        "trailing_stop_atr_multiple": 0.4,
                    },
                ),
                CandidateSpec(
                    name="gbpusd_london_range_fade",
                    description="GBPUSD London range fade around VWAP and session extremes",
                    agents=[
                        GBPUSDLondonRangeFadeAgent(
                            max_abs_trend_strength=0.0011,
                            min_relative_volume=0.58,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.forex.GBPUSDLondonRangeFadeAgent",
                    regime_filter_label="trend_flat_vol_mid",
                    allowed_variants=("15m_europe", "15m_overlap", "30m_europe"),
                    execution_overrides={
                        "structure_exit_bars": 1,
                        "stale_breakout_bars": 5,
                        "max_holding_bars": 14,
                        "take_profit_atr_multiple": 1.35,
                        "trailing_stop_atr_multiple": 0.5,
                    },
                ),
                CandidateSpec(
                    name="gbpusd_london_breakout_reclaim",
                    description="GBPUSD London breakout reclaim continuation",
                    agents=[
                        GBPUSDLondonBreakoutReclaimAgent(
                            min_trend_strength=0.00014,
                            min_relative_volume=0.62,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.forex.GBPUSDLondonBreakoutReclaimAgent",
                    allowed_variants=("15m_europe", "15m_overlap", "30m_europe"),
                    execution_overrides={
                        "structure_exit_bars": 1,
                        "stale_breakout_bars": 5,
                        "max_holding_bars": 18,
                        "take_profit_atr_multiple": 1.8,
                        "trailing_stop_atr_multiple": 0.7,
                    },
                ),
                CandidateSpec(
                    name="gbpusd_overlap_impulse",
                    description="GBPUSD London/NY overlap impulse continuation",
                    agents=[
                        GBPUSDOverlapImpulseAgent(
                            min_trend_strength=0.00014,
                            min_relative_volume=0.64,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.forex.GBPUSDOverlapImpulseAgent",
                    allowed_variants=("15m_overlap", "30m_overlap"),
                    execution_overrides={
                        "structure_exit_bars": 1,
                        "stale_breakout_bars": 4,
                        "max_holding_bars": 16,
                        "take_profit_atr_multiple": 1.7,
                        "trailing_stop_atr_multiple": 0.65,
                    },
                ),
                CandidateSpec(
                    name="gbpusd_prior_day_sweep_reversal",
                    description="GBPUSD prior-day sweep reversal in flat or transition regimes",
                    agents=[
                        GBPUSDPriorDaySweepReversalAgent(
                            max_abs_trend_strength=0.0012,
                            min_relative_volume=0.6,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.forex.GBPUSDPriorDaySweepReversalAgent",
                    regime_filter_label="trend_flat_vol_mid",
                    allowed_variants=("15m_europe", "15m_overlap", "30m_europe"),
                    execution_overrides={
                        "structure_exit_bars": 1,
                        "stale_breakout_bars": 4,
                        "max_holding_bars": 12,
                        "take_profit_atr_multiple": 1.4,
                        "trailing_stop_atr_multiple": 0.52,
                    },
                ),
            ]
        return [
            CandidateSpec(
                name="forex_carry_trend",
                description="Forex carry-style continuation using USD and yield tailwind proxies",
                agents=[ForexCarryTrendAgent(), risk],
                code_path="quant_system.agents.forex.ForexCarryTrendAgent",
                allowed_variants=("30m_europe", "30m_overlap", "30m_us"),
                execution_overrides={
                    "structure_exit_bars": 0,
                    "stale_breakout_bars": 8,
                    "max_holding_bars": 28,
                    "take_profit_atr_multiple": 2.2,
                    "trailing_stop_atr_multiple": 0.9,
                },
            ),
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
    if upper == "EU50":
        specs.extend(
            [
                CandidateSpec(
                    name="eu50_range_reject_short",
                    description="EU50 Europe-session failed range reclaim short",
                    agents=[GER40RangeRejectShortAgent(), risk],
                    code_path="quant_system.agents.ger40.GER40RangeRejectShortAgent",
                    allowed_variants=("15m_europe", "30m_europe"),
                    execution_overrides={
                        "structure_exit_bars": 1,
                        "stale_breakout_bars": 4,
                        "max_holding_bars": 14,
                        "take_profit_atr_multiple": 1.4,
                        "trailing_stop_atr_multiple": 0.55,
                    },
                ),
                CandidateSpec(
                    name="eu50_failed_breakout_short",
                    description="EU50 Europe-session failed upside breakout short",
                    agents=[GER40FailedBreakoutShortAgent(), risk],
                    code_path="quant_system.agents.ger40.GER40FailedBreakoutShortAgent",
                    allowed_variants=("15m_europe", "30m_europe"),
                    execution_overrides={
                        "structure_exit_bars": 1,
                        "stale_breakout_bars": 4,
                        "max_holding_bars": 12,
                        "take_profit_atr_multiple": 1.3,
                        "trailing_stop_atr_multiple": 0.5,
                    },
                ),
                CandidateSpec(
                    name="eu50_opening_drive_fade_long",
                    description="EU50 Europe open drive fade back into range",
                    agents=[GER40OpeningDriveFadeLongAgent(), risk],
                    code_path="quant_system.agents.ger40.GER40OpeningDriveFadeLongAgent",
                    allowed_variants=("15m_europe", "30m_europe"),
                    execution_overrides={
                        "structure_exit_bars": 1,
                        "stale_breakout_bars": 5,
                        "max_holding_bars": 14,
                        "take_profit_atr_multiple": 1.25,
                        "trailing_stop_atr_multiple": 0.45,
                    },
                ),
                CandidateSpec(
                    name="eu50_range_reclaim_long",
                    description="EU50 Europe-session failed breakdown reclaim long",
                    agents=[GER40RangeReclaimLongAgent(), risk],
                    code_path="quant_system.agents.ger40.GER40RangeReclaimLongAgent",
                    allowed_variants=("15m_europe", "30m_europe"),
                    execution_overrides={
                        "structure_exit_bars": 1,
                        "stale_breakout_bars": 5,
                        "max_holding_bars": 14,
                        "take_profit_atr_multiple": 1.3,
                        "trailing_stop_atr_multiple": 0.5,
                    },
                ),
                CandidateSpec(
                    name="eu50_midday_breakout_long",
                    description="EU50 midday continuation breakout long",
                    agents=[GER40MiddayBreakoutLongAgent(), risk],
                    code_path="quant_system.agents.ger40.GER40MiddayBreakoutLongAgent",
                    allowed_variants=("15m_europe", "30m_europe"),
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 6,
                        "max_holding_bars": 18,
                        "take_profit_atr_multiple": 1.8,
                        "trailing_stop_atr_multiple": 0.7,
                    },
                ),
                CandidateSpec(
                    name="eu50_midday_breakout_short",
                    description="EU50 midday continuation breakout short",
                    agents=[GER40MiddayBreakoutShortAgent(), risk],
                    code_path="quant_system.agents.ger40.GER40MiddayBreakoutShortAgent",
                    allowed_variants=("15m_europe", "30m_europe"),
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 6,
                        "max_holding_bars": 18,
                        "take_profit_atr_multiple": 1.8,
                        "trailing_stop_atr_multiple": 0.7,
                    },
                ),
                CandidateSpec(
                    name="eu50_mean_reversion_down_mid",
                    description="EU50 Europe-session mean reversion after downside extension in down-mid regimes",
                    agents=[MeanReversionAgent(max(config.agents.mean_reversion_window - 2, 4), config.agents.mean_reversion_threshold * 0.8), risk],
                    code_path="quant_system.agents.trend.MeanReversionAgent",
                    regime_filter_label="trend_down_vol_mid",
                    allowed_variants=("15m_europe", "30m_europe"),
                    execution_overrides={
                        "structure_exit_bars": 1,
                        "stale_breakout_bars": 3,
                        "max_holding_bars": 10,
                        "take_profit_atr_multiple": 1.1,
                        "trailing_stop_atr_multiple": 0.4,
                    },
                ),
                CandidateSpec(
                    name="eu50_open_reclaim_long",
                    description="EU50 Europe-open reclaim long after downside washout",
                    agents=[EU50OpenReclaimLongAgent(), risk],
                    code_path="quant_system.agents.eu50.EU50OpenReclaimLongAgent",
                    allowed_variants=("15m_europe", "30m_europe"),
                    execution_overrides={
                        "structure_exit_bars": 1,
                        "stale_breakout_bars": 4,
                        "max_holding_bars": 12,
                        "take_profit_atr_multiple": 1.25,
                        "trailing_stop_atr_multiple": 0.45,
                    },
                ),
            ]
        )
    if upper == "JP225":
        specs.extend(
            [
                CandidateSpec(
                    name="jp225_open_drive_mean_reversion_long",
                    description="JP225 open-drive mean reversion long after failed downside extension",
                    agents=[JP225OpenDriveMeanReversionLongAgent(), risk],
                    code_path="quant_system.agents.strategies.JP225OpenDriveMeanReversionLongAgent",
                ),
                CandidateSpec(
                    name="jp225_asia_continuation_long",
                    description="JP225 Asia-session continuation long after controlled upside expansion",
                    agents=[JP225AsiaContinuationLongAgent(), risk],
                    code_path="quant_system.agents.strategies.JP225AsiaContinuationLongAgent",
                ),
                CandidateSpec(
                    name="jp225_failed_breakdown_reclaim_core_hours",
                    description="JP225 failed breakdown reclaim long limited to the strongest upside reversal hours",
                    agents=[
                        FailedBreakdownReclaimLongAgent(),
                        SessionEntryFilterAgent({0, 1, 2, 8, 9, 10}),
                        risk,
                    ],
                    code_path="quant_system.agents.strategies.FailedBreakdownReclaimLongAgent",
                ),
                CandidateSpec(
                    name="jp225_failed_breakdown_reclaim_asia_hours",
                    description="JP225 failed breakdown reclaim long focused on Asia-hours reversal windows",
                    agents=[
                        FailedBreakdownReclaimLongAgent(),
                        SessionEntryFilterAgent({0, 1, 2, 8}),
                        risk,
                    ],
                    code_path="quant_system.agents.strategies.FailedBreakdownReclaimLongAgent",
                ),
                CandidateSpec(
                    name="jp225_volatility_breakout_core_hours",
                    description="JP225 long volatility breakout limited to the strongest historical upside entry hours",
                    agents=[
                        VolatilityBreakoutAgent(lookback=max(8, config.agents.mean_reversion_window)),
                        SessionEntryFilterAgent({0, 1, 2, 8, 10, 11}),
                        risk,
                    ],
                    code_path="quant_system.agents.strategies.VolatilityBreakoutAgent",
                ),
                CandidateSpec(
                    name="jp225_volatility_breakout_asia_hours",
                    description="JP225 long volatility breakout focused on the strongest Asia-hours upside continuation windows",
                    agents=[
                        VolatilityBreakoutAgent(lookback=max(8, config.agents.mean_reversion_window)),
                        SessionEntryFilterAgent({0, 1, 2, 8}),
                        risk,
                    ],
                    code_path="quant_system.agents.strategies.VolatilityBreakoutAgent",
                ),
                CandidateSpec(
                    name="jp225_volatility_short_breakdown_core_hours",
                    description="JP225 short volatility breakdown limited to the strongest historical entry hours",
                    agents=[
                        VolatilityShortBreakdownAgent(lookback=max(8, config.agents.mean_reversion_window)),
                        SessionEntryFilterAgent({3, 4, 9, 17, 20}),
                        risk,
                    ],
                    code_path="quant_system.agents.strategies.VolatilityShortBreakdownAgent",
                ),
                CandidateSpec(
                    name="jp225_volatility_short_breakdown_asia_hours",
                    description="JP225 short volatility breakdown focused on the strongest Asia-Europe handoff hours",
                    agents=[
                        VolatilityShortBreakdownAgent(lookback=max(8, config.agents.mean_reversion_window)),
                        SessionEntryFilterAgent({3, 4, 9}),
                        risk,
                    ],
                    code_path="quant_system.agents.strategies.VolatilityShortBreakdownAgent",
                ),
            ]
        )
    if _is_stock_symbol(data_symbol):
        stock_risk = EventAwareRiskSentinelAgent(allow_high_impact_day=False)
        stock_event_risk = EventAwareRiskSentinelAgent(allow_high_impact_day=True, allow_event_blackout=True)
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
                agents=[StockNewsMomentumAgent(), stock_event_risk, risk],
                code_path="quant_system.agents.stocks.StockNewsMomentumAgent",
            ),
            CandidateSpec(
                name="stock_event_open_drive_continuation",
                description="Stock event-day continuation anchored to premarket and opening-drive structure",
                agents=[StockEventOpenDriveContinuationAgent(), stock_event_risk, risk],
                code_path="quant_system.agents.stocks.StockEventOpenDriveContinuationAgent",
            ),
            CandidateSpec(
                name="stock_post_earnings_drift",
                description="Stock post-earnings drift continuation after the open",
                agents=[StockPostEarningsDriftAgent(), stock_event_risk, risk],
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
                name="stock_gap_open_reclaim",
                description="Stock gap continuation after reclaiming premarket structure",
                agents=[StockGapOpenReclaimAgent(), stock_risk, risk],
                code_path="quant_system.agents.stocks.StockGapOpenReclaimAgent",
            ),
            CandidateSpec(
                name="stock_premarket_sweep_reversal",
                description="Stock premarket sweep reversal after failed opening extension",
                agents=[StockPremarketSweepReversalAgent(), stock_risk, risk],
                code_path="quant_system.agents.stocks.StockPremarketSweepReversalAgent",
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


def _score_result(
    name: str,
    description: str,
    archetype: str,
    code_path: str,
    result: ExecutionResult,
    initial_cash: float,
) -> CandidateResult:
    wins = [trade.pnl for trade in result.closed_trades if trade.pnl > 0]
    losses = [trade.pnl for trade in result.closed_trades if trade.pnl < 0]
    pnls = [trade.pnl for trade in result.closed_trades]
    expectancy = mean(result.closed_trade_pnls) if result.closed_trade_pnls else 0.0
    sharpe_ratio = _sharpe_ratio(result.closed_trade_pnls)
    sortino_ratio = _sortino_ratio(result.closed_trade_pnls)
    calmar_ratio = _calmar_ratio(result.realized_pnl, result.max_drawdown, initial_cash)
    monte_carlo = _monte_carlo_summary(result.closed_trade_pnls, initial_cash)
    avg_win = mean(wins) if wins else 0.0
    avg_loss = mean(losses) if losses else 0.0
    payoff_ratio = (avg_win / abs(avg_loss)) if avg_loss < 0 else (999.0 if avg_win > 0 else 0.0)
    avg_hold_bars = mean([trade.hold_bars for trade in result.closed_trades]) if result.closed_trades else 0.0
    gross_profit = sum(wins)
    best_trade_share_pct = (max(wins) / gross_profit * 100.0) if wins and gross_profit > 0.0 else 0.0
    equity = 0.0
    peak = 0.0
    new_high_count = 0
    current_loss_streak = 0
    max_consecutive_losses = 0
    for pnl in pnls:
        equity += pnl
        if equity >= peak:
            peak = equity
            new_high_count += 1
        if pnl < 0.0:
            current_loss_streak += 1
            max_consecutive_losses = max(max_consecutive_losses, current_loss_streak)
        else:
            current_loss_streak = 0
    trade_count = len(result.closed_trades)
    equity_new_high_share_pct = (new_high_count / trade_count * 100.0) if trade_count > 0 else 0.0
    quality_components = [
        min(max(payoff_ratio, 0.0), 3.0) / 3.0,
        min(max(equity_new_high_share_pct, 0.0), 100.0) / 100.0,
        1.0 - min(best_trade_share_pct, 100.0) / 100.0,
        1.0 - (max_consecutive_losses / trade_count if trade_count > 0 else 1.0),
    ]
    equity_quality_score = sum(quality_components) / float(len(quality_components)) if quality_components else 0.0
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
        sharpe_ratio=sharpe_ratio,
        sortino_ratio=sortino_ratio,
        calmar_ratio=calmar_ratio,
        avg_win=avg_win,
        avg_loss=avg_loss,
        payoff_ratio=payoff_ratio,
        avg_hold_bars=avg_hold_bars,
        best_trade_share_pct=best_trade_share_pct,
        equity_new_high_share_pct=equity_new_high_share_pct,
        max_consecutive_losses=max_consecutive_losses,
        equity_quality_score=equity_quality_score,
        dominant_exit=dominant_exit,
        dominant_exit_share_pct=dominant_exit_share_pct,
        mc_simulations=int(monte_carlo["mc_simulations"]),
        mc_pnl_median=monte_carlo["mc_pnl_median"],
        mc_pnl_p05=monte_carlo["mc_pnl_p05"],
        mc_pnl_p95=monte_carlo["mc_pnl_p95"],
        mc_max_drawdown_pct_median=monte_carlo["mc_max_drawdown_pct_median"],
        mc_max_drawdown_pct_p95=monte_carlo["mc_max_drawdown_pct_p95"],
        mc_loss_probability_pct=monte_carlo["mc_loss_probability_pct"],
    )


def _run_candidate(
    config: SystemConfig,
    features: list[FeatureVector],
    spec: CandidateSpec,
    archetype: str,
    artifact_prefix: str,
) -> CandidateResult:
    from quant_system.research_artifacts import export_closed_trade_artifacts

    candidate_config = _with_execution_overrides(config, spec.execution_overrides)
    symbol = features[0].symbol if features else ""
    agents = _with_session_gate(copy.deepcopy(spec.agents), spec.session_label, symbol)
    engine = _build_engine(candidate_config, agents)
    result = asyncio.run(engine.run(features, sleep_seconds=0.0))
    trades_path, analysis_path = export_closed_trade_artifacts(
        result.closed_trades,
        result.realized_pnl,
        artifact_prefix,
    )
    scored = _score_result(spec.name, spec.description, archetype, spec.code_path, result, candidate_config.execution.initial_cash)
    scored.trade_log_path = str(trades_path)
    scored.trade_analysis_path = str(analysis_path)
    scored.variant_label = spec.variant_label
    scored.timeframe_label = spec.timeframe_label
    scored.session_label = spec.session_label
    scored.regime_filter_label = spec.regime_filter_label
    scored.cross_filter_label = spec.cross_filter_label
    scored.execution_overrides = copy.deepcopy(spec.execution_overrides)
    _annotate_regime_metrics(scored, features, result.closed_trades)
    _annotate_funding_context(scored, features)
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
        symbol = slice_features[0].symbol if slice_features else ""
        agents = _with_session_gate(copy.deepcopy(spec.agents), spec.session_label, symbol)
        engine = _build_engine(candidate_config, agents)
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

    if "ETH" in upper:
        return specs

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
                    agents=[StockNewsMomentumAgent(min_relative_volume=1.25, min_atr_proxy=0.0036), EventAwareRiskSentinelAgent(True, allow_event_blackout=True), risk],
                    code_path="quant_system.agents.stocks.StockNewsMomentumAgent",
                    execution_overrides={"structure_exit_bars": 0, "stale_breakout_bars": 7, "max_holding_bars": 24},
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_stock_event_open_drive_patient",
                    description=f"{upper} event-day opening-drive continuation with patient exits",
                    agents=[StockEventOpenDriveContinuationAgent(min_relative_volume=1.2, min_atr_proxy=0.0035, max_minutes_from_open=135.0), EventAwareRiskSentinelAgent(True, allow_event_blackout=True), risk],
                    code_path="quant_system.agents.stocks.StockEventOpenDriveContinuationAgent",
                    execution_overrides={"structure_exit_bars": 0, "stale_breakout_bars": 7, "max_holding_bars": 24},
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_stock_gap_fade_selective",
                    description=f"{upper} selective gap fade with stricter extension filter",
                    agents=[StockGapFadeAgent(min_gap_proxy=0.0038, min_relative_volume=1.0), EventAwareRiskSentinelAgent(False), risk],
                    code_path="quant_system.agents.stocks.StockGapFadeAgent",
                    execution_overrides={"structure_exit_bars": 1, "stale_breakout_bars": 5, "max_holding_bars": 18},
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_stock_gap_and_go_selective",
                    description=f"{upper} selective gap-and-go continuation with stricter opening filter",
                    agents=[StockGapAndGoAgent(min_relative_volume=1.1, min_atr_proxy=0.0032, max_minutes_from_open=120.0), EventAwareRiskSentinelAgent(False), risk],
                    code_path="quant_system.agents.stocks.StockGapAndGoAgent",
                    execution_overrides={"structure_exit_bars": 0, "stale_breakout_bars": 6, "max_holding_bars": 22},
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_stock_gap_open_reclaim_selective",
                    description=f"{upper} selective gap reclaim continuation after premarket retake",
                    agents=[StockGapOpenReclaimAgent(min_relative_volume=1.0, min_gap_pct=0.0035, max_minutes_from_open=135.0), EventAwareRiskSentinelAgent(False), risk],
                    code_path="quant_system.agents.stocks.StockGapOpenReclaimAgent",
                    execution_overrides={"structure_exit_bars": 0, "stale_breakout_bars": 6, "max_holding_bars": 22},
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_stock_premarket_sweep_reversal",
                    description=f"{upper} premarket sweep reversal after failed gap extension",
                    agents=[StockPremarketSweepReversalAgent(min_relative_volume=1.0, min_gap_pct=0.003), EventAwareRiskSentinelAgent(False), risk],
                    code_path="quant_system.agents.stocks.StockPremarketSweepReversalAgent",
                    execution_overrides={"structure_exit_bars": 1, "stale_breakout_bars": 5, "max_holding_bars": 18},
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_stock_post_earnings_drift_patient",
                    description=f"{upper} post-earnings drift with patient exits",
                    agents=[StockPostEarningsDriftAgent(min_relative_volume=1.05, max_minutes_from_open=180.0), EventAwareRiskSentinelAgent(True, allow_event_blackout=True), risk],
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
                CandidateSpec(
                    name=f"{upper.lower()}_opening_range_short_breakdown_trend",
                    description=f"{upper} opening-range short breakdown with trend-runner exits",
                    agents=[OpeningRangeShortBreakdownAgent(), risk],
                    code_path="quant_system.agents.strategies.OpeningRangeShortBreakdownAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 8,
                        "max_holding_bars": 0,
                        "take_profit_atr_multiple": 3.0,
                        "trailing_stop_atr_multiple": 1.0,
                    },
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_opening_range_short_breakdown_trend_cross_risk_off",
                    description=f"{upper} opening-range short breakdown with cross-asset risk-off confirmation",
                    agents=[OpeningRangeShortBreakdownAgent(), risk],
                    code_path="quant_system.agents.strategies.OpeningRangeShortBreakdownAgent",
                    cross_filter_label="risk_off_confirm",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 8,
                        "max_holding_bars": 0,
                        "take_profit_atr_multiple": 3.0,
                        "trailing_stop_atr_multiple": 1.0,
                    },
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_opening_range_short_breakdown_fast",
                    description=f"{upper} opening-range short breakdown with faster failure control",
                    agents=[OpeningRangeShortBreakdownAgent(), risk],
                    code_path="quant_system.agents.strategies.OpeningRangeShortBreakdownAgent",
                    execution_overrides={
                        "structure_exit_bars": 1,
                        "stale_breakout_bars": 4,
                        "max_holding_bars": 16,
                        "take_profit_atr_multiple": 1.7,
                    },
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_volatility_short_breakdown_selective",
                    description=f"{upper} selective intraday short breakdown after volatility expansion",
                    agents=[
                        VolatilityShortBreakdownAgent(
                            lookback=10,
                            allowed_hours={15, 16, 17},
                            min_atr_proxy=0.0018,
                            min_trend_strength=max(config.agents.min_trend_strength * 0.9, 0.0008),
                            min_relative_volume=0.9,
                            min_momentum_20=0.0001,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.strategies.VolatilityShortBreakdownAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 5,
                        "max_holding_bars": 18,
                        "take_profit_atr_multiple": 2.1,
                        "trailing_stop_atr_multiple": 0.75,
                    },
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_volatility_short_breakdown_flat_high",
                    description=f"{upper} short breakdown focused on flat/high-volatility sessions",
                    agents=[
                        VolatilityShortBreakdownAgent(
                            lookback=9,
                            allowed_hours={15, 16},
                            min_atr_proxy=0.0016,
                            min_trend_strength=max(config.agents.min_trend_strength * 0.8, 0.0007),
                            min_relative_volume=0.85,
                            min_momentum_20=0.0,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.strategies.VolatilityShortBreakdownAgent",
                    regime_filter_label="trend_flat_vol_high",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 6,
                        "max_holding_bars": 20,
                        "take_profit_atr_multiple": 2.25,
                        "trailing_stop_atr_multiple": 0.8,
                    },
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_afternoon_downside_continuation",
                    description=f"{upper} afternoon downside continuation after failed rebounds",
                    agents=[
                        AfternoonDownsideContinuationAgent(
                            allowed_hours={15, 16, 17, 18},
                            min_trend_strength=max(config.agents.min_trend_strength * 0.85, 0.0007),
                            min_relative_volume=0.82,
                            max_z_score=0.55,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.strategies.AfternoonDownsideContinuationAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 6,
                        "max_holding_bars": 24,
                        "take_profit_atr_multiple": 2.35,
                        "trailing_stop_atr_multiple": 0.82,
                    },
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_afternoon_downside_continuation_trend_down",
                    description=f"{upper} afternoon downside continuation limited to trend-down regimes",
                    agents=[
                        AfternoonDownsideContinuationAgent(
                            allowed_hours={15, 16, 17},
                            min_trend_strength=max(config.agents.min_trend_strength * 0.95, 0.0008),
                            min_relative_volume=0.85,
                            max_z_score=0.4,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.strategies.AfternoonDownsideContinuationAgent",
                    regime_filter_label="trend_down_vol_high",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 5,
                        "max_holding_bars": 20,
                        "take_profit_atr_multiple": 2.5,
                        "trailing_stop_atr_multiple": 0.78,
                    },
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_failed_bounce_short",
                    description=f"{upper} failed-bounce short after weak reclaim attempts",
                    agents=[
                        FailedBounceShortAgent(
                            lookback=6,
                            allowed_hours={15, 16, 17},
                            min_relative_volume=0.82,
                            min_negative_trend=max(config.agents.min_trend_strength * 0.85, 0.0007),
                            min_z_score=0.2,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.strategies.FailedBounceShortAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 5,
                        "max_holding_bars": 18,
                        "take_profit_atr_multiple": 2.2,
                        "trailing_stop_atr_multiple": 0.74,
                    },
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_failed_bounce_short_trend_down",
                    description=f"{upper} failed-bounce short limited to trend-down regimes",
                    agents=[
                        FailedBounceShortAgent(
                            lookback=7,
                            allowed_hours={15, 16},
                            min_relative_volume=0.84,
                            min_negative_trend=max(config.agents.min_trend_strength * 0.95, 0.0008),
                            min_z_score=0.35,
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.strategies.FailedBounceShortAgent",
                    regime_filter_label="trend_down_vol_high",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 4,
                        "max_holding_bars": 16,
                        "take_profit_atr_multiple": 2.35,
                        "trailing_stop_atr_multiple": 0.7,
                    },
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_prior_day_failed_bounce_short",
                    description=f"{upper} short failed-bounce against prior-day and overnight context",
                    agents=[
                        PriorDayFailedBounceShortAgent(
                            min_negative_trend=max(config.agents.min_trend_strength * 0.9, 0.00075)
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.us100.PriorDayFailedBounceShortAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 5,
                        "max_holding_bars": 18,
                        "take_profit_atr_multiple": 2.15,
                        "trailing_stop_atr_multiple": 0.72,
                    },
                ),
                CandidateSpec(
                    name=f"{upper.lower()}_prior_day_failed_bounce_short_trend_down",
                    description=f"{upper} prior-day failed-bounce short limited to trend-down/high-vol regimes",
                    agents=[
                        PriorDayFailedBounceShortAgent(
                            min_negative_trend=max(config.agents.min_trend_strength, 0.0008)
                        ),
                        risk,
                    ],
                    code_path="quant_system.agents.us100.PriorDayFailedBounceShortAgent",
                    regime_filter_label="trend_down_vol_high",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 4,
                        "max_holding_bars": 16,
                        "take_profit_atr_multiple": 2.3,
                        "trailing_stop_atr_multiple": 0.68,
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
                        name="us500_momentum_impulse_high_vol_us100_breakout_confirm",
                        description="US500 momentum impulse with US100 breakout confirmation",
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
                        cross_filter_label="us100_breakout_confirm",
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
                    CandidateSpec(
                        name="us500_short_vwap_reject_flat_high_dense",
                        description="US500 denser short VWAP rejection in flat/high-volatility regime",
                        agents=[
                            US500ShortVWAPRejectAgent(
                                config.agents.min_trend_strength * 0.8,
                                allowed_hours={15, 16, 17},
                                min_relative_volume=0.84,
                            ),
                            risk,
                        ],
                        code_path="quant_system.agents.us500.US500ShortVWAPRejectAgent",
                        regime_filter_label="trend_flat_vol_high",
                        execution_overrides={
                            "structure_exit_bars": 0,
                            "stale_breakout_bars": 6,
                            "max_holding_bars": 22,
                            "take_profit_atr_multiple": 2.0,
                            "trailing_stop_atr_multiple": 0.82,
                        },
                    ),
                    CandidateSpec(
                        name="us500_opening_drive_short_reclaim_flat_high",
                        description="US500 opening-drive short reclaim in flat/high-volatility tape",
                        agents=[
                            US500OpeningDriveShortReclaimAgent(
                                config.agents.min_trend_strength * 0.95,
                                allowed_hours={15, 16},
                                min_relative_volume=0.88,
                                max_session_position=0.58,
                            ),
                            risk,
                        ],
                        code_path="quant_system.agents.us500.US500OpeningDriveShortReclaimAgent",
                        regime_filter_label="trend_flat_vol_high",
                        execution_overrides={
                            "structure_exit_bars": 0,
                            "stale_breakout_bars": 5,
                            "max_holding_bars": 20,
                            "take_profit_atr_multiple": 2.15,
                            "trailing_stop_atr_multiple": 0.78,
                        },
                    ),
                    CandidateSpec(
                        name="us500_volatility_short_breakdown_flat_high",
                        description="US500 short volatility breakdown in flat/high-volatility sessions",
                        agents=[
                            VolatilityShortBreakdownAgent(
                                lookback=8,
                                allowed_hours={15, 16, 17},
                                min_atr_proxy=0.0014,
                                min_trend_strength=max(config.agents.min_trend_strength * 0.75, 0.0007),
                                min_relative_volume=0.82,
                                min_momentum_20=-0.0001,
                            ),
                            risk,
                        ],
                        code_path="quant_system.agents.strategies.VolatilityShortBreakdownAgent",
                        regime_filter_label="trend_flat_vol_high",
                        execution_overrides={
                            "structure_exit_bars": 0,
                            "stale_breakout_bars": 6,
                            "max_holding_bars": 22,
                            "take_profit_atr_multiple": 2.1,
                            "trailing_stop_atr_multiple": 0.8,
                        },
                    ),
                    CandidateSpec(
                        name="us500_flat_high_reversal",
                        description="US500 flat/high-volatility reversal fade",
                        agents=[
                            US500FlatHighReversalAgent(
                                max_abs_trend_strength=0.0006,
                                min_relative_volume=0.8,
                                allowed_hours={15, 16, 17},
                                min_z_score=0.8,
                            ),
                            risk,
                        ],
                        code_path="quant_system.agents.us500.US500FlatHighReversalAgent",
                        regime_filter_label="trend_flat_vol_high",
                        execution_overrides={
                            "structure_exit_bars": 0,
                            "stale_breakout_bars": 4,
                            "max_holding_bars": 14,
                            "take_profit_atr_multiple": 1.7,
                            "trailing_stop_atr_multiple": 0.65,
                        },
                    ),
                    CandidateSpec(
                        name="us500_flat_high_reversal_dense",
                        description="US500 denser flat/high-volatility reversal fade",
                        agents=[
                            US500FlatHighReversalAgent(
                                max_abs_trend_strength=0.00075,
                                min_relative_volume=0.76,
                                allowed_hours={15, 16, 17, 18},
                                min_z_score=0.7,
                            ),
                            risk,
                        ],
                        code_path="quant_system.agents.us500.US500FlatHighReversalAgent",
                        regime_filter_label="trend_flat_vol_high",
                        execution_overrides={
                            "structure_exit_bars": 1,
                            "stale_breakout_bars": 5,
                            "max_holding_bars": 16,
                            "take_profit_atr_multiple": 1.55,
                            "trailing_stop_atr_multiple": 0.6,
                        },
                    ),
                    CandidateSpec(
                        name="us500_flat_tape_mean_reversion",
                        description="US500 flat-tape mean reversion around VWAP and rolling mean",
                        agents=[
                            US500FlatTapeMeanReversionAgent(
                                lookback=8,
                                max_abs_trend_strength=0.0006,
                                min_relative_volume=0.78,
                                allowed_hours={15, 16, 17},
                                min_abs_z_score=0.9,
                            ),
                            risk,
                        ],
                        code_path="quant_system.agents.us500.US500FlatTapeMeanReversionAgent",
                        regime_filter_label="trend_flat_vol_high",
                        execution_overrides={
                            "structure_exit_bars": 1,
                            "stale_breakout_bars": 4,
                            "max_holding_bars": 12,
                            "take_profit_atr_multiple": 1.45,
                            "trailing_stop_atr_multiple": 0.55,
                        },
                    ),
                    CandidateSpec(
                        name="us500_flat_tape_mean_reversion_dense",
                        description="US500 denser flat-tape mean reversion in flat/high-volatility tape",
                        agents=[
                            US500FlatTapeMeanReversionAgent(
                                lookback=6,
                                max_abs_trend_strength=0.00075,
                                min_relative_volume=0.74,
                                allowed_hours={15, 16, 17, 18},
                                min_abs_z_score=0.75,
                            ),
                            risk,
                        ],
                        code_path="quant_system.agents.us500.US500FlatTapeMeanReversionAgent",
                        regime_filter_label="trend_flat_vol_high",
                        execution_overrides={
                            "structure_exit_bars": 1,
                            "stale_breakout_bars": 5,
                            "max_holding_bars": 14,
                            "take_profit_atr_multiple": 1.35,
                            "trailing_stop_atr_multiple": 0.5,
                        },
                    ),
                    CandidateSpec(
                        name="us500_overnight_gap_fade",
                        description="US500 overnight gap fade using prior-day and overnight context",
                        agents=[
                            US500OvernightGapFadeAgent(
                                min_gap_pct=0.0014,
                                max_abs_trend_strength=0.0007,
                                min_relative_volume=0.8,
                            ),
                            risk,
                        ],
                        code_path="quant_system.agents.us500.US500OvernightGapFadeAgent",
                        execution_overrides={
                            "structure_exit_bars": 1,
                            "stale_breakout_bars": 4,
                            "max_holding_bars": 12,
                            "take_profit_atr_multiple": 1.5,
                            "trailing_stop_atr_multiple": 0.55,
                        },
                    ),
                    CandidateSpec(
                        name="us500_overnight_gap_fade_flat_high",
                        description="US500 overnight gap fade focused on flat/high-volatility tape",
                        agents=[
                            US500OvernightGapFadeAgent(
                                min_gap_pct=0.0012,
                                max_abs_trend_strength=0.0008,
                                min_relative_volume=0.76,
                            ),
                            risk,
                        ],
                        code_path="quant_system.agents.us500.US500OvernightGapFadeAgent",
                        regime_filter_label="trend_flat_vol_high",
                        execution_overrides={
                            "structure_exit_bars": 1,
                            "stale_breakout_bars": 5,
                            "max_holding_bars": 14,
                            "take_profit_atr_multiple": 1.4,
                            "trailing_stop_atr_multiple": 0.5,
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
                    allowed_variants=("5m_open", "15m_open"),
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
                    allowed_variants=("5m_open",),
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
                    allowed_variants=("5m_europe", "15m_europe"),
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
                    allowed_variants=("5m_europe", "15m_europe"),
                ),
                CandidateSpec(
                    name="ger40_opening_drive_fade_long",
                    description="GER40 long fade after opening drive washout and reclaim",
                    agents=[GER40OpeningDriveFadeLongAgent(), risk],
                    code_path="quant_system.agents.ger40.GER40OpeningDriveFadeLongAgent",
                    allowed_variants=("5m_europe", "15m_europe"),
                    regime_filter_label="trend_flat_vol_mid",
                    execution_overrides={
                        "structure_exit_bars": 1,
                        "stale_breakout_bars": 4,
                        "max_holding_bars": 14,
                        "take_profit_atr_multiple": 1.5,
                        "trailing_stop_atr_multiple": 0.45,
                    },
                ),
                CandidateSpec(
                    name="ger40_range_reclaim_long",
                    description="GER40 long reclaim after failed breakdown below opening range",
                    agents=[GER40RangeReclaimLongAgent(), risk],
                    code_path="quant_system.agents.ger40.GER40RangeReclaimLongAgent",
                    allowed_variants=("5m_europe", "15m_europe"),
                    regime_filter_label="trend_down_vol_low",
                    execution_overrides={
                        "structure_exit_bars": 1,
                        "stale_breakout_bars": 4,
                        "max_holding_bars": 12,
                        "take_profit_atr_multiple": 1.4,
                        "trailing_stop_atr_multiple": 0.4,
                    },
                ),
                CandidateSpec(
                    name="ger40_midday_breakout_long",
                    description="GER40 midday continuation breakout after opening range compression",
                    agents=[GER40MiddayBreakoutLongAgent(), risk],
                    code_path="quant_system.agents.ger40.GER40MiddayBreakoutLongAgent",
                    allowed_variants=("5m_midday", "15m_midday"),
                    regime_filter_label="trend_up_vol_mid",
                    execution_overrides={
                        "structure_exit_bars": 1,
                        "stale_breakout_bars": 3,
                        "max_holding_bars": 16,
                        "take_profit_atr_multiple": 1.8,
                        "trailing_stop_atr_multiple": 0.55,
                    },
                ),
                CandidateSpec(
                    name="ger40_midday_breakout_short",
                    description="GER40 midday downside continuation after opening range compression",
                    agents=[GER40MiddayBreakoutShortAgent(), risk],
                    code_path="quant_system.agents.ger40.GER40MiddayBreakoutShortAgent",
                    allowed_variants=("5m_midday", "15m_midday"),
                    regime_filter_label="trend_down_vol_mid",
                    execution_overrides={
                        "structure_exit_bars": 1,
                        "stale_breakout_bars": 3,
                        "max_holding_bars": 16,
                        "take_profit_atr_multiple": 1.8,
                        "trailing_stop_atr_multiple": 0.55,
                    },
                ),
                CandidateSpec(
                    name="ger40_europe_mean_reversion_long",
                    description="GER40 higher-frequency Europe-session mean reversion from session lows",
                    agents=[GER40EuropeMeanReversionLongAgent(), risk],
                    code_path="quant_system.agents.ger40.GER40EuropeMeanReversionLongAgent",
                    allowed_variants=("5m_europe", "15m_europe"),
                    regime_filter_label="trend_flat_vol_mid",
                    execution_overrides={
                        "structure_exit_bars": 1,
                        "stale_breakout_bars": 2,
                        "max_holding_bars": 10,
                        "take_profit_atr_multiple": 1.1,
                        "trailing_stop_atr_multiple": 0.35,
                    },
                ),
                CandidateSpec(
                    name="ger40_europe_mean_reversion_short",
                    description="GER40 higher-frequency Europe-session mean reversion from session highs",
                    agents=[GER40EuropeMeanReversionShortAgent(), risk],
                    code_path="quant_system.agents.ger40.GER40EuropeMeanReversionShortAgent",
                    allowed_variants=("5m_europe", "15m_europe"),
                    regime_filter_label="trend_flat_vol_mid",
                    execution_overrides={
                        "structure_exit_bars": 1,
                        "stale_breakout_bars": 2,
                        "max_holding_bars": 10,
                        "take_profit_atr_multiple": 1.1,
                        "trailing_stop_atr_multiple": 0.35,
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
        if "ETH" in upper:
            reversion_variants = [
                ("balanced", 1.8, 0.60, 0.00035, 0.0008),
                ("selective", 2.1, 0.68, 0.00028, 0.0009),
            ]
            for label, z_entry, rel_vol, max_trend, atr in reversion_variants:
                specs.append(
                    CandidateSpec(
                        name=f"crypto_vwap_reversion_sweep_{label}",
                        description=f"ETH VWAP reversion sweep {label}",
                        agents=[
                            CryptoVWAPReversionAgent(
                                z_score_entry=z_entry,
                                min_relative_volume=rel_vol,
                                max_trend_strength=max_trend,
                                min_atr_proxy=atr,
                            ),
                            RiskSentinelAgent(max_volatility=config.risk.max_volatility * 1.8, min_relative_volume=max(rel_vol - 0.05, 0.5)),
                        ],
                        code_path="quant_system.agents.crypto.CryptoVWAPReversionAgent",
                        execution_overrides={
                            "max_holding_bars": 16,
                            "take_profit_atr_multiple": 1.4,
                            "stale_breakout_bars": 4,
                            "structure_exit_bars": 1,
                        },
                    )
                )
            sweep_variants = [
                ("balanced", 18, 0.0009, 0.60, 0.0006, 0.0010),
                ("selective", 22, 0.0011, 0.68, 0.0007, 0.0008),
            ]
            for label, lookback, sweep_margin, rel_vol, atr, max_trend in sweep_variants:
                specs.append(
                    CandidateSpec(
                        name=f"eth_liquidity_sweep_reversal_sweep_{label}",
                        description=f"ETH liquidity sweep reversal sweep {label}",
                        agents=[
                            EthLiquiditySweepReversalAgent(
                                lookback=lookback,
                                sweep_margin=sweep_margin,
                                min_relative_volume=rel_vol,
                                min_atr_proxy=atr,
                                max_trend_strength=max_trend,
                            ),
                            RiskSentinelAgent(max_volatility=config.risk.max_volatility * 1.8, min_relative_volume=max(rel_vol - 0.05, 0.5)),
                        ],
                        code_path="quant_system.agents.crypto.EthLiquiditySweepReversalAgent",
                        execution_overrides={
                            "max_holding_bars": 14,
                            "take_profit_atr_multiple": 1.3,
                            "stale_breakout_bars": 4,
                            "structure_exit_bars": 1,
                        },
                    )
                )
            return specs
        if "BTC" in upper:
            sweep_variants = [
                ("balanced", 20, 0.00045, 0.58, 0.0007, 0.0014),
                ("dense", 16, 0.00035, 0.54, 0.0006, 0.0017),
                ("selective", 24, 0.00060, 0.66, 0.0009, 0.0010),
            ]
            for label, lookback, sweep_margin, rel_vol, atr, max_trend in sweep_variants:
                specs.append(
                    CandidateSpec(
                        name=f"btc_liquidity_sweep_reversal_sweep_{label}",
                        description=f"BTC liquidity sweep reversal sweep {label}",
                        agents=[
                            EthLiquiditySweepReversalAgent(
                                lookback=lookback,
                                sweep_margin=sweep_margin,
                                min_relative_volume=rel_vol,
                                min_atr_proxy=atr,
                                max_trend_strength=max_trend,
                            ),
                            RiskSentinelAgent(max_volatility=config.risk.max_volatility * 2.0, min_relative_volume=max(rel_vol - 0.05, 0.5)),
                        ],
                        code_path="quant_system.agents.crypto.EthLiquiditySweepReversalAgent",
                        allowed_variants=("15m_overlap", "15m_us", "1h_us"),
                        execution_overrides={
                            "max_holding_bars": 14 if label == "dense" else (16 if label == "balanced" else 20),
                            "take_profit_atr_multiple": 1.30 if label == "dense" else (1.45 if label == "balanced" else 1.65),
                            "stale_breakout_bars": 4 if label == "dense" else (5 if label == "balanced" else 6),
                            "structure_exit_bars": 1,
                            "trailing_stop_atr_multiple": 0.45 if label == "dense" else (0.50 if label == "balanced" else 0.60),
                        },
                    )
                )
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
    elif _is_stock_symbol(symbol):
        stock_risk = EventAwareRiskSentinelAgent(allow_high_impact_day=False)
        stock_event_risk = EventAwareRiskSentinelAgent(allow_high_impact_day=True, allow_event_blackout=True)
        trend_variants = [
            ("balanced", 8, 24, 0.95, 0.0022, 0.0004, 0.0006),
            ("dense", 6, 18, 0.85, 0.0016, 0.0002, 0.00035),
            ("selective", 10, 30, 1.10, 0.0028, 0.0006, 0.0009),
        ]
        for label, fast_window, slow_window, rel_vol, atr, mom5, mom20 in trend_variants:
            specs.append(
                CandidateSpec(
                    name=f"stock_trend_breakout_sweep_{label}",
                    description=f"Stock trend breakout sweep {label}",
                    agents=[
                        StockTrendBreakoutAgent(
                            fast_window=fast_window,
                            slow_window=slow_window,
                            min_relative_volume=rel_vol,
                            min_atr_proxy=atr,
                            min_momentum_5=mom5,
                            min_momentum_20=mom20,
                            max_news_count=6.0 if label == "dense" else 4.0,
                        ),
                        stock_risk,
                        RiskSentinelAgent(
                            max_volatility=config.risk.max_volatility * 1.15,
                            min_relative_volume=max(rel_vol - 0.05, 0.7),
                        ),
                    ],
                    code_path="quant_system.agents.stocks.StockTrendBreakoutAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 6 if label == "dense" else 5,
                        "max_holding_bars": 20 if label == "dense" else 16,
                    },
                )
            )

        gap_variants = [
            ("balanced", 1.10, 0.0028, 0.0002, 0.0005, 120.0),
            ("dense", 1.00, 0.0022, 0.0001, 0.00025, 150.0),
            ("selective", 1.25, 0.0034, 0.0004, 0.0008, 90.0),
        ]
        for label, rel_vol, atr, mom5, mom20, max_minutes in gap_variants:
            specs.append(
                CandidateSpec(
                    name=f"stock_gap_and_go_sweep_{label}",
                    description=f"Stock gap-and-go sweep {label}",
                    agents=[
                        StockGapAndGoAgent(
                            min_relative_volume=rel_vol,
                            min_atr_proxy=atr,
                            min_momentum_5=mom5,
                            min_momentum_20=mom20,
                            max_minutes_from_open=max_minutes,
                        ),
                        stock_risk,
                        RiskSentinelAgent(
                            max_volatility=config.risk.max_volatility * 1.2,
                            min_relative_volume=max(rel_vol - 0.1, 0.7),
                        ),
                    ],
                    code_path="quant_system.agents.stocks.StockGapAndGoAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 5 if label != "dense" else 6,
                        "max_holding_bars": 18 if label != "dense" else 22,
                    },
                )
            )

        power_variants = [
            ("balanced", 0.90, 0.0022, 0.0002, (18, 19)),
            ("dense", 0.82, 0.0017, 0.0001, (17, 18, 19)),
            ("selective", 1.00, 0.0028, 0.00035, (18, 19)),
        ]
        for label, rel_vol, mom20, mom5, hours in power_variants:
            specs.append(
                CandidateSpec(
                    name=f"stock_power_hour_sweep_{label}",
                    description=f"Stock power-hour continuation sweep {label}",
                    agents=[
                        StockPowerHourContinuationAgent(
                            min_relative_volume=rel_vol,
                            min_momentum_20=mom20,
                            min_momentum_5=mom5,
                            allowed_hours=hours,
                        ),
                        stock_risk,
                        RiskSentinelAgent(
                            max_volatility=config.risk.max_volatility * 1.1,
                            min_relative_volume=max(rel_vol - 0.05, 0.7),
                        ),
                    ],
                    code_path="quant_system.agents.stocks.StockPowerHourContinuationAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 4,
                        "max_holding_bars": 16 if label != "dense" else 20,
                    },
                )
            )

        event_variants = [
            ("balanced", 1.20, 0.0032, 180.0),
            ("dense", 1.05, 0.0028, 210.0),
        ]
        for label, rel_vol, atr, max_minutes in event_variants:
            specs.append(
                CandidateSpec(
                    name=f"stock_post_earnings_drift_sweep_{label}",
                    description=f"Stock post-earnings drift sweep {label}",
                    agents=[
                        StockPostEarningsDriftAgent(min_relative_volume=rel_vol, max_minutes_from_open=max_minutes),
                        stock_event_risk,
                        RiskSentinelAgent(
                            max_volatility=config.risk.max_volatility * 1.2,
                            min_relative_volume=max(rel_vol - 0.1, 0.7),
                        ),
                    ],
                    code_path="quant_system.agents.stocks.StockPostEarningsDriftAgent",
                    execution_overrides={
                        "structure_exit_bars": 0,
                        "stale_breakout_bars": 7,
                        "max_holding_bars": 24 if label == "balanced" else 28,
                    },
                )
            )
    return specs


def _with_variant_name(spec: CandidateSpec, variant_label: str) -> CandidateSpec | None:
    if spec.allowed_variants and variant_label not in spec.allowed_variants:
        return None
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
        regime_filter_label=spec.regime_filter_label,
        reference_filter_label=spec.reference_filter_label,
        cross_filter_label=spec.cross_filter_label,
        allowed_variants=spec.allowed_variants,
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
                    agents=[StockNewsMomentumAgent(min_relative_volume=1.2, min_atr_proxy=0.0035), EventAwareRiskSentinelAgent(True, allow_event_blackout=True), RiskSentinelAgent(max_volatility=config.risk.max_volatility, min_relative_volume=config.agents.min_relative_volume)],
                    code_path="quant_system.agents.stocks.StockNewsMomentumAgent",
                    execution_overrides={"structure_exit_bars": 0, "stale_breakout_bars": 8, "max_holding_bars": 26},
                )
            )
        if closed_trades <= 4:
            specs.append(
                CandidateSpec(
                    name=f"{upper.lower()}_stock_post_earnings_drift_dense",
                    description=f"{upper} denser post-earnings drift variant",
                    agents=[StockPostEarningsDriftAgent(min_relative_volume=1.0, max_minutes_from_open=210.0), EventAwareRiskSentinelAgent(True, allow_event_blackout=True), RiskSentinelAgent(max_volatility=config.risk.max_volatility, min_relative_volume=config.agents.min_relative_volume)],
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


def _feature_regime_to_unified(label: str) -> str:
    normalized = str(label or "").strip().lower()
    if not normalized:
        return ""
    structure_label = "trend" if normalized.startswith(("trend_up", "trend_down")) else "range"
    if normalized.endswith("vol_high"):
        volatility_label = "high"
    elif normalized.endswith("vol_low"):
        volatility_label = "low"
    else:
        volatility_label = "normal"
    synthetic_legacy = "calm_range"
    if structure_label == "trend" and volatility_label == "high":
        synthetic_legacy = "volatile_trend"
    elif structure_label == "trend":
        synthetic_legacy = "calm_trend"
    elif volatility_label == "high":
        synthetic_legacy = "volatile_chop"
    return map_regime_label_to_unified(synthetic_legacy, volatility_label, structure_label)


def _summarize_unified_regime(raw_label: str) -> str:
    unified = _feature_regime_to_unified(raw_label)
    if not unified:
        return raw_label
    if not raw_label:
        return unified
    return f"{unified} ({raw_label})"


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
    regime_trade_count_by_label = {label: len(values) for label, values in regime_pnls.items()}
    regime_pnl_by_label = {label: float(sum(values)) for label, values in regime_pnls.items()}
    regime_pf_by_label: dict[str, float] = {}
    regime_win_rate_by_label: dict[str, float] = {}
    positive_pnl_total = 0.0
    negative_pnl_total = 0.0
    for label, values in regime_pnls.items():
        wins = [value for value in values if value > 0.0]
        losses = [value for value in values if value < 0.0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        regime_pf_by_label[label] = (gross_profit / gross_loss) if gross_loss > 0.0 else (999.0 if gross_profit > 0.0 else 0.0)
        regime_win_rate_by_label[label] = (len(wins) / len(values) * 100.0) if values else 0.0
        pnl_total = regime_pnl_by_label[label]
        if pnl_total > 0.0:
            positive_pnl_total += pnl_total
        elif pnl_total < 0.0:
            negative_pnl_total += abs(pnl_total)
    result.best_regime = best_regime
    result.best_unified_regime = _feature_regime_to_unified(best_regime)
    result.best_regime_pnl = sum(regime_pnls[best_regime])
    result.worst_regime = worst_regime
    result.worst_unified_regime = _feature_regime_to_unified(worst_regime)
    result.worst_regime_pnl = sum(regime_pnls[worst_regime])
    result.dominant_regime_share_pct = (len(regime_pnls[dominant_regime]) / total_trades * 100.0) if total_trades else 0.0
    result.regime_trade_count_by_label = json.dumps(regime_trade_count_by_label, sort_keys=True)
    result.regime_pnl_by_label = json.dumps(regime_pnl_by_label, sort_keys=True)
    result.regime_pf_by_label = json.dumps(regime_pf_by_label, sort_keys=True)
    result.regime_win_rate_by_label = json.dumps(regime_win_rate_by_label, sort_keys=True)
    total_directional = positive_pnl_total + negative_pnl_total
    result.regime_stability_score = (positive_pnl_total / total_directional) if total_directional > 0.0 else 0.0
    result.regime_loss_ratio = (
        abs(min(result.worst_regime_pnl, 0.0)) / result.best_regime_pnl
        if result.best_regime_pnl > 0.0
        else 999.0
    )


def _annotate_funding_context(result: CandidateResult, features: list[FeatureVector]) -> None:
    if not features:
        return
    latest = features[-1].values
    result.broker_swap_available = latest.get("broker_swap_available", 0.0) > 0.0
    result.broker_swap_long = float(latest.get("broker_swap_long", 0.0))
    result.broker_swap_short = float(latest.get("broker_swap_short", 0.0))
    result.broker_carry_spread = float(latest.get("broker_carry_spread", 0.0))
    preferred_side = float(latest.get("broker_preferred_carry_side", 0.0))
    if preferred_side >= 0.5:
        result.broker_preferred_carry_side = "long"
    elif preferred_side <= -0.5:
        result.broker_preferred_carry_side = "short"
    else:
        result.broker_preferred_carry_side = "none"


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


def _promotion_tier_for_row(row: CandidateResult | dict[str, object], symbol: str) -> str:
    if _meets_viability(row, symbol):
        return "core"
    if _meets_regime_specialist_viability(row, symbol):
        return "specialist"
    return "reject"


def build_execution_policy_from_candidate_row(row: CandidateResult | dict[str, object]) -> dict[str, object]:
    symbol = str(row.get("symbol", "") or "") if isinstance(row, dict) else ""
    promotion_tier = _promotion_tier_for_row(row, symbol)
    best_regime = str(row.best_regime if isinstance(row, CandidateResult) else row.get("best_regime", "") or "")
    worst_regime = str(row.worst_regime if isinstance(row, CandidateResult) else row.get("worst_regime", "") or "")
    regime_stability_score = float(
        row.regime_stability_score if isinstance(row, CandidateResult) else row.get("regime_stability_score", 0.0)
    )
    regime_loss_ratio = float(
        row.regime_loss_ratio if isinstance(row, CandidateResult) else row.get("regime_loss_ratio", 999.0)
    )
    component_count = int(row.component_count if isinstance(row, CandidateResult) else row.get("component_count", 1))
    regime_pnl_by_label = _metric_map_from_row(row, "regime_pnl_by_label")
    combined_row = component_count > 1
    if combined_row and regime_pnl_by_label:
        positive_regimes = [
            item[0]
            for item in sorted(regime_pnl_by_label.items(), key=lambda item: item[1], reverse=True)
            if item[1] > 0.0
        ]
        negative_regimes = [
            item[0]
            for item in sorted(regime_pnl_by_label.items(), key=lambda item: item[1])
            if item[1] < 0.0
        ]
        active_feature_regimes = tuple(positive_regimes[:2])
        blocked_feature_regimes = tuple(item for item in negative_regimes[:2] if item not in active_feature_regimes)
        allowed_regimes = tuple(
            item for item in dict.fromkeys(_feature_regime_to_unified(label) for label in active_feature_regimes) if item
        )
        blocked_regimes = tuple(
            item for item in dict.fromkeys(_feature_regime_to_unified(label) for label in blocked_feature_regimes) if item and item not in allowed_regimes
        )
    else:
        active_feature_regimes = (best_regime,) if best_regime else ()
        allowed_regimes = tuple(
            item for item in (_feature_regime_to_unified(best_regime),) if item
        )
        blocked_regimes = tuple(
            item for item in (_feature_regime_to_unified(worst_regime),) if item and item not in allowed_regimes
        )
    blocked_summary = ", ".join(blocked_regimes) if blocked_regimes else "no explicit blocked regime"
    allowed_summary = ", ".join(allowed_regimes) if allowed_regimes else "no preferred regime"

    active_regimes = active_feature_regimes or ((best_regime,) if best_regime else ())
    vol_suffixes = [regime.split("_")[-1] for regime in active_regimes if regime]
    min_vol_percentile = 0.0
    max_vol_percentile = 1.0
    vol_ranges: list[tuple[float, float]] = []
    for vol_suffix in vol_suffixes:
        if vol_suffix == "low":
            vol_ranges.append((0.0, 0.45))
        elif vol_suffix == "mid":
            vol_ranges.append((0.20, 0.80))
        elif vol_suffix == "high":
            vol_ranges.append((0.55, 0.97))
    if vol_ranges:
        min_vol_percentile = min(item[0] for item in vol_ranges)
        max_vol_percentile = max(item[1] for item in vol_ranges)

    base_allocation_weight = max(0.35, min(1.15, 0.45 + regime_stability_score * 0.70))
    if component_count > 1:
        base_allocation_weight *= 0.85
    if regime_loss_ratio > 0.75:
        base_allocation_weight *= 0.85

    max_risk_multiplier = max(0.35, min(1.0, 0.55 + regime_stability_score * 0.45))
    if "high" in vol_suffixes:
        max_risk_multiplier = min(max_risk_multiplier, 0.60)
    min_risk_multiplier = 0.0
    if promotion_tier == "specialist":
        base_allocation_weight = min(base_allocation_weight, 0.35)
        max_risk_multiplier = min(max_risk_multiplier, 0.35)
    elif promotion_tier == "reject":
        base_allocation_weight = min(base_allocation_weight, 0.20)
        max_risk_multiplier = min(max_risk_multiplier, 0.20)
    policy_summary = (
        f"tier={promotion_tier}"
        f"; activate in unified_regimes={allowed_summary}"
        f"; avoid unified_regimes={blocked_summary}"
        f"; vol_pct in [{min_vol_percentile:.2f}, {max_vol_percentile:.2f}]"
        f"; base_weight={base_allocation_weight:.2f}"
        f"; risk_cap={max_risk_multiplier:.2f}"
        f"; stability={regime_stability_score:.2f}"
        f"; loss_ratio={regime_loss_ratio:.2f}"
    )

    return {
        "promotion_tier": promotion_tier,
        "allowed_regimes": allowed_regimes,
        "blocked_regimes": blocked_regimes,
        "min_vol_percentile": min_vol_percentile,
        "max_vol_percentile": max_vol_percentile,
        "base_allocation_weight": base_allocation_weight,
        "max_risk_multiplier": max_risk_multiplier,
        "min_risk_multiplier": min_risk_multiplier,
        "policy_summary": policy_summary,
    }


def _regime_improvement_specs(specs: list[CandidateSpec], results: list[CandidateResult]) -> list[CandidateSpec]:
    lookup = {spec.name: spec for spec in specs}
    ranked = sorted(
        [row for row in results if row.best_regime and row.best_regime_pnl > 0.0 and row.worst_regime_pnl < 0.0],
        key=lambda item: (item.regime_stability_score, -(item.regime_loss_ratio), item.best_regime_pnl, item.profit_factor, item.closed_trades),
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
                description=f"{base_spec.description} focused on {_feature_regime_to_unified(row.best_regime) or row.best_regime}",
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
        "sharpe_ratio": row.sharpe_ratio,
        "sortino_ratio": row.sortino_ratio,
        "calmar_ratio": row.calmar_ratio,
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
        "best_trade_share_pct": row.best_trade_share_pct,
        "equity_new_high_share_pct": row.equity_new_high_share_pct,
        "max_consecutive_losses": row.max_consecutive_losses,
        "equity_quality_score": row.equity_quality_score,
        "mc_simulations": row.mc_simulations,
        "mc_pnl_median": row.mc_pnl_median,
        "mc_pnl_p05": row.mc_pnl_p05,
        "mc_pnl_p95": row.mc_pnl_p95,
        "mc_max_drawdown_pct_median": row.mc_max_drawdown_pct_median,
        "mc_max_drawdown_pct_p95": row.mc_max_drawdown_pct_p95,
        "mc_loss_probability_pct": row.mc_loss_probability_pct,
        "sparse_strategy": row.sparse_strategy,
        "component_count": row.component_count,
        "combo_outperformance_score": row.combo_outperformance_score,
        "combo_trade_overlap_pct": row.combo_trade_overlap_pct,
        "recommended": False,
        "promotion_tier": _promotion_tier_for_row(row, symbol),
        "variant_label": row.variant_label,
        "session_label": row.session_label,
        "regime_filter_label": row.regime_filter_label,
        "cross_filter_label": row.cross_filter_label,
        "execution_overrides": row.execution_overrides or {},
        "best_regime": row.best_regime,
        "best_regime_pnl": row.best_regime_pnl,
        "regime_stability_score": row.regime_stability_score,
        "regime_loss_ratio": row.regime_loss_ratio,
        "regime_trade_count_by_label": row.regime_trade_count_by_label,
        "regime_pf_by_label": row.regime_pf_by_label,
        "regime_specialist_viable": _meets_regime_specialist_viability(row, symbol),
    }


def _selection_component_keys(row: dict[str, object]) -> set[str]:
    candidate_name = str(row.get("candidate_name", "")).strip()
    variant_label = str(row.get("variant_label", "")).strip()
    regime_filter_label = str(row.get("regime_filter_label", "")).strip()
    parts = _component_names(candidate_name)
    if parts:
        return {
            f"{part}|{variant_label}|{regime_filter_label}"
            for part in parts
        }
    code_paths = _component_set(str(row.get("code_path", "")))
    if code_paths:
        return {
            f"{path}|{variant_label}|{regime_filter_label}"
            for path in code_paths
        }
    return {f"{candidate_name}|{variant_label}|{regime_filter_label}"}


def _candidate_selection_score(row: dict[str, object]) -> tuple[float, ...]:
    return (
        float(row.get("equity_quality_score", 0.0)),
        float(row.get("regime_stability_score", 0.0)),
        -float(row.get("best_trade_share_pct", 100.0)),
        float(row.get("equity_new_high_share_pct", 0.0)),
        -float(row.get("regime_loss_ratio", 999.0)),
        float(row.get("validation_pnl", 0.0)) + float(row.get("test_pnl", 0.0)),
        float(row.get("test_pnl", 0.0)),
        float(row.get("validation_pnl", 0.0)),
        float(row.get("realized_pnl", 0.0)),
    )


def _is_valid_execution_combo(combo: tuple[dict[str, object], ...], symbol: str) -> bool:
    used_components: set[str] = set()
    used_signatures: set[tuple[str, str, str]] = set()
    used_code_paths: set[str] = set()
    used_regimes: set[str] = set()
    allow_multi_core = symbol_is_forex(symbol) or _is_crypto_symbol(symbol) or _is_metal_symbol(symbol)
    specialist_count = 0
    core_count = 0
    for row in combo:
        components = _selection_component_keys(row)
        if components & used_components:
            return False
        used_components.update(components)
        code_path = str(row.get("code_path", "") or "").strip()
        variant_label = str(row.get("variant_label", "") or "").strip()
        best_regime = str(row.get("best_regime", "") or "").strip()
        signature = (code_path, variant_label, best_regime)
        if signature in used_signatures:
            return False
        used_signatures.add(signature)
        if code_path and code_path in used_code_paths:
            return False
        if code_path:
            used_code_paths.add(code_path)
        if best_regime:
            if best_regime in used_regimes:
                return False
            used_regimes.add(best_regime)
        tier = str(row.get("promotion_tier", "reject"))
        if tier == "specialist":
            specialist_count += 1
        if tier == "core":
            core_count += 1
    if specialist_count > 1:
        return False
    if core_count == 0 and any(str(row.get("promotion_tier", "")) == "core" for row in combo):
        return False
    if not allow_multi_core and len(combo) > 1:
        return False
    return True


def _build_execution_candidate_sets(rows: list[dict[str, object]], symbol: str, max_candidates: int = 3) -> list[tuple[str, list[dict[str, object]]]]:
    candidate_sets: list[tuple[str, list[dict[str, object]]]] = []
    seen_names: set[tuple[str, ...]] = set()

    def _append_set(label: str, candidate_set: list[dict[str, object]]) -> None:
        if not candidate_set:
            return
        key = tuple(sorted(str(row.get("candidate_name", "")) for row in candidate_set))
        if key in seen_names:
            return
        seen_names.add(key)
        candidate_sets.append((label, candidate_set))

    standard_candidates = select_execution_candidates(rows, max_candidates=max_candidates)
    _append_set("standard", standard_candidates)

    sparse_candidates = select_sparse_execution_candidates(rows, symbol, max_candidates=max_candidates)
    _append_set("sparse", sparse_candidates)

    pool = sorted(
        [row for row in rows if str(row.get("promotion_tier", "reject")) in {"core", "specialist"}],
        key=_candidate_selection_score,
        reverse=True,
    )[:6]
    for size in range(1, min(max_candidates, len(pool)) + 1):
        for combo in itertools.combinations(pool, size):
            if not _is_valid_execution_combo(combo, symbol):
                continue
            _append_set(f"combo_{size}", list(combo))
    return candidate_sets


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
                reference_filter_label=base_spec.reference_filter_label,
                cross_filter_label=base_spec.cross_filter_label,
            )
            features, _ = load_execution_features_for_variant(
                config,
                symbol,
                data_symbol,
                candidate_spec.variant_label,
                candidate_spec.regime_filter_label,
                candidate_spec.cross_filter_label,
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
    used_code_paths: set[str] = set()
    used_variant_regimes: set[tuple[str, str, str]] = set()
    viable_rows = [row for row in rows if _meets_viability(row, str(row.get("symbol", "")))]
    specialist_rows = [
        row for row in rows if bool(row.get("regime_specialist_viable")) and not _meets_viability(row, str(row.get("symbol", "")))
    ]
    ranked = sorted(
        viable_rows,
        key=lambda row: (
            bool(row.get("recommended")),
            float(row.get("regime_stability_score", 0.0)),
            -float(row.get("regime_loss_ratio", 999.0)),
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
    specialist_ranked = sorted(
        specialist_rows,
        key=lambda row: (
            float(row.get("best_regime_pnl", 0.0)),
            float(row.get("regime_stability_score", 0.0)),
            -float(row.get("regime_loss_ratio", 999.0)),
            int(_metric_map_from_row(row, "regime_trade_count_by_label").get(str(row.get("best_regime", "") or ""), 0.0)),
            float(row.get("test_pnl", 0.0)),
            float(row.get("validation_pnl", 0.0)),
        ),
        reverse=True,
    )

    if ranked:
        lead = ranked[0]
        selected.append(lead)
        used_components.update(_selection_component_keys(lead))
        lead_code_path = str(lead.get("code_path", "") or "").strip()
        if lead_code_path:
            used_code_paths.add(lead_code_path)
        used_variant_regimes.add(
            (
                str(lead.get("code_path", "") or "").strip(),
                str(lead.get("variant_label", "") or "").strip(),
                str(lead.get("best_regime", "") or "").strip(),
            )
        )

    if selected and len(selected) < max_candidates:
        lead_regime = str(selected[0].get("best_regime", "") or "")
        for row in specialist_ranked:
            components = _selection_component_keys(row)
            if components & used_components:
                continue
            candidate_code_path = str(row.get("code_path", "") or "").strip()
            candidate_signature = (
                candidate_code_path,
                str(row.get("variant_label", "") or "").strip(),
                str(row.get("best_regime", "") or "").strip(),
            )
            if candidate_signature in used_variant_regimes:
                continue
            if lead_regime and str(row.get("best_regime", "") or "") == lead_regime:
                continue
            selected.append(row)
            used_components.update(components)
            if candidate_code_path:
                used_code_paths.add(candidate_code_path)
            used_variant_regimes.add(candidate_signature)
            break

    fallback_ranked = [row for row in ranked[1:] if row not in selected] + [row for row in specialist_ranked if row not in selected]
    for row in fallback_ranked:
        components = _selection_component_keys(row)
        if selected and components & used_components:
            continue
        candidate_code_path = str(row.get("code_path", "") or "").strip()
        candidate_signature = (
            candidate_code_path,
            str(row.get("variant_label", "") or "").strip(),
            str(row.get("best_regime", "") or "").strip(),
        )
        if candidate_signature in used_variant_regimes:
            continue
        if candidate_code_path and candidate_code_path in used_code_paths and selected:
            continue
        selected.append(row)
        used_components.update(components)
        if candidate_code_path:
            used_code_paths.add(candidate_code_path)
        used_variant_regimes.add(candidate_signature)
        if len(selected) >= max_candidates:
            break
    return selected


def _tiered_fallback_candidates(rows: list[dict[str, object]], symbol: str, max_candidates: int = 3) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    used_components: set[str] = set()
    core_rows = [row for row in rows if str(row.get("promotion_tier", "reject")) == "core"]
    specialist_rows = [row for row in rows if str(row.get("promotion_tier", "reject")) == "specialist"]
    allow_multi_core = symbol_is_forex(symbol) or _is_crypto_symbol(symbol) or _is_metal_symbol(symbol)
    allow_forex_specialist_third = symbol_is_forex(symbol) or _is_crypto_symbol(symbol) or _is_metal_symbol(symbol)
    used_regimes: set[str] = set()
    used_variants: set[str] = set()
    used_code_paths: set[str] = set()

    core_ranked = sorted(
        core_rows,
        key=lambda row: (
            float(row.get("validation_pnl", 0.0)) + float(row.get("test_pnl", 0.0)),
            float(row.get("test_pnl", 0.0)),
            float(row.get("validation_pnl", 0.0)),
            float(row.get("regime_stability_score", 0.0)),
            float(row.get("realized_pnl", 0.0)),
        ),
        reverse=True,
    )

    if core_ranked:
        lead = core_ranked[0]
        selected.append(lead)
        used_components.update(_selection_component_keys(lead))
        lead_regime = str(lead.get("best_regime", "") or "")
        lead_variant = str(lead.get("variant_label", "") or "").strip()
        if lead_regime:
            used_regimes.add(lead_regime)
        if lead_variant:
            used_variants.add(lead_variant)
        lead_code_path = str(lead.get("code_path", "") or "").strip()
        if lead_code_path:
            used_code_paths.add(lead_code_path)

    if allow_multi_core and selected:
        for row in core_ranked[1:]:
            if len(selected) >= max_candidates:
                break
            components = _selection_component_keys(row)
            if components & used_components:
                continue
            candidate_regime = str(row.get("best_regime", "") or "")
            candidate_variant = str(row.get("variant_label", "") or "").strip()
            if candidate_regime and candidate_regime in used_regimes:
                continue
            if candidate_variant and candidate_variant in used_variants:
                continue
            selected.append(row)
            used_components.update(components)
            if candidate_regime:
                used_regimes.add(candidate_regime)
            if candidate_variant:
                used_variants.add(candidate_variant)
            candidate_code_path = str(row.get("code_path", "") or "").strip()
            if candidate_code_path:
                used_code_paths.add(candidate_code_path)

    specialist_ranked = sorted(
        specialist_rows,
        key=lambda row: (
            int(_metric_map_from_row(row, "regime_trade_count_by_label").get(str(row.get("best_regime", "") or ""), 0.0)),
            float(row.get("best_regime_pnl", 0.0)),
            float(row.get("equity_quality_score", 0.0)),
            -float(row.get("best_trade_share_pct", 100.0)),
        ),
        reverse=True,
    )
    if not selected and allow_multi_core and specialist_ranked:
        lead_specialist = specialist_ranked[0]
        selected.append(lead_specialist)
        used_components.update(_selection_component_keys(lead_specialist))
        lead_regime = str(lead_specialist.get("best_regime", "") or "")
        lead_variant = str(lead_specialist.get("variant_label", "") or "").strip()
        if lead_regime:
            used_regimes.add(lead_regime)
        if lead_variant:
            used_variants.add(lead_variant)
        lead_code_path = str(lead_specialist.get("code_path", "") or "").strip()
        if lead_code_path:
            used_code_paths.add(lead_code_path)
    lead_regime = str(selected[0].get("best_regime", "") or "") if selected else ""
    for row in specialist_ranked:
        components = _selection_component_keys(row)
        if components & used_components:
            continue
        candidate_regime = str(row.get("best_regime", "") or "")
        candidate_code_path = str(row.get("code_path", "") or "").strip()
        same_regime = bool(candidate_regime and candidate_regime in used_regimes)
        if lead_regime and candidate_regime == lead_regime and not allow_forex_specialist_third:
            continue
        if same_regime and not allow_forex_specialist_third:
            continue
        if same_regime and allow_forex_specialist_third and len(selected) < 2:
            continue
        if candidate_code_path and candidate_code_path in used_code_paths:
            continue
        selected.append(row)
        used_components.update(components)
        if candidate_regime:
            used_regimes.add(candidate_regime)
        if candidate_code_path:
            used_code_paths.add(candidate_code_path)
        if len(selected) >= max_candidates:
            break

    return selected[:max_candidates]


def select_sparse_execution_candidates(rows: list[dict[str, object]], symbol: str, max_candidates: int = 3) -> list[dict[str, object]]:
    thresholds = _research_thresholds(symbol)
    selected: list[dict[str, object]] = []
    used_components: set[str] = set()
    used_variants: set[str] = set()
    sparse_rows = [
        row
        for row in rows
        if bool(row.get("sparse_strategy"))
        and float(row.get("realized_pnl", 0.0)) > 0.0
        and float(row.get("profit_factor", 0.0)) >= float(thresholds["min_profit_factor"])
        and (float(row.get("validation_pnl", 0.0)) + float(row.get("test_pnl", 0.0))) > 0.0
        and (int(row.get("validation_closed_trades", 0)) + int(row.get("test_closed_trades", 0))) > 0
        and (
            _meets_viability(row, symbol)
            or bool(row.get("regime_specialist_viable"))
        )
    ]
    ranked = sorted(
        sparse_rows,
        key=lambda row: (
            float(row.get("validation_pnl", 0.0)) + float(row.get("test_pnl", 0.0)),
            int(row.get("validation_closed_trades", 0)) + int(row.get("test_closed_trades", 0)),
            max(float(row.get("walk_forward_pass_rate_pct", 0.0)), float(row.get("walk_forward_soft_pass_rate_pct", 0.0))),
            float(row.get("test_pnl", 0.0)),
            float(row.get("validation_pnl", 0.0)),
            float(row.get("realized_pnl", 0.0)),
        ),
        reverse=True,
    )
    while len(selected) < max_candidates:
        current_validation_closed = sum(int(item.get("validation_closed_trades", 0)) for item in selected)
        current_test_closed = sum(int(item.get("test_closed_trades", 0)) for item in selected)
        current_validation_pnl = sum(float(item.get("validation_pnl", 0.0)) for item in selected)
        current_test_pnl = sum(float(item.get("test_pnl", 0.0)) for item in selected)
        best_row: dict[str, object] | None = None
        best_score: tuple[float, ...] | None = None
        for row in ranked:
            if row in selected:
                continue
            components = _selection_component_keys(row)
            if selected and components & used_components:
                continue
            variant_label = str(row.get("variant_label", "")).strip()
            if selected and variant_label and variant_label in used_variants:
                continue
            validation_closed = int(row.get("validation_closed_trades", 0))
            test_closed = int(row.get("test_closed_trades", 0))
            validation_pnl = float(row.get("validation_pnl", 0.0))
            test_pnl = float(row.get("test_pnl", 0.0))
            coverage_gain = 0
            if current_validation_pnl <= 0.0 and validation_closed > 0 and validation_pnl > 0.0:
                coverage_gain += 1
            if current_test_pnl <= 0.0 and test_closed > 0 and test_pnl > 0.0:
                coverage_gain += 1
            score = (
                float(coverage_gain),
                float(validation_pnl > 0.0 and test_pnl > 0.0),
                validation_pnl + test_pnl,
                test_pnl,
                validation_pnl,
                float(row.get("realized_pnl", 0.0)),
            )
            if best_score is None or score > best_score:
                best_score = score
                best_row = row
        if best_row is None:
            break
        selected.append(best_row)
        used_components.update(_selection_component_keys(best_row))
        variant_label = str(best_row.get("variant_label", "")).strip()
        if variant_label:
            used_variants.add(variant_label)
        combined_validation_closed = sum(int(item.get("validation_closed_trades", 0)) for item in selected)
        combined_test_closed = sum(int(item.get("test_closed_trades", 0)) for item in selected)
        combined_validation_pnl = sum(float(item.get("validation_pnl", 0.0)) for item in selected)
        combined_test_pnl = sum(float(item.get("test_pnl", 0.0)) for item in selected)
        combined_closed = combined_validation_closed + combined_test_closed
        combined_pnl = sum(float(item.get("validation_pnl", 0.0)) + float(item.get("test_pnl", 0.0)) for item in selected)
        if (
            combined_closed >= int(thresholds["sparse_combined_closed_trades"])
            and combined_pnl > 0.0
            and combined_validation_closed > 0
            and combined_test_closed > 0
            and combined_validation_pnl > 0.0
            and combined_test_pnl > 0.0
        ):
            break
    combined_closed = sum(int(item.get("validation_closed_trades", 0)) + int(item.get("test_closed_trades", 0)) for item in selected)
    combined_validation_closed = sum(int(item.get("validation_closed_trades", 0)) for item in selected)
    combined_test_closed = sum(int(item.get("test_closed_trades", 0)) for item in selected)
    combined_validation_pnl = sum(float(item.get("validation_pnl", 0.0)) for item in selected)
    combined_test_pnl = sum(float(item.get("test_pnl", 0.0)) for item in selected)
    combined_pnl = sum(float(item.get("validation_pnl", 0.0)) + float(item.get("test_pnl", 0.0)) for item in selected)
    if (
        combined_closed < int(thresholds["sparse_combined_closed_trades"])
        or combined_pnl <= 0.0
        or combined_validation_closed <= 0
        or combined_test_closed <= 0
        or combined_validation_pnl <= 0.0
        or combined_test_pnl <= 0.0
    ):
        return []
    return selected


def _export_results(symbol: str, broker_symbol: str, data_source: str, rows: list[CandidateResult]) -> tuple[Path, Path]:
    reports_dir = research_reports_dir(symbol)
    csv_path = reports_dir / "symbol_research.csv"
    txt_path = reports_dir / "symbol_research.txt"

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
                "sharpe_ratio",
                "sortino_ratio",
                "calmar_ratio",
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
                "best_unified_regime",
                "best_regime_pnl",
                "worst_regime",
                "worst_unified_regime",
                "worst_regime_pnl",
                "dominant_regime_share_pct",
                "regime_stability_score",
                "regime_loss_ratio",
                "regime_trade_count_by_label",
                "regime_pnl_by_label",
                "regime_pf_by_label",
                "regime_win_rate_by_label",
                "regime_filter_label",
                "broker_swap_available",
                "broker_swap_long",
                "broker_swap_short",
                "broker_preferred_carry_side",
                "broker_carry_spread",
                "mc_simulations",
                "mc_pnl_median",
                "mc_pnl_p05",
                "mc_pnl_p95",
                "mc_max_drawdown_pct_median",
                "mc_max_drawdown_pct_p95",
                "mc_loss_probability_pct",
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
                    f"{row.sharpe_ratio:.5f}",
                    f"{row.sortino_ratio:.5f}",
                    f"{row.calmar_ratio:.5f}",
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
                    row.best_unified_regime,
                    f"{row.best_regime_pnl:.5f}",
                    row.worst_regime,
                    row.worst_unified_regime,
                    f"{row.worst_regime_pnl:.5f}",
                    f"{row.dominant_regime_share_pct:.5f}",
                    f"{row.regime_stability_score:.5f}",
                    f"{row.regime_loss_ratio:.5f}",
                    row.regime_trade_count_by_label,
                    row.regime_pnl_by_label,
                    row.regime_pf_by_label,
                    row.regime_win_rate_by_label,
                    row.regime_filter_label,
                    int(row.broker_swap_available),
                    f"{row.broker_swap_long:.5f}",
                    f"{row.broker_swap_short:.5f}",
                    row.broker_preferred_carry_side,
                    f"{row.broker_carry_spread:.5f}",
                    row.mc_simulations,
                    f"{row.mc_pnl_median:.5f}",
                    f"{row.mc_pnl_p05:.5f}",
                    f"{row.mc_pnl_p95:.5f}",
                    f"{row.mc_max_drawdown_pct_median:.5f}",
                    f"{row.mc_max_drawdown_pct_p95:.5f}",
                    f"{row.mc_loss_probability_pct:.5f}",
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
        candidate_row = _execution_candidate_row_from_result(symbol, row)
        policy = build_execution_policy_from_candidate_row(candidate_row)
        lines.append(
            f"{row.name} [{row.archetype}|{policy['promotion_tier']}]: pnl={row.realized_pnl:.2f} closed={row.closed_trades} "
            f"pf={row.profit_factor:.2f} win_rate={row.win_rate_pct:.2f}% dd={row.max_drawdown_pct:.2f}%"
        )
        lines.append(f"  tier: {policy['promotion_tier']}")
        lines.append(
            f"  trade_metrics: expectancy={row.expectancy:.2f} sharpe={row.sharpe_ratio:.2f} "
            f"sortino={row.sortino_ratio:.2f} calmar={row.calmar_ratio:.2f} avg_win={row.avg_win:.2f} "
            f"avg_loss={row.avg_loss:.2f} payoff={row.payoff_ratio:.2f} avg_hold={row.avg_hold_bars:.1f}"
        )
        lines.append(
            f"  exits: dominant={row.dominant_exit or 'none'} share={row.dominant_exit_share_pct:.2f}%"
        )
        lines.append(
            f"  regimes: best={_summarize_unified_regime(row.best_regime) if row.best_regime else 'none'} pnl={row.best_regime_pnl:.2f} "
            f"worst={_summarize_unified_regime(row.worst_regime) if row.worst_regime else 'none'} pnl={row.worst_regime_pnl:.2f} "
            f"dominant_share={row.dominant_regime_share_pct:.2f}% "
            f"stability={row.regime_stability_score:.2f} loss_ratio={row.regime_loss_ratio:.2f}"
        )
        lines.append(
            f"  unified_regimes: best={row.best_unified_regime or 'none'} "
            f"worst={row.worst_unified_regime or 'none'}"
        )
        lines.append(f"  regime_trade_counts: {row.regime_trade_count_by_label}")
        lines.append(f"  regime_pnls: {row.regime_pnl_by_label}")
        lines.append(
            f"  funding: available={'yes' if row.broker_swap_available else 'no'} "
            f"swap_long={row.broker_swap_long:.5f} swap_short={row.broker_swap_short:.5f} "
            f"preferred_side={row.broker_preferred_carry_side or 'none'} "
            f"carry_spread={row.broker_carry_spread:.5f}"
        )
        lines.append(
            f"  monte_carlo: sims={row.mc_simulations} pnl_median={row.mc_pnl_median:.2f} "
            f"p05={row.mc_pnl_p05:.2f} p95={row.mc_pnl_p95:.2f} "
            f"dd_median={row.mc_max_drawdown_pct_median:.2f}% dd_p95={row.mc_max_drawdown_pct_p95:.2f}% "
            f"loss_prob={row.mc_loss_probability_pct:.2f}%"
        )
        lines.append(f"  live_policy: {policy['policy_summary']}")
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
    lines.extend(["", "Top candidate-level winners"])
    if winners:
        for row in winners[:3]:
            tier = _promotion_tier_for_row(row, symbol)
            lines.append(f"- {row.name} [{tier}] ({row.description})")
    else:
        lines.append("No candidate met the positive-PnL and PF>=1.0 threshold.")
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, txt_path


def _candidate_failure_reasons(row: CandidateResult, symbol: str) -> list[str]:
    reasons: list[str] = []
    specialist_viable = _meets_regime_specialist_viability(row, symbol)
    thresholds = _research_thresholds(symbol)
    validation_min = int(thresholds["validation_closed_trades"])
    test_min = int(thresholds["test_closed_trades"])
    wf_pass_min = float(thresholds["walk_forward_min_pass_rate_pct"])
    sparse_strategy = _is_sparse_candidate(row, symbol)
    if row.mc_simulations <= 0:
        reasons.append("monte carlo missing (no simulations recorded)")
    else:
        if row.mc_pnl_p05 <= 0.0:
            reasons.append(f"monte carlo p05 pnl <= 0 ({row.mc_pnl_p05:.2f})")
        if row.mc_loss_probability_pct > 10.0:
            reasons.append(f"monte carlo loss probability too high ({row.mc_loss_probability_pct:.2f}% > 10.00%)")
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
    if not row.best_regime:
        reasons.append("no regime edge identified")
    if row.best_regime_pnl <= 0.0:
        reasons.append(f"best regime pnl <= 0 ({row.best_regime_pnl:.2f})")
    if row.regime_stability_score < 0.50:
        reasons.append(f"regime stability too low ({row.regime_stability_score:.2f} < 0.50)")
    if row.regime_loss_ratio > 1.25:
        reasons.append(f"regime loss ratio too high ({row.regime_loss_ratio:.2f} > 1.25)")
    if row.equity_quality_score < 0.45:
        reasons.append(f"equity quality too low ({row.equity_quality_score:.2f} < 0.45)")
    if row.best_trade_share_pct > 70.0:
        reasons.append(f"best trade concentration too high ({row.best_trade_share_pct:.2f}% > 70%)")
    if row.component_count > 1 and row.combo_outperformance_score < 0.0:
        reasons.append(f"combo underperformed components ({row.combo_outperformance_score:.2f})")
    if row.component_count > 1 and row.combo_trade_overlap_pct > 80.0:
        reasons.append(f"combo overlap too high ({row.combo_trade_overlap_pct:.2f}% > 80%)")
    if reasons and specialist_viable:
        reasons.append("broad viability failed, but candidate qualifies as a regime specialist")
    return reasons


def _export_viability_autopsy(symbol: str, rows: list[CandidateResult], execution_validation_summary: str) -> Path:
    path = research_reports_dir(symbol) / "viability_autopsy.txt"
    ranked = sorted(rows, key=lambda item: (item.realized_pnl, item.profit_factor, item.closed_trades), reverse=True)
    counts: dict[str, int] = {}
    near_misses: list[tuple[CandidateResult, list[str]]] = []
    tier_counts = {"core": 0, "specialist": 0, "reject": 0}
    for row in ranked:
        tier = _promotion_tier_for_row(row, symbol)
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        reasons = _candidate_failure_reasons(row, symbol)
        for reason in reasons:
            counts[reason] = counts.get(reason, 0) + 1
        if reasons:
            near_misses.append((row, reasons))

    lines = [
        f"Viability autopsy: {symbol}",
        f"Execution validation summary: {execution_validation_summary}",
        f"Tier counts: core={tier_counts['core']} specialist={tier_counts['specialist']} reject={tier_counts['reject']}",
        "",
        "Top blockers",
    ]
    for reason, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:8]:
        lines.append(f"- {reason}: {count}")
    lines.extend(["", "Top near-misses"])
    for row, reasons in near_misses[:8]:
        tier = _promotion_tier_for_row(row, symbol)
        lines.append(
            f"- {row.name} [{tier}]: pnl={row.realized_pnl:.2f} pf={row.profit_factor:.2f} "
            f"val={row.validation_pnl:.2f}/{row.validation_profit_factor:.2f}/{row.validation_closed_trades} "
            f"test={row.test_pnl:.2f}/{row.test_profit_factor:.2f}/{row.test_closed_trades} "
            f"wf={row.walk_forward_pass_rate_pct:.2f}%"
        )
        lines.append(f"  reasons: {', '.join(reasons)}")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run_symbol_research(
    data_symbol: str,
    broker_symbol: str | None = None,
    *,
    candidate_name_prefixes: tuple[str, ...] | None = None,
) -> list[str]:
    config = SystemConfig()
    resolved = resolve_symbol_request(data_symbol, broker_symbol)
    config.symbol_research.broker_symbol = resolved.broker_symbol
    config.market_data.history_days = _symbol_research_history_days(config, resolved.profile_symbol)
    _configure_symbol_execution(config, resolved.profile_symbol, resolved.broker_symbol)
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
    if candidate_name_prefixes:
        singles = [
            spec
            for spec in singles
            if any(spec.name.startswith(prefix) for prefix in candidate_name_prefixes)
        ]
    symbol_slug = _symbol_slug(resolved.profile_symbol)
    results: list[CandidateResult] = []
    explored_entry_exit_specs: list[CandidateSpec] = []
    for variant_label, features in feature_variants.items():
        if not features:
            continue
        variant_specs = [spec for base_spec in singles if (spec := _with_variant_name(base_spec, variant_label)) is not None]
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
                    materialized_spec,
                    "parameter_sweep",
                    f"{symbol_slug}_{materialized_spec.name}_{variant_label}_symbol_candidate",
                )
                for base_spec in sweep_specs
                if (materialized_spec := _with_variant_name(base_spec, variant_label)) is not None
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
                    spec.cross_filter_label,
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
                    spec.cross_filter_label,
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
                    spec.cross_filter_label,
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
    spec_lookup = {
        spec.name: spec
        for spec in (
            explored_entry_exit_specs
            + sweep_specs
            + improvement_specs
            + second_pass_specs
            + regime_specs
            + autopsy_specs
            + near_miss_specs
            + local_optimized_specs
            + combos
        )
    }
    _annotate_combo_results(results)
    csv_path, txt_path = _export_results(resolved.profile_symbol, resolved.broker_symbol, data_source, results)
    ranked = sorted(
        results,
        key=lambda item: (
            _meets_viability(item, resolved.profile_symbol),
            item.regime_stability_score,
            -item.regime_loss_ratio,
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

    execution_candidate_rows = [
        (
            {
            "candidate_name": row.name,
            "symbol": resolved.profile_symbol,
            "code_path": row.code_path,
            "realized_pnl": row.realized_pnl,
            "profit_factor": row.profit_factor,
            "closed_trades": row.closed_trades,
            "sharpe_ratio": row.sharpe_ratio,
            "sortino_ratio": row.sortino_ratio,
            "calmar_ratio": row.calmar_ratio,
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
            "best_regime": row.best_regime,
            "best_unified_regime": row.best_unified_regime,
            "best_regime_pnl": row.best_regime_pnl,
            "worst_regime": row.worst_regime,
            "worst_unified_regime": row.worst_unified_regime,
            "worst_regime_pnl": row.worst_regime_pnl,
            "dominant_regime_share_pct": row.dominant_regime_share_pct,
            "regime_stability_score": row.regime_stability_score,
            "regime_loss_ratio": row.regime_loss_ratio,
            "recommended": row.name in recommended,
            "variant_label": row.variant_label,
            "session_label": row.session_label,
            "regime_filter_label": row.regime_filter_label,
            "execution_overrides": row.execution_overrides or {},
            "agents": copy.deepcopy(spec_lookup[row.name].agents) if row.name in spec_lookup else None,
        }
        | build_execution_policy_from_candidate_row(row)
        )
        for row in results
    ]
    fallback_limit = 3 if symbol_is_forex(resolved.profile_symbol) or _is_crypto_symbol(resolved.profile_symbol) else 2
    candidate_sets = _build_execution_candidate_sets(
        execution_candidate_rows,
        resolved.profile_symbol,
        max_candidates=fallback_limit,
    )
    standard_candidates = next((candidate_set for label, candidate_set in candidate_sets if label == "standard"), [])
    sparse_candidates = next((candidate_set for label, candidate_set in candidate_sets if label == "sparse"), [])
    selected_execution_candidates: list[dict[str, object]] = []
    execution_set_id: int | None = None
    execution_validation_summary = "not_run"
    execution_rejection_reason = ""
    selection_diagnostics = (
        f"standard={len(standard_candidates)} sparse={len(sparse_candidates)}"
    )
    generated_combo_count = sum(1 for label, _ in candidate_sets if label.startswith("combo_"))
    if generated_combo_count:
        selection_diagnostics += f" combos={generated_combo_count}"
    best_execution_choice: tuple[tuple[float, float, float, float, int], list[dict[str, object]], str] | None = None
    best_reduced_risk_choice: tuple[tuple[float, float, float, float, int], list[dict[str, object]], str] | None = None
    for selection_kind, candidate_set in candidate_sets:
        execution_validation_result, execution_validation_source, execution_variant = _evaluate_execution_candidate_set(
            config,
            resolved.profile_symbol,
            resolved.data_symbol,
            candidate_set,
        )
        path_metrics = _execution_path_metrics(execution_validation_result)
        sparse_execution = any(bool(row.get("sparse_strategy")) for row in candidate_set)
        min_execution_closed_trades = 3 if sparse_execution else 2
        accepted = (
            execution_validation_result.realized_pnl > 0.0
            and execution_validation_result.profit_factor >= 1.0
            and len(execution_validation_result.closed_trades) >= min_execution_closed_trades
        )
        normal_quality = (
            path_metrics["equity_quality_score"] >= 0.35
            and path_metrics["time_under_water_pct"] <= 75.0
            and path_metrics["best_trade_share_pct"] <= 75.0
        )
        reduced_risk_acceptable = (
            execution_validation_result.realized_pnl > 0.0
            and execution_validation_result.profit_factor >= 1.0
            and len(execution_validation_result.closed_trades) >= min_execution_closed_trades
            and path_metrics["equity_quality_score"] >= 0.18
            and path_metrics["time_under_water_pct"] <= 90.0
            and path_metrics["best_trade_share_pct"] <= 90.0
        )
        summary = (
            f"selection={selection_kind} variant={execution_variant} data_source={execution_validation_source} "
            f"pnl={execution_validation_result.realized_pnl:.2f} "
            f"pf={execution_validation_result.profit_factor:.2f} "
            f"closed={len(execution_validation_result.closed_trades)} "
            f"quality={path_metrics['equity_quality_score']:.2f} "
            f"underwater={path_metrics['time_under_water_pct']:.1f}%"
        )
        if accepted and normal_quality:
            summary += " -> accepted"
            score = _execution_result_score(execution_validation_result, candidate_set)
            if best_execution_choice is None or score > best_execution_choice[0]:
                best_execution_choice = (score, candidate_set, summary)
        elif reduced_risk_acceptable:
            summary += " -> accepted_with_reduced_risk"
            score = _execution_result_score(execution_validation_result, candidate_set)
            if best_reduced_risk_choice is None or score > best_reduced_risk_choice[0]:
                best_reduced_risk_choice = (score, candidate_set, summary)
        elif best_execution_choice is None:
            execution_validation_summary = summary + " -> rejected"
            rejection_reasons: list[str] = []
            if execution_validation_result.realized_pnl <= 0.0:
                rejection_reasons.append(f"execution pnl <= 0 ({execution_validation_result.realized_pnl:.2f})")
            if execution_validation_result.profit_factor < 1.0:
                rejection_reasons.append(f"execution PF < 1.0 ({execution_validation_result.profit_factor:.2f})")
            if len(execution_validation_result.closed_trades) < min_execution_closed_trades:
                rejection_reasons.append(
                    f"execution closed trades too low ({len(execution_validation_result.closed_trades)} < {min_execution_closed_trades})"
                )
            if path_metrics["equity_quality_score"] < 0.2:
                rejection_reasons.append(f"execution quality too low ({path_metrics['equity_quality_score']:.2f})")
            execution_rejection_reason = ", ".join(rejection_reasons) if rejection_reasons else "execution set rejected by validation"
    if best_execution_choice is not None:
        _, selected_execution_candidates, execution_validation_summary = best_execution_choice
    elif best_reduced_risk_choice is not None:
        _, selected_execution_candidates, execution_validation_summary = best_reduced_risk_choice
    else:
        tiered_fallback = _tiered_fallback_candidates(
            execution_candidate_rows,
            resolved.profile_symbol,
            max_candidates=fallback_limit,
        )
        selection_diagnostics += f" tiered_fallback={len(tiered_fallback)}"
        if tiered_fallback:
            selected_execution_candidates = tiered_fallback
            core_count = sum(1 for row in selected_execution_candidates if str(row.get("promotion_tier", "")) == "core")
            specialist_count = sum(
                1 for row in selected_execution_candidates if str(row.get("promotion_tier", "")) == "specialist"
            )
            execution_validation_summary = (
                f"selection=tiered_fallback core={core_count} specialist={specialist_count} "
                f"-> accepted_with_reduced_risk"
            )
    recommended = [str(row["candidate_name"]) for row in selected_execution_candidates]
    symbol_status = _derive_symbol_status(selected_execution_candidates, execution_validation_summary)
    tier_counts = {"core": 0, "specialist": 0, "reject": 0}
    for row in results:
        tier = _promotion_tier_for_row(row, resolved.profile_symbol)
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
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
    deployment = build_symbol_deployment(
        profile_name=profile_name,
        symbol=resolved.profile_symbol,
        data_symbol=resolved.data_symbol,
        broker_symbol=resolved.broker_symbol,
        research_run_id=run_id,
        execution_set_id=execution_set_id,
        execution_validation_summary=execution_validation_summary,
        symbol_status=symbol_status,
        selected_candidates=selected_execution_candidates,
    )
    deployment_path = export_symbol_deployment(deployment)
    selected_execution_results = [row for row in results if row.name in {str(item["candidate_name"]) for item in selected_execution_candidates}]
    plot_paths = plot_symbol_research(
        resolved.profile_symbol,
        results,
        best_row=best,
        execution_rows=selected_execution_results,
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
    lines.append(f"Symbol status: {symbol_status}")
    lines.append(
        f"Tier counts: core={tier_counts['core']} specialist={tier_counts['specialist']} reject={tier_counts['reject']}"
    )
    lines.append(
        "Execution set: "
        + (
            ", ".join(str(row["candidate_name"]) for row in selected_execution_candidates)
            if selected_execution_candidates
            else "none"
        )
    )
    if not selected_execution_candidates and tier_counts["core"] > 0:
        lines.append(
            "Execution set note: core candidates existed, but no candidate set survived symbol-level execution selection "
            "or execution validation."
        )
        lines.append(f"Execution selection diagnostics: {selection_diagnostics}")
        if execution_rejection_reason:
            lines.append(f"Execution rejection reason: {execution_rejection_reason}")
    if selected_execution_candidates:
        lines.append(
            "Execution tiers: "
            + ", ".join(f"{row['candidate_name']}[{row.get('promotion_tier', 'core')}]" for row in selected_execution_candidates)
        )
    lines.append(f"Execution set id: {execution_set_id if execution_set_id is not None else 'none'}")
    lines.append(f"Execution validation: {execution_validation_summary}")
    if deployment_path is not None:
        lines.append(f"Live deployment: {deployment_path}")
    lines.append(f"Research history days: {config.market_data.history_days}")
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
