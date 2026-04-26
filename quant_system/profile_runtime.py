from __future__ import annotations

from quant_system.agents.factory import build_alpha_agents
from quant_system.config import SystemConfig
from quant_system.execution.broker import SimulatedBroker
from quant_system.execution.engine import AgentCoordinator, EventDrivenEngine
from quant_system.integrations.mt5 import MT5Broker, MT5Client
from quant_system.models import FeatureVector, OrderRequest, Side
from quant_system.monitoring.heartbeat import HeartbeatMonitor
from quant_system.risk.limits import RiskManager


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
            venue_key=str(config.mt5.prop_broker),
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
