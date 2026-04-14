from __future__ import annotations

import asyncio
import csv
import hashlib
import logging
from pathlib import Path
from statistics import mean
import copy
import time

from quant_system.ai.analysis import build_profile_analysis
from quant_system.ai.history import build_experiment_memory_report
from quant_system.ai.models import ProfileArtifacts
from quant_system.ai.registry import build_agent_registry_records, render_agent_catalog, render_agent_registry
from quant_system.ai.storage import ExperimentStore
from quant_system.agents.factory import build_alpha_agents, build_shadow_candidate_agents, describe_profile_agents
from quant_system.artifacts import ARTIFACTS_DIR, profile_logs_dir, profile_reports_dir, research_candidates_dir
from quant_system.config import SystemConfig
from quant_system.costs import apply_ftmo_cost_profile
from quant_system.data.market_data import DuckDBMarketDataStore
from quant_system.evaluation.report import build_ftmo_report
from quant_system.execution.broker import SimulatedBroker
from quant_system.execution.engine import AgentCoordinator, EventDrivenEngine
from quant_system.integrations.mt5 import MT5Broker, MT5Client
from quant_system.logging_utils import configure_logging
from quant_system.monitoring.heartbeat import HeartbeatMonitor
from quant_system.optimization.walk_forward import SimpleParameterOptimizer
from quant_system.models import FeatureVector
from quant_system.models import MarketBar, OrderRequest, Side
from quant_system.profiles import StrategyProfile, resolve_profiles
from quant_system.research.features import build_feature_library
from quant_system.research.funding import apply_broker_funding_context, load_broker_funding_context
from quant_system.risk.limits import RiskManager
LOGGER = logging.getLogger(__name__)
def _safe_artifact_stem(name: str, max_length: int = 140) -> str:
    if len(name) <= max_length:
        return name
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]
    trimmed = name[: max_length - 13].rstrip("_")
    return f"{trimmed}_{digest}"

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
    apply_ftmo_cost_profile(config, profile.broker_symbol or profile.data_symbol, profile.broker_symbol)


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


def build_system(
    config: SystemConfig,
    optimized_agents,
) -> EventDrivenEngine:
    agents = build_alpha_agents(optimized_agents, config.risk, config.instrument.profile_name)
    return build_system_with_agents(config, agents, optimized_agents.consensus_min_confidence)


def build_system_with_agents(
    config: SystemConfig,
    agents,
    consensus_min_confidence: float,
) -> EventDrivenEngine:
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
        coordinator=AgentCoordinator(agents, consensus_min_confidence=consensus_min_confidence),
        broker=broker,
        risk_manager=RiskManager(
            config=config.risk,
            starting_equity=config.execution.initial_cash,
        ),
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
    if config.instrument.profile_name == "ger40_orb":
        engine.min_confidence_quantity_scale = 1.0
        engine.max_confidence_quantity_scale = 1.0
        engine.min_confidence_target_scale = 1.0
        engine.max_confidence_target_scale = 1.35
    return engine


def export_trade_artifacts(profile: StrategyProfile, result) -> tuple[Path, Path]:
    return export_closed_trade_artifacts(result.closed_trades, result.realized_pnl, f"{profile.name}")


def export_ai_artifacts(profile: StrategyProfile, package) -> tuple[Path, Path]:
    reports_dir = profile_reports_dir(profile.name)
    summary_path = reports_dir / "ai_summary.txt"
    experiments_path = reports_dir / "next_experiment.txt"

    summary_lines = [package.local_summary]
    if package.ai_summary:
        summary_lines.extend(["", "AI summary", package.ai_summary])
    else:
        summary_lines.extend(["", "AI summary", "AI enrichment unavailable. Local analysis only."])
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")

    experiment_lines = [f"Profile: {profile.name}", "Recommended next experiments", ""]
    experiment_lines.extend(f"- {item}" for item in package.next_experiments)
    experiments_path.write_text("\n".join(experiment_lines), encoding="utf-8")
    return summary_path, experiments_path


def export_memory_artifacts(profile: StrategyProfile, package) -> tuple[Path, Path]:
    reports_dir = profile_reports_dir(profile.name)
    history_path = reports_dir / "experiment_history.txt"
    comparison_path = reports_dir / "run_comparison.txt"
    history_path.write_text(package.history_summary, encoding="utf-8")
    comparison_path.write_text(package.comparison_summary, encoding="utf-8")
    return history_path, comparison_path


def export_agent_registry_artifact(profile: StrategyProfile, rendered_registry: str) -> Path:
    reports_dir = profile_reports_dir(profile.name)
    registry_path = reports_dir / "agent_registry.txt"
    registry_path.write_text(rendered_registry, encoding="utf-8")
    return registry_path


