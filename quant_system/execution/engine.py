from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
import logging

from quant_system.agents.base import Agent
from quant_system.execution.broker import Broker
from quant_system.models import ClosedTradeRecord, DecisionContext, FeatureVector, OrderRequest, Side
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
    closed_trades: list[ClosedTradeRecord]


class AgentCoordinator:
    def __init__(self, agents: list[Agent], consensus_min_confidence: float = 1.0) -> None:
        self.agents = agents
        self.consensus_min_confidence = consensus_min_confidence

    def evaluate(self, feature: FeatureVector) -> DecisionContext | None:
        votes: Counter[Side] = Counter()
        confidences: Counter[Side] = Counter()
        reasons: dict[Side, list[str]] = {Side.BUY: [], Side.SELL: []}
        metadata: dict[Side, dict[str, float | str]] = {Side.BUY: {}, Side.SELL: {}}
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
            if signal.side == Side.FLAT and (signal.agent_name == "risk_sentinel" or "veto" in signal.metadata):
                veto = True
            if signal.side != Side.FLAT:
                votes[signal.side] += 1
                confidences[signal.side] += signal.confidence
                reasons[signal.side].append(signal.agent_name)
                metadata[signal.side].update(signal.metadata)
        if veto or not votes:
            return None
        decision, count = votes.most_common(1)[0]
        if len(votes) > 1:
            return None
        if count < 1 or confidences[decision] < self.consensus_min_confidence:
            return None
        return DecisionContext(
            side=decision,
            confidence=confidences[decision],
            reasons=tuple(reasons[decision]),
            metadata=metadata[decision],
        )

    def decide(self, feature: FeatureVector) -> Side | None:
        context = self.evaluate(feature)
        return context.side if context is not None else None


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
        self.stop_loss_atr_multiple = 0.0
        self.take_profit_atr_multiple = 0.0
        self.break_even_atr_multiple = 0.0
        self.trailing_stop_atr_multiple = 0.0
        self.stale_breakout_bars = 0
        self.stale_breakout_atr_fraction = 0.0
        self.structure_exit_bars = 0
        self.min_confidence_quantity_scale = 1.0
        self.max_confidence_quantity_scale = 1.0
        self.min_confidence_target_scale = 1.0
        self.max_confidence_target_scale = 1.0
        self._last_trade_index: int | None = None
        self._entry_index: int | None = None
        self._entry_price: float | None = None
        self._entry_atr_proxy: float | None = None
        self._extreme_price: float | None = None
        self._entry_decision: DecisionContext | None = None
        self._entry_side: Side | None = None

    def _reset_entry_state(self) -> None:
        self._entry_index = None
        self._entry_price = None
        self._entry_atr_proxy = None
        self._extreme_price = None
        self._entry_decision = None
        self._entry_side = None

    def _set_entry_state(self, index: int, fill_price: float, feature: FeatureVector, decision_context: DecisionContext | None, side: Side) -> None:
        self._entry_index = index
        self._entry_price = fill_price
        self._entry_atr_proxy = max(feature.values.get("atr_proxy", 0.0), 0.0001)
        self._extreme_price = fill_price
        self._entry_decision = decision_context
        self._entry_side = side

    def _infer_entry_mode(self, decision_context: DecisionContext | None) -> str:
        if decision_context is None:
            return ""
        return str(decision_context.metadata.get("position_intent", "") or "")

    def _risk_exit_reason(self, feature: FeatureVector, current_quantity: float) -> str | None:
        if current_quantity == 0 or self._entry_price is None:
            return None
        close = feature.values["close"]
        atr_proxy = self._entry_atr_proxy or feature.values.get("atr_proxy", 0.0)
        if atr_proxy <= 0:
            return None
        stop_distance = self._entry_price * atr_proxy * self.stop_loss_atr_multiple
        entry_confidence = self._entry_decision.confidence if self._entry_decision is not None else 1.0
        target_scale = self.min_confidence_target_scale + (
            (self.max_confidence_target_scale - self.min_confidence_target_scale) * entry_confidence
        )
        target_distance = self._entry_price * atr_proxy * self.take_profit_atr_multiple * target_scale
        break_even_distance = self._entry_price * atr_proxy * self.break_even_atr_multiple
        trailing_distance = self._entry_price * atr_proxy * self.trailing_stop_atr_multiple
        if current_quantity > 0:
            stop_price = self._entry_price - stop_distance
            target_price = self._entry_price + target_distance
            self._extreme_price = close if self._extreme_price is None else max(self._extreme_price, close)
            if self.stop_loss_atr_multiple > 0 and close <= stop_price:
                return "stop_loss"
            if self.take_profit_atr_multiple > 0 and close >= target_price:
                return "take_profit"
            if (
                self.break_even_atr_multiple > 0
                and self.trailing_stop_atr_multiple > 0
                and self._extreme_price >= self._entry_price + break_even_distance
                and close <= max(self._entry_price, self._extreme_price - trailing_distance)
            ):
                return "trailing_stop"
        else:
            stop_price = self._entry_price + stop_distance
            target_price = self._entry_price - target_distance
            self._extreme_price = close if self._extreme_price is None else min(self._extreme_price, close)
            if self.stop_loss_atr_multiple > 0 and close >= stop_price:
                return "stop_loss"
            if self.take_profit_atr_multiple > 0 and close <= target_price:
                return "take_profit"
            if (
                self.break_even_atr_multiple > 0
                and self.trailing_stop_atr_multiple > 0
                and self._extreme_price <= self._entry_price - break_even_distance
                and close >= min(self._entry_price, self._extreme_price + trailing_distance)
            ):
                return "trailing_stop"
        return None

    def _stale_breakout_exit_reason(self, feature: FeatureVector, index: int, current_quantity: float) -> str | None:
        if (
            current_quantity == 0
            or self._entry_index is None
            or self._entry_price is None
            or self._entry_decision is None
            or self.stale_breakout_bars <= 0
            or (index - self._entry_index) < self.stale_breakout_bars
        ):
            return None
        close = feature.values["close"]
        atr_proxy = self._entry_atr_proxy or feature.values.get("atr_proxy", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        entry_confidence = self._entry_decision.confidence
        holding_bars = index - self._entry_index
        if current_quantity > 0:
            breakout_high = self._entry_decision.metadata.get("breakout_high")
            breakout_level = float(breakout_high) if breakout_high is not None else self._entry_price
            min_progress = self._entry_price + (self._entry_price * atr_proxy * self.stale_breakout_atr_fraction)
            if close < breakout_level and (momentum_20 <= 0 or trend_strength <= 0):
                return "stale_breakout"
            if (
                entry_confidence < 0.8
                and holding_bars >= self.stale_breakout_bars
                and close < self._entry_price
                and (self._extreme_price or self._entry_price) < min_progress
            ):
                return "stale_breakout"
            if close < min_progress and holding_bars >= (self.stale_breakout_bars + 2) and (momentum_20 <= 0 or trend_strength <= 0):
                return "stale_breakout"
        else:
            breakout_low = self._entry_decision.metadata.get("breakout_low")
            rebound_high = self._entry_decision.metadata.get("rebound_high")
            breakout_level = float(breakout_low) if breakout_low is not None else self._entry_price
            invalidate_level = float(rebound_high) if rebound_high is not None else self._entry_price
            min_progress = self._entry_price - (self._entry_price * atr_proxy * self.stale_breakout_atr_fraction)
            if close > invalidate_level and (momentum_20 >= 0 or trend_strength >= 0):
                return "stale_breakout"
            if (
                entry_confidence < 0.8
                and holding_bars >= self.stale_breakout_bars
                and close > self._entry_price
                and (self._extreme_price or self._entry_price) > min_progress
            ):
                return "stale_breakout"
            if close > min_progress and holding_bars >= (self.stale_breakout_bars + 2) and (momentum_20 >= 0 or trend_strength >= 0):
                return "stale_breakout"
        return None

    def _structure_exit_reason(self, feature: FeatureVector, index: int, current_quantity: float) -> str | None:
        if (
            current_quantity == 0
            or self._entry_index is None
            or self._entry_price is None
            or self._entry_decision is None
            or self.structure_exit_bars <= 0
            or (index - self._entry_index) < self.structure_exit_bars
        ):
            return None
        close = feature.values["close"]
        momentum_20 = feature.values.get("momentum_20", 0.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        if current_quantity > 0:
            breakout_high = self._entry_decision.metadata.get("breakout_high")
            breakout_level = float(breakout_high) if breakout_high is not None else self._entry_price
            if close < breakout_level and momentum_20 <= 0:
                return "structure_exit"
            if close < self._entry_price and trend_strength <= 0:
                return "structure_exit"
        else:
            breakout_low = self._entry_decision.metadata.get("breakout_low")
            invalidate_level = float(breakout_low) if breakout_low is not None else self._entry_price
            rebound_high = self._entry_decision.metadata.get("rebound_high")
            if rebound_high is not None:
                invalidate_level = float(rebound_high)
            if close > invalidate_level and momentum_20 >= 0:
                return "structure_exit"
            if close > self._entry_price and trend_strength >= 0:
                return "structure_exit"
        return None

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
                decision_context = self.coordinator.evaluate(feature)
                decision = decision_context.side if decision_context is not None else None
                exit_reason = "signal_exit"
                snapshot = self.broker.snapshot(feature.timestamp, feature.values["close"])
                max_drawdown = max(max_drawdown, snapshot.drawdown)
                if self.risk_manager.on_snapshot(snapshot):
                    LOGGER.error("Kill-switch triggered at %s", feature.timestamp.isoformat())
                    break
                current_quantity = self.broker.get_position_quantity()
                risk_exit_reason = self._risk_exit_reason(feature, current_quantity)
                stale_exit_reason = self._stale_breakout_exit_reason(feature, index, current_quantity)
                structure_exit_reason = self._structure_exit_reason(feature, index, current_quantity)
                if (
                    current_quantity != 0
                    and self.max_holding_bars > 0
                    and self._entry_index is not None
                    and (index - self._entry_index) >= self.max_holding_bars
                    and snapshot.unrealized_pnl <= 0
                ):
                    decision = Side.SELL if current_quantity > 0 else Side.BUY
                    exit_reason = "time_stop"
                elif structure_exit_reason is not None:
                    decision = Side.SELL if current_quantity > 0 else Side.BUY
                    exit_reason = structure_exit_reason
                elif stale_exit_reason is not None:
                    decision = Side.SELL if current_quantity > 0 else Side.BUY
                    exit_reason = stale_exit_reason
                elif risk_exit_reason is not None:
                    decision = Side.SELL if current_quantity > 0 else Side.BUY
                    exit_reason = risk_exit_reason
                if decision in {Side.BUY, Side.SELL}:
                    entry_mode = self._infer_entry_mode(decision_context)
                    if (
                        current_quantity == 0
                        and decision == Side.BUY
                        and entry_mode != "short_exit"
                        and
                        self._last_trade_index is not None
                        and (index - self._last_trade_index) < self.min_bars_between_trades
                    ):
                        continue
                    if current_quantity == 0 and decision == Side.SELL and entry_mode != "short_entry":
                        continue
                    if decision == Side.BUY and current_quantity > 0:
                        continue
                    if decision == Side.SELL and current_quantity < 0:
                        continue
                    order_quantity = self.quantity
                    order_reason = exit_reason
                    order_confidence = 0.0
                    order_metadata = {"exit_reason": exit_reason}
                    if current_quantity > 0 and decision == Side.SELL:
                        order_quantity = current_quantity
                    elif current_quantity < 0 and decision == Side.BUY:
                        order_quantity = abs(current_quantity)
                    elif current_quantity == 0 and decision_context is not None:
                        order_quantity = self.quantity * (
                            self.min_confidence_quantity_scale + (
                                (self.max_confidence_quantity_scale - self.min_confidence_quantity_scale) * decision_context.confidence
                            )
                        )
                        order_reason = "+".join(decision_context.reasons) if decision_context.reasons else order_reason
                        order_confidence = decision_context.confidence
                        order_metadata = dict(decision_context.metadata)
                    order = OrderRequest(
                        timestamp=feature.timestamp,
                        symbol=feature.symbol,
                        side=decision,
                        quantity=order_quantity,
                        reason=order_reason,
                        confidence=order_confidence,
                        metadata=order_metadata,
                        bar_index=index,
                    )
                    if self.risk_manager.check_order(order, snapshot):
                        fill = self.broker.submit_order(order, feature.values["close"])
                        trades += 1
                        self._last_trade_index = index
                        new_quantity = self.broker.get_position_quantity()
                        if current_quantity == 0 and new_quantity != 0:
                            self._set_entry_state(index, fill.price, feature, decision_context, fill.side)
                        elif current_quantity != 0 and new_quantity == 0:
                            self._reset_entry_state()
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
        final_price = features[-1].values["close"]
        final_qty = self.broker.get_position_quantity()
        if final_qty != 0:
            final_order = OrderRequest(
                timestamp=features[-1].timestamp,
                symbol=features[-1].symbol,
                side=Side.SELL if final_qty > 0 else Side.BUY,
                quantity=abs(final_qty),
                reason="end_of_run",
                metadata={"exit_reason": "end_of_run"},
                bar_index=len(features) - 1,
            )
            final_snapshot = self.broker.snapshot(features[-1].timestamp, final_price)
            if self.risk_manager.check_order(final_order, final_snapshot):
                self.broker.submit_order(final_order, final_price)
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
            closed_trades=self.broker.get_closed_trades(),
        )
