from __future__ import annotations

import asyncio
import csv
import logging
from pathlib import Path
from statistics import mean
import copy

from quant_system.ai.analysis import build_profile_analysis
from quant_system.ai.history import build_experiment_memory_report
from quant_system.ai.models import ProfileArtifacts
from quant_system.ai.storage import ExperimentStore
from quant_system.agents.factory import build_alpha_agents, build_shadow_candidate_agents
from quant_system.config import SystemConfig
from quant_system.data.market_data import DuckDBMarketDataStore
from quant_system.evaluation.report import build_ftmo_report
from quant_system.execution.broker import SimulatedBroker
from quant_system.execution.engine import AgentCoordinator, EventDrivenEngine
from quant_system.integrations.mt5 import MT5Broker, MT5Client
from quant_system.integrations.polygon_data import PolygonDataClient
from quant_system.logging_utils import configure_logging
from quant_system.monitoring.heartbeat import HeartbeatMonitor
from quant_system.optimization.walk_forward import SimpleParameterOptimizer
from quant_system.models import FeatureVector
from quant_system.models import MarketBar, OrderRequest, Side
from quant_system.profiles import StrategyProfile, resolve_profiles
from quant_system.research.features import build_feature_library
from quant_system.risk.limits import RiskManager


LOGGER = logging.getLogger(__name__)
ARTIFACTS_DIR = Path("artifacts")


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
        config.execution.fee_bps = 0.0
        config.execution.commission_per_unit = 0.0
        config.execution.slippage_bps = 0.5
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
        config.execution.fee_bps = 0.0
        config.execution.commission_per_unit = 0.0
        config.execution.slippage_bps = 0.5
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


def load_features(config: SystemConfig, profile: StrategyProfile) -> list[FeatureVector]:
    config.polygon.symbol = profile.data_symbol
    if profile.name == "ger40_orb":
        config.polygon.history_days = max(config.polygon.history_days, 365)
    elif profile.name == "us500_trend":
        config.polygon.history_days = max(config.polygon.history_days, 365)
    config.mt5.symbol = profile.broker_symbol
    client = PolygonDataClient(config.polygon)
    store = DuckDBMarketDataStore(config.mt5.database_path)
    bars = client.fetch_bars()
    timeframe = f"{config.polygon.multiplier}_{config.polygon.timespan}"
    scoped_timeframe = f"{profile.name}_{timeframe}"
    if profile.name == "ger40_orb":
        bars = scale_proxy_bars(bars, multiplier=500.0)
    store.upsert_bars(bars, timeframe=scoped_timeframe, source="polygon")
    persisted_bars = store.load_bars(config.polygon.symbol, scoped_timeframe, len(bars))
    if not persisted_bars:
        raise RuntimeError("No Polygon bars were loaded into DuckDB.")
    config.instrument.profile_name = profile.name
    config.instrument.data_symbol = config.polygon.symbol
    config.instrument.broker_symbol = config.mt5.symbol
    config.execution.symbol = config.polygon.symbol
    return build_feature_library(persisted_bars)


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


def load_shadow_features(config: SystemConfig, profile: StrategyProfile) -> list[FeatureVector]:
    if profile.name != "us100_trend":
        return load_features(config, profile)

    shadow_config = copy.deepcopy(config)
    shadow_config.polygon.symbol = profile.data_symbol
    shadow_config.polygon.timespan = "minute"
    shadow_config.polygon.multiplier = 1
    shadow_config.polygon.history_days = max(config.polygon.history_days, 45)
    shadow_config.mt5.symbol = profile.broker_symbol
    client = PolygonDataClient(shadow_config.polygon)
    store = DuckDBMarketDataStore(shadow_config.mt5.database_path)
    bars = client.fetch_bars()
    timeframe = f"{shadow_config.polygon.multiplier}_{shadow_config.polygon.timespan}"
    scoped_timeframe = f"{profile.name}_shadow_{timeframe}"
    store.upsert_bars(bars, timeframe=scoped_timeframe, source="polygon")
    persisted_bars = store.load_bars(shadow_config.polygon.symbol, scoped_timeframe, len(bars))
    if not persisted_bars:
        raise RuntimeError("No shadow Polygon bars were loaded into DuckDB.")
    return build_feature_library(persisted_bars)


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
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    summary_path = ARTIFACTS_DIR / f"{profile.name}_ai_summary.txt"
    experiments_path = ARTIFACTS_DIR / f"{profile.name}_next_experiment.txt"

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
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    history_path = ARTIFACTS_DIR / f"{profile.name}_experiment_history.txt"
    comparison_path = ARTIFACTS_DIR / f"{profile.name}_run_comparison.txt"
    history_path.write_text(package.history_summary, encoding="utf-8")
    comparison_path.write_text(package.comparison_summary, encoding="utf-8")
    return history_path, comparison_path


def export_closed_trade_artifacts(closed_trades, realized_pnl: float, artifact_prefix: str) -> tuple[Path, Path]:
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    trades_path = ARTIFACTS_DIR / f"{artifact_prefix}_trades.csv"
    analysis_path = ARTIFACTS_DIR / f"{artifact_prefix}_analysis.txt"

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
        f"Artifact: {artifact_prefix}",
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
    shadow_features = load_shadow_features(config, profile)

    ARTIFACTS_DIR.mkdir(exist_ok=True)
    csv_path = ARTIFACTS_DIR / f"{profile.name}_shadow_setups.csv"
    analysis_path = ARTIFACTS_DIR / f"{profile.name}_shadow_setups.txt"
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
            f"{row['setup_name']}: pnl={float(row['realized_pnl']):.2f} closed={row['closed_trades']} pf={float(row['profit_factor']):.2f} win_rate={float(row['win_rate_pct']):.2f}% costs={float(row['total_costs']):.2f}"
        )
    analysis_path.write_text("\n".join(analysis_lines), encoding="utf-8")
    return csv_path, analysis_path


def export_signal_artifacts(
    config: SystemConfig,
    profile: StrategyProfile,
    features: list[FeatureVector],
    optimized_agents,
) -> tuple[Path, Path]:
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    signals_path = ARTIFACTS_DIR / f"{profile.name}_signals.csv"
    analysis_path = ARTIFACTS_DIR / f"{profile.name}_signals_analysis.txt"
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
        features = load_features(config, profile)
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
        experiment_store.record_experiment(
            profile=profile,
            result=result,
            report=report,
            optimized_agents=optimized_agents,
            artifacts=artifacts,
            local_summary=analysis_package.local_summary,
            ai_summary=analysis_package.ai_summary,
            next_experiments=analysis_package.next_experiments,
        )
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
    for profile in profiles:
        report_lines.append("")
        report_lines.extend(run_profile(config, profile))
    print("\n".join(report_lines))
    return 0