def export_agent_catalog_artifact(profile: StrategyProfile, rendered_catalog: str) -> Path:
    reports_dir = profile_reports_dir(profile.name)
    catalog_path = reports_dir / "agent_catalog.txt"
    catalog_path.write_text(rendered_catalog, encoding="utf-8")
    return catalog_path


def export_closed_trade_artifacts(closed_trades, realized_pnl: float, artifact_prefix: str) -> tuple[Path, Path]:
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    symbol = artifact_prefix.split("_", 1)[0]
    safe_prefix = _safe_artifact_stem(artifact_prefix)
    file_stem = safe_prefix[len(symbol) + 1 :] if safe_prefix.startswith(f"{symbol}_") else safe_prefix
    file_stem = _safe_artifact_stem(file_stem, max_length=110)
    candidate_dir = research_candidates_dir(symbol)
    trades_path = candidate_dir / f"{file_stem}_trades.csv"
    analysis_path = candidate_dir / f"{file_stem}_analysis.txt"

    with trades_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "symbol",
                "entry_timestamp",
                "exit_timestamp",
                "entry_hour",
                "exit_hour",
                "entry_reason",
                "exit_reason",
                "entry_price",
                "exit_price",
                "quantity",
                "pnl",
                "costs",
                "hold_bars",
                "entry_confidence",
                "entry_metadata",
            ]
        )
        for trade in closed_trades:
            writer.writerow(
                [
                    trade.symbol,
                    trade.entry_timestamp.isoformat(),
                    trade.exit_timestamp.isoformat(),
                    trade.entry_hour,
                    trade.exit_hour,
                    trade.entry_reason,
                    trade.exit_reason,
                    f"{trade.entry_price:.5f}",
                    f"{trade.exit_price:.5f}",
                    f"{trade.quantity:.5f}",
                    f"{trade.pnl:.5f}",
                    f"{trade.costs:.5f}",
                    trade.hold_bars,
                    f"{trade.entry_confidence:.5f}",
                    trade.entry_metadata,
                ]
            )

    by_hour: dict[int, list[float]] = {}
    by_setup: dict[str, list[float]] = {}
    by_exit: dict[str, list[float]] = {}
    for trade in closed_trades:
        by_hour.setdefault(trade.entry_hour, []).append(trade.pnl)
        by_setup.setdefault(trade.entry_reason, []).append(trade.pnl)
        by_exit.setdefault(trade.exit_reason, []).append(trade.pnl)

    def render_bucket(title: str, buckets: dict[object, list[float]]) -> list[str]:
        lines = [title]
        for key, pnls in sorted(buckets.items(), key=lambda item: (sum(item[1]), len(item[1]))):
            wins = sum(1 for pnl in pnls if pnl > 0)
            lines.append(
                f"{key}: trades={len(pnls)} pnl={sum(pnls):.2f} avg={sum(pnls)/len(pnls):.2f} win_rate={wins/len(pnls)*100.0:.2f}%"
            )
        return lines

    analysis_lines = [
        f"Artifact: {file_stem}",
        f"Closed trades: {len(closed_trades)}",
        f"Realized pnl: {realized_pnl:.2f}",
        "",
    ]
    analysis_lines.extend(render_bucket("By entry hour", by_hour))
    analysis_lines.append("")
    analysis_lines.extend(render_bucket("By entry setup", by_setup))
    analysis_lines.append("")
    analysis_lines.extend(render_bucket("By exit reason", by_exit))
    analysis_path.write_text("\n".join(analysis_lines), encoding="utf-8")
    return trades_path, analysis_path


