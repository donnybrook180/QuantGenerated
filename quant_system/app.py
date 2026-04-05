from __future__ import annotations

import asyncio
import logging

from quant_system.agents.factory import build_alpha_agents
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
from quant_system.models import OrderRequest, Side
from quant_system.research.features import build_feature_library
from quant_system.risk.limits import RiskManager


LOGGER = logging.getLogger(__name__)


def load_features(config: SystemConfig) -> list[FeatureVector]:
    client = PolygonDataClient(config.polygon)
    store = DuckDBMarketDataStore(config.mt5.database_path)
    bars = client.fetch_bars()
    timeframe = f"{config.polygon.multiplier}_{config.polygon.timespan}"
    store.upsert_bars(bars, timeframe=timeframe, source="polygon")
    persisted_bars = store.load_bars(config.polygon.symbol, timeframe, len(bars))
    if not persisted_bars:
        raise RuntimeError("No Polygon bars were loaded into DuckDB.")
    config.instrument.data_symbol = config.polygon.symbol
    config.instrument.broker_symbol = config.mt5.symbol
    config.execution.symbol = config.polygon.symbol
    return build_feature_library(persisted_bars)


def build_system(
    config: SystemConfig,
    optimized_agents,
) -> EventDrivenEngine:
    agents = build_alpha_agents(optimized_agents, config.risk)
    broker = SimulatedBroker(
        initial_cash=config.execution.initial_cash,
        fee_bps=config.execution.fee_bps,
        commission_per_unit=config.execution.commission_per_unit,
        slippage_bps=config.execution.slippage_bps,
    )
    engine = EventDrivenEngine(
        coordinator=AgentCoordinator(agents, consensus_min_confidence=optimized_agents.consensus_min_confidence),
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
    return engine


def maybe_place_live_order(config: SystemConfig, features: list[FeatureVector], optimized_agents) -> None:
    if not config.execution.live_trading_enabled:
        return
    agents = build_alpha_agents(optimized_agents, config.risk)
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


def main() -> int:
    configure_logging()
    config = SystemConfig()
    features = load_features(config)
    optimized_agents = SimpleParameterOptimizer(
        config.optimization,
        config.execution,
        config.risk,
    ).fit(features, config.agents)
    LOGGER.info("optimized agent config=%s", optimized_agents)
    engine = build_system(config, optimized_agents)
    result = asyncio.run(engine.run(features, sleep_seconds=config.execution.bar_interval_seconds))
    maybe_place_live_order(config, features, optimized_agents)
    report = build_ftmo_report(result, config.execution.initial_cash, config.risk, config.ftmo, config.instrument)
    LOGGER.info(
        "finished ending_equity=%.2f realized_pnl=%.2f trades=%d locked=%s",
        result.ending_equity,
        result.realized_pnl,
        result.trades,
        result.locked,
    )
    print(
        "\n".join(
            [
                "QuantGenerated run complete",
                f"Ending equity: {result.ending_equity:.2f}",
                f"Realized PnL: {result.realized_pnl:.2f}",
                f"Trades: {result.trades}",
                f"Closed trades: {report.closed_trades}",
                f"Win rate: {report.win_rate_pct:.2f}%",
                f"Profit factor: {report.profit_factor:.2f}",
                f"Max drawdown: {report.max_drawdown_pct:.2f}%",
                f"Total costs: {report.total_costs:.2f}",
                f"FTMO pass: {report.passed}",
                f"FTMO reasons: {', '.join(report.reasons) if report.reasons else 'none'}",
                f"Kill-switch triggered: {result.locked}",
            ]
        )
    )
    return 0
