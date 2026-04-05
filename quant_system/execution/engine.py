from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
import logging

from quant_system.agents.base import Agent
from quant_system.execution.broker import Broker
from quant_system.models import FeatureVector, OrderRequest, Side
from quant_system.monitoring.heartbeat import HeartbeatMonitor
from quant_system.risk.limits import RiskManager


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ExecutionResult:
    ending_equity: float
    realized_pnl: float
    trades: int
    locked: bool
    max_drawdown: float
    win_rate_pct: float
    profit_factor: float
    total_costs: float
    closed_trade_pnls: list[float]


class AgentCoordinator:
    def __init__(self, agents: list[Agent], consensus_min_confidence: float = 1.0) -> None:
        self.agents = agents
        self.consensus_min_confidence = consensus_min_confidence

    def decide(self, feature: FeatureVector) -> Side | None:
        votes: Counter[Side] = Counter()
        confidences: Counter[Side] = Counter()
        veto = False
        for agent in self.agents:
            signal = agent.on_feature(feature)
            if signal is None:
                continue
            LOGGER.debug(
                "signal agent=%s side=%s confidence=%.3f meta=%s",
                signal.agent_name,
                signal.side.value,
                signal.confidence,
                signal.metadata,
            )
            if signal.agent_name == "risk_sentinel" and signal.side == Side.FLAT:
                veto = True
            if signal.side != Side.FLAT:
                votes[signal.side] += 1
                confidences[signal.side] += signal.confidence
        if veto or not votes:
            return None
        decision, count = votes.most_common(1)[0]
        if len(votes) > 1:
            return None
        if count < 1 or confidences[decision] < self.consensus_min_confidence:
            return None
        return decision


class EventDrivenEngine:
    def __init__(
        self,
        coordinator: AgentCoordinator,
        broker: Broker,
        risk_manager: RiskManager,
        heartbeat: HeartbeatMonitor,
        quantity: float = 1.0,
    ) -> None:
        self.coordinator = coordinator
        self.broker = broker
        self.risk_manager = risk_manager
        self.heartbeat = heartbeat
        self.quantity = quantity
        self.min_bars_between_trades = 0
        self.max_holding_bars = 0
        self._last_trade_index: int | None = None
        self._entry_index: int | None = None

    async def run(
        self,
        features: list[FeatureVector],
        sleep_seconds: float = 0.0,
    ) -> ExecutionResult:
        stop_event = asyncio.Event()
        monitor_task = asyncio.create_task(self.heartbeat.watch(stop_event))
        trades = 0
        max_drawdown = 0.0
        try:
            for index, feature in enumerate(features):
                self.heartbeat.beat()
                decision = self.coordinator.decide(feature)
                snapshot = self.broker.snapshot(feature.timestamp, feature.values["close"])
                max_drawdown = max(max_drawdown, snapshot.drawdown)
                if self.risk_manager.on_snapshot(snapshot):
                    LOGGER.error("Kill-switch triggered at %s", feature.timestamp.isoformat())
                    break
                current_quantity = self.broker.get_position_quantity()
                if (
                    current_quantity > 0
                    and self.max_holding_bars > 0
                    and self._entry_index is not None
                    and (index - self._entry_index) >= self.max_holding_bars
                ):
                    decision = Side.SELL
                if decision in {Side.BUY, Side.SELL}:
                    if (
                        self._last_trade_index is not None
                        and (index - self._last_trade_index) < self.min_bars_between_trades
                    ):
                        continue
                    if decision == Side.BUY and current_quantity > 0:
                        continue
                    if decision == Side.SELL and current_quantity <= 0:
                        continue
                    order = OrderRequest(
                        timestamp=feature.timestamp,
                        symbol=feature.symbol,
                        side=decision,
                        quantity=current_quantity if decision == Side.SELL else self.quantity,
                        reason="agent_consensus",
                    )
                    if self.risk_manager.check_order(order, snapshot):
                        fill = self.broker.submit_order(order, feature.values["close"])
                        trades += 1
                        self._last_trade_index = index
                        if fill.side == Side.BUY:
                            self._entry_index = index
                        elif fill.side == Side.SELL:
                            self._entry_index = None
                        LOGGER.info(
                            "fill side=%s qty=%.2f price=%.2f",
                            fill.side.value,
                            fill.quantity,
                            fill.price,
                        )
                if sleep_seconds:
                    await asyncio.sleep(sleep_seconds)
        finally:
            stop_event.set()
            await monitor_task
        final_snapshot = self.broker.snapshot(features[-1].timestamp, features[-1].values["close"])
        closed_trade_pnls = self.broker.get_closed_trade_pnls()
        wins = [pnl for pnl in closed_trade_pnls if pnl > 0]
        losses = [pnl for pnl in closed_trade_pnls if pnl < 0]
        win_rate_pct = (len(wins) / len(closed_trade_pnls) * 100.0) if closed_trade_pnls else 0.0
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
        return ExecutionResult(
            ending_equity=final_snapshot.equity,
            realized_pnl=final_snapshot.realized_pnl,
            trades=trades,
            locked=self.risk_manager.locked_until is not None,
            max_drawdown=max_drawdown,
            win_rate_pct=win_rate_pct,
            profit_factor=profit_factor,
            total_costs=self.broker.get_total_costs(),
            closed_trade_pnls=closed_trade_pnls,
        )