def export_shadow_execution_artifacts(
    config: SystemConfig,
    profile: StrategyProfile,
    features: list[FeatureVector],
    optimized_agents,
) -> tuple[Path, Path] | tuple[None, None]:
    candidates = build_shadow_candidate_agents(optimized_agents, config.risk, profile.name)
    if not candidates:
        return None, None
    shadow_features, shadow_data_source = load_shadow_features(config, profile)

    logs_dir = profile_logs_dir(profile.name)
    reports_dir = profile_reports_dir(profile.name)
    csv_path = logs_dir / "shadow_setups.csv"
    analysis_path = reports_dir / "shadow_setups.txt"
    rows: list[dict[str, object]] = []

    for setup_name, agents in candidates.items():
        engine = build_system_with_agents(config, agents, optimized_agents.consensus_min_confidence)
        result = asyncio.run(engine.run(shadow_features, sleep_seconds=0.0))
        export_closed_trade_artifacts(
            result.closed_trades,
            result.realized_pnl,
            f"{profile.name}_{setup_name}_shadow",
        )
        rows.append(
            {
                "setup_name": setup_name,
                "trades": result.trades,
                "closed_trades": len(result.closed_trades),
                "realized_pnl": result.realized_pnl,
                "win_rate_pct": result.win_rate_pct,
                "profit_factor": result.profit_factor,
                "max_drawdown_pct": result.max_drawdown * 100.0,
                "total_costs": result.total_costs,
                "kill_switch_triggered": result.locked,
                "data_source": shadow_data_source,
            }
        )

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "setup_name",
                "trades",
                "closed_trades",
                "realized_pnl",
                "win_rate_pct",
                "profit_factor",
                "max_drawdown_pct",
                "total_costs",
                "kill_switch_triggered",
                "data_source",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["setup_name"],
                    row["trades"],
                    row["closed_trades"],
                    f"{float(row['realized_pnl']):.5f}",
                    f"{float(row['win_rate_pct']):.5f}",
                    f"{float(row['profit_factor']):.5f}",
                    f"{float(row['max_drawdown_pct']):.5f}",
                    f"{float(row['total_costs']):.5f}",
                    row["kill_switch_triggered"],
                    row["data_source"],
                ]
            )

    ranked_rows = sorted(
        rows,
        key=lambda row: (
            float(row["realized_pnl"]),
            float(row["profit_factor"]),
            float(row["win_rate_pct"]),
            -float(row["total_costs"]),
        ),
        reverse=True,
    )
    analysis_lines = [
        f"Profile: {profile.name}",
        "Shadow execution by setup",
        "",
    ]
    for row in ranked_rows:
        analysis_lines.append(
            f"{row['setup_name']}: pnl={float(row['realized_pnl']):.2f} closed={row['closed_trades']} pf={float(row['profit_factor']):.2f} win_rate={float(row['win_rate_pct']):.2f}% costs={float(row['total_costs']):.2f} data_source={row['data_source']}"
        )
    analysis_path.write_text("\n".join(analysis_lines), encoding="utf-8")
    return csv_path, analysis_path


def export_signal_artifacts(
    config: SystemConfig,
    profile: StrategyProfile,
    features: list[FeatureVector],
    optimized_agents,
) -> tuple[Path, Path]:
    logs_dir = profile_logs_dir(profile.name)
    reports_dir = profile_reports_dir(profile.name)
    signals_path = logs_dir / "signals.csv"
    analysis_path = reports_dir / "signals_analysis.txt"
    agents = build_alpha_agents(optimized_agents, config.risk, profile.name)
    coordinator = AgentCoordinator(agents, consensus_min_confidence=optimized_agents.consensus_min_confidence)
    horizons = (3, 6, 12)
    signal_rows: list[dict[str, object]] = []
    by_setup: dict[str, list[float]] = {}
    by_hour: dict[int, list[float]] = {}
    accepted_by_setup: dict[str, int] = {}

    for index, feature in enumerate(features):
        decision_context = coordinator.evaluate(feature)
        consensus_reasons = set(decision_context.reasons) if decision_context is not None else set()
        for agent in agents:
            signal = agent.on_feature(feature)
            if signal is None or signal.side != Side.BUY or signal.agent_name == "risk_sentinel":
                continue
            forward_returns: dict[int, float | None] = {}
            for horizon in horizons:
                target_index = index + horizon
                if target_index >= len(features):
                    forward_returns[horizon] = None
                    continue
                target_close = features[target_index].values["close"]
                forward_returns[horizon] = ((target_close / feature.values["close"]) - 1.0) * 100.0
            signal_rows.append(
                {
                    "timestamp": feature.timestamp.isoformat(),
                    "hour": int(feature.values.get("hour_of_day", feature.timestamp.hour)),
                    "agent_name": signal.agent_name,
                    "confidence": signal.confidence,
                    "consensus_accepted": signal.agent_name in consensus_reasons,
                    "forward_return_3": forward_returns[3],
                    "forward_return_6": forward_returns[6],
                    "forward_return_12": forward_returns[12],
                    "metadata": signal.metadata,
                }
            )
            if forward_returns[6] is not None:
                by_setup.setdefault(signal.agent_name, []).append(forward_returns[6])
                by_hour.setdefault(int(feature.values.get("hour_of_day", feature.timestamp.hour)), []).append(forward_returns[6])
            if signal.agent_name in consensus_reasons:
                accepted_by_setup[signal.agent_name] = accepted_by_setup.get(signal.agent_name, 0) + 1

    with signals_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "timestamp",
                "hour",
                "agent_name",
                "confidence",
                "consensus_accepted",
                "forward_return_3_pct",
                "forward_return_6_pct",
                "forward_return_12_pct",
                "metadata",
            ]
        )
        for row in signal_rows:
            writer.writerow(
                [
                    row["timestamp"],
                    row["hour"],
                    row["agent_name"],
                    f"{float(row['confidence']):.5f}",
                    row["consensus_accepted"],
                    "" if row["forward_return_3"] is None else f"{float(row['forward_return_3']):.5f}",
                    "" if row["forward_return_6"] is None else f"{float(row['forward_return_6']):.5f}",
                    "" if row["forward_return_12"] is None else f"{float(row['forward_return_12']):.5f}",
                    row["metadata"],
                ]
            )

    analysis_lines = [
        f"Profile: {profile.name}",
        f"Candidate buy signals: {len(signal_rows)}",
        "",
        "By setup (6-bar forward return)",
    ]
    for setup, returns in sorted(by_setup.items(), key=lambda item: mean(item[1]) if item[1] else -999.0):
        wins = sum(1 for value in returns if value > 0)
        analysis_lines.append(
            f"{setup}: signals={len(returns)} accepted={accepted_by_setup.get(setup, 0)} avg_6bar={mean(returns):.3f}% win_rate={wins/len(returns)*100.0:.2f}%"
        )
    analysis_lines.append("")
    analysis_lines.append("By hour (6-bar forward return)")
    for hour, returns in sorted(by_hour.items(), key=lambda item: mean(item[1]) if item[1] else -999.0):
        wins = sum(1 for value in returns if value > 0)
        analysis_lines.append(
            f"{hour}: signals={len(returns)} avg_6bar={mean(returns):.3f}% win_rate={wins/len(returns)*100.0:.2f}%"
        )
    analysis_path.write_text("\n".join(analysis_lines), encoding="utf-8")
    return signals_path, analysis_path


def maybe_place_live_order(config: SystemConfig, features: list[FeatureVector], optimized_agents) -> None:
    if not config.execution.live_trading_enabled:
        return
    agents = build_alpha_agents(optimized_agents, config.risk, config.instrument.profile_name)
    coordinator = AgentCoordinator(agents, consensus_min_confidence=optimized_agents.consensus_min_confidence)
    latest_decision = None
    for feature in features:
        decision = coordinator.decide(feature)
        if decision in {Side.BUY, Side.SELL}:
            latest_decision = (feature, decision)
    if latest_decision is None:
        LOGGER.info("No live MT5 order placed because there is no actionable consensus signal.")
        return

    feature, decision = latest_decision
    client = MT5Client(config.mt5)
    client.initialize()
    try:
        broker = MT5Broker(client=client, starting_equity=client.account_snapshot().equity)
        order = OrderRequest(
            timestamp=feature.timestamp,
            symbol=config.instrument.broker_symbol,
            side=decision,
            quantity=config.execution.order_size,
            reason="multi_agent_consensus",
        )
        broker.submit_order(order, feature.values["close"])
    finally:
        client.shutdown()


def run_profile(config: SystemConfig, profile: StrategyProfile) -> list[str]:
    try:
        configure_profile_execution(config, profile)
        configure_profile_optimization(config, profile)
        features, data_source = load_features(config, profile)
        optimized_agents = SimpleParameterOptimizer(
            config.optimization,
            config.execution,
            config.risk,
            profile.name,
        ).fit(features, config.agents)
        LOGGER.info("profile=%s optimized agent config=%s", profile.name, optimized_agents)
        engine = build_system(config, optimized_agents)
        result = asyncio.run(engine.run(features, sleep_seconds=config.execution.bar_interval_seconds))
        trades_path, analysis_path = export_trade_artifacts(profile, result)
        shadow_csv_path, shadow_analysis_path = export_shadow_execution_artifacts(config, profile, features, optimized_agents)
        signals_path, signals_analysis_path = export_signal_artifacts(config, profile, features, optimized_agents)
        maybe_place_live_order(config, features, optimized_agents)
        report = build_ftmo_report(result, config.execution.initial_cash, config.risk, config.ftmo, config.instrument)
        artifacts = ProfileArtifacts(
            trade_log=trades_path,
            trade_analysis=analysis_path,
            signal_log=signals_path,
            signal_analysis=signals_analysis_path,
            shadow_log=shadow_csv_path,
            shadow_analysis=shadow_analysis_path,
        )
        analysis_package = build_profile_analysis(
            profile=profile,
            result=result,
            report=report,
            artifacts=artifacts,
            ai_config=config.ai,
        )
        ai_summary_path, next_experiment_path = export_ai_artifacts(profile, analysis_package)
        experiment_store = ExperimentStore(config.ai.experiment_database_path)
        experiment_id = experiment_store.record_experiment(
            profile=profile,
            result=result,
            report=report,
            optimized_agents=optimized_agents,
            artifacts=artifacts,
            local_summary=analysis_package.local_summary,
            ai_summary=analysis_package.ai_summary,
            next_experiments=analysis_package.next_experiments,
        )
        descriptors = describe_profile_agents(optimized_agents, config.risk, profile.name)
        agent_records = build_agent_registry_records(profile.name, artifacts)
        experiment_store.record_agent_registry(experiment_id, agent_records)
        experiment_store.record_agent_lifecycle(
            experiment_id=experiment_id,
            profile=profile,
            descriptors=descriptors,
            registry_records=agent_records,
            optimized_agents=optimized_agents,
        )
        registry_text = render_agent_registry(agent_records, profile.name)
        registry_path = export_agent_registry_artifact(profile, registry_text)
        catalog_text = render_agent_catalog(profile.name, experiment_store.list_agent_catalog(profile.name))
        catalog_path = export_agent_catalog_artifact(profile, catalog_text)
        current_run, previous_run = experiment_store.compare_latest_runs(profile.name)
        recent_runs = experiment_store.list_recent_experiments(profile.name, limit=config.ai.history_lookback)
        best_run = experiment_store.get_best_experiment(profile.name)
        memory_package = build_experiment_memory_report(
            profile_name=profile.name,
            recent_runs=recent_runs,
            best_run=best_run,
            current_run=current_run,
            previous_run=previous_run,
        )
        history_path, comparison_path = export_memory_artifacts(profile, memory_package)
        LOGGER.info(
            "profile=%s finished ending_equity=%.2f realized_pnl=%.2f trades=%d locked=%s",
            profile.name,
            result.ending_equity,
            result.realized_pnl,
            result.trades,
            result.locked,
        )
        return [
            f"Profile: {profile.name}",
            f"Description: {profile.description}",
            f"Data symbol: {profile.data_symbol}",
            f"Broker symbol: {profile.broker_symbol}",
            f"Data source: {data_source}",
            f"Ending equity: {result.ending_equity:.2f}",
            f"Realized PnL: {result.realized_pnl:.2f}",
            f"Trades: {result.trades}",
            f"Closed trades: {report.closed_trades}",
            f"Win rate: {report.win_rate_pct:.2f}%",
            f"Profit factor: {report.profit_factor:.2f}",
            f"Max drawdown: {report.max_drawdown_pct:.2f}%",
            f"Total costs: {report.total_costs:.2f}",
            f"Trade log: {trades_path}",
            f"Trade analysis: {analysis_path}",
            f"Signal log: {signals_path}",
            f"Signal analysis: {signals_analysis_path}",
            f"Shadow setup log: {shadow_csv_path}" if shadow_csv_path is not None else "Shadow setup log: none",
            f"Shadow setup analysis: {shadow_analysis_path}" if shadow_analysis_path is not None else "Shadow setup analysis: none",
            f"AI summary: {ai_summary_path}",
            f"Next experiments: {next_experiment_path}",
            f"Agent registry: {registry_path}",
            f"Agent catalog: {catalog_path}",
            f"Experiment history: {history_path}",
            f"Run comparison: {comparison_path}",
            f"FTMO pass: {report.passed}",
            f"FTMO reasons: {', '.join(report.reasons) if report.reasons else 'none'}",
            f"Kill-switch triggered: {result.locked}",
        ]
    except Exception as exc:
        LOGGER.exception("profile=%s failed", profile.name)
        return [
            f"Profile: {profile.name}",
            f"Description: {profile.description}",
            f"Data symbol: {profile.data_symbol}",
            f"Broker symbol: {profile.broker_symbol}",
            f"Status: failed",
            f"Reason: {exc}",
        ]


def main() -> int:
    configure_logging()
    config = SystemConfig()
    profiles = resolve_profiles(config.instrument.active_profiles)
    report_lines = ["QuantGenerated run complete"]
    for index, profile in enumerate(profiles):
        report_lines.append("")
        report_lines.extend(run_profile(config, profile))
        if index < len(profiles) - 1 and config.market_data.profile_pause_seconds > 0:
            time.sleep(config.market_data.profile_pause_seconds)
    print("\n".join(report_lines))
    return 0
