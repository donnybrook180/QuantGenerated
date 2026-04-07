from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Protocol

from quant_system.models import ClosedTradeRecord, FillEvent, OrderRequest, PortfolioSnapshot, Position, Side


class Broker(Protocol):
    def submit_order(self, order: OrderRequest, market_price: float) -> FillEvent:
        raise NotImplementedError

    def snapshot(self, timestamp, mark_price: float) -> PortfolioSnapshot:
        raise NotImplementedError

    def get_position_quantity(self) -> float:
        raise NotImplementedError

    def get_closed_trade_pnls(self) -> list[float]:
        raise NotImplementedError

    def get_total_costs(self) -> float:
        raise NotImplementedError

    def get_closed_trades(self) -> list[ClosedTradeRecord]:
        raise NotImplementedError


@dataclass(slots=True)
class SimulatedBroker:
    initial_cash: float
    fee_bps: float
    commission_per_unit: float
    slippage_bps: float
    spread_points: float = 0.0
    contract_size: float = 1.0
    commission_mode: str = "legacy"
    commission_per_lot: float = 0.0
    commission_notional_pct: float = 0.0
    overnight_cost_per_lot_day: float = 0.0
    cash: float = field(init=False)
    realized_pnl: float = 0.0
    total_costs: float = 0.0
    position: Position = field(default_factory=lambda: Position(symbol=""))
    closed_trade_pnls: list[float] = field(default_factory=list)
    closed_trades: list[ClosedTradeRecord] = field(default_factory=list)
    _open_trade: dict[str, object] | None = None

    def __post_init__(self) -> None:
        self.cash = self.initial_cash

    def _commission_cost(self, order: OrderRequest, fill_price: float) -> float:
        if self.commission_mode == "per_lot":
            return abs(order.quantity) * self.commission_per_lot
        if self.commission_mode == "notional_pct":
            notional = abs(fill_price * order.quantity * self.contract_size)
            return notional * (self.commission_notional_pct / 100.0)
        if self.commission_mode == "none":
            return 0.0
        return abs(order.quantity) * self.commission_per_unit

    def _overnight_cost(self, order: OrderRequest) -> float:
        if self._open_trade is None or self.overnight_cost_per_lot_day == 0.0:
            return 0.0
        entry_timestamp = self._open_trade["entry_timestamp"]
        days_held = max(0, (order.timestamp.date() - entry_timestamp.date()).days)
        return days_held * abs(order.quantity) * self.overnight_cost_per_lot_day

    def submit_order(self, order: OrderRequest, market_price: float) -> FillEvent:
        if not self.position.symbol:
            self.position.symbol = order.symbol
        slippage_multiplier = 1 + ((self.slippage_bps / 10_000) if order.side == Side.BUY else -(self.slippage_bps / 10_000))
        slipped_price = market_price * slippage_multiplier
        spread_half = self.spread_points / 2.0
        fill_price = slipped_price + spread_half if order.side == Side.BUY else slipped_price - spread_half
        gross_notional = fill_price * order.quantity * self.contract_size
        fee = abs(gross_notional) * (self.fee_bps / 10_000)
        commission = self._commission_cost(order, fill_price)
        overnight_cost = self._overnight_cost(order) if order.side == Side.SELL else 0.0
        total_cost = fee + commission + overnight_cost
        self.total_costs += total_cost

        if order.side == Side.BUY and self.position.quantity < 0:
            closed_quantity = min(order.quantity, abs(self.position.quantity))
            gross_trade_pnl = (self.position.average_price - fill_price) * closed_quantity * self.contract_size
            entry_costs = float(self._open_trade.get("entry_costs", 0.0)) if self._open_trade is not None else 0.0
            trade_pnl = gross_trade_pnl - entry_costs - total_cost
            self.cash += gross_trade_pnl - total_cost
            self.realized_pnl += trade_pnl
            if closed_quantity > 0:
                self.closed_trade_pnls.append(trade_pnl)
                if self._open_trade is not None:
                    entry_bar_index = int(self._open_trade.get("entry_bar_index", -1))
                    exit_bar_index = getattr(order, "bar_index", -1)
                    self.closed_trades.append(
                        ClosedTradeRecord(
                            symbol=order.symbol,
                            entry_timestamp=self._open_trade["entry_timestamp"],
                            exit_timestamp=order.timestamp,
                            entry_price=float(self._open_trade["entry_price"]),
                            exit_price=fill_price,
                            quantity=closed_quantity,
                            pnl=trade_pnl,
                            costs=entry_costs + total_cost,
                            entry_reason=str(self._open_trade.get("entry_reason", "")),
                            exit_reason=order.reason,
                            entry_hour=self._open_trade["entry_timestamp"].hour,
                            exit_hour=order.timestamp.hour,
                            hold_bars=max(0, exit_bar_index - entry_bar_index) if entry_bar_index >= 0 and exit_bar_index >= 0 else 0,
                            entry_confidence=float(self._open_trade.get("entry_confidence", 0.0)),
                            entry_metadata=dict(self._open_trade.get("entry_metadata", {})),
                        )
                    )
                    self._open_trade = None
            self.position.quantity += order.quantity
            if self.position.quantity >= 0:
                self.position.quantity = 0.0
                self.position.average_price = 0.0
        elif order.side == Side.BUY:
            self.cash -= total_cost
            new_quantity = self.position.quantity + order.quantity
            if new_quantity:
                self.position.average_price = (
                    (self.position.average_price * self.position.quantity) + (fill_price * order.quantity)
                ) / new_quantity
            self.position.quantity = new_quantity
            self._open_trade = {
                "entry_timestamp": order.timestamp,
                "entry_price": fill_price,
                "quantity": order.quantity,
                "entry_reason": order.reason,
                "entry_confidence": getattr(order, "confidence", 0.0),
                "entry_metadata": getattr(order, "metadata", {}),
                "entry_bar_index": getattr(order, "bar_index", -1),
                "entry_costs": total_cost,
            }
        elif order.side == Side.SELL and self.position.quantity > 0:
            closed_quantity = min(order.quantity, self.position.quantity)
            gross_trade_pnl = (fill_price - self.position.average_price) * closed_quantity * self.contract_size
            entry_costs = float(self._open_trade.get("entry_costs", 0.0)) if self._open_trade is not None else 0.0
            trade_pnl = gross_trade_pnl - entry_costs - total_cost
            self.cash += gross_trade_pnl - total_cost
            self.realized_pnl += trade_pnl
            if closed_quantity > 0:
                self.closed_trade_pnls.append(trade_pnl)
                if self._open_trade is not None:
                    entry_bar_index = int(self._open_trade.get("entry_bar_index", -1))
                    exit_bar_index = getattr(order, "bar_index", -1)
                    self.closed_trades.append(
                        ClosedTradeRecord(
                            symbol=order.symbol,
                            entry_timestamp=self._open_trade["entry_timestamp"],
                            exit_timestamp=order.timestamp,
                            entry_price=float(self._open_trade["entry_price"]),
                            exit_price=fill_price,
                            quantity=closed_quantity,
                            pnl=trade_pnl,
                            costs=entry_costs + total_cost,
                            entry_reason=str(self._open_trade.get("entry_reason", "")),
                            exit_reason=order.reason,
                            entry_hour=self._open_trade["entry_timestamp"].hour,
                            exit_hour=order.timestamp.hour,
                            hold_bars=max(0, exit_bar_index - entry_bar_index) if entry_bar_index >= 0 and exit_bar_index >= 0 else 0,
                            entry_confidence=float(self._open_trade.get("entry_confidence", 0.0)),
                            entry_metadata=dict(self._open_trade.get("entry_metadata", {})),
                        )
                    )
                    self._open_trade = None
            self.position.quantity -= order.quantity
            if self.position.quantity <= 0:
                self.position.quantity = 0.0
                self.position.average_price = 0.0
        elif order.side == Side.SELL:
            self.cash -= total_cost
            new_quantity = self.position.quantity - order.quantity
            if abs(new_quantity):
                self.position.average_price = (
                    (self.position.average_price * abs(self.position.quantity)) + (fill_price * order.quantity)
                ) / abs(new_quantity)
            self.position.quantity = new_quantity
            self._open_trade = {
                "entry_timestamp": order.timestamp,
                "entry_price": fill_price,
                "quantity": order.quantity,
                "entry_reason": order.reason,
                "entry_confidence": getattr(order, "confidence", 0.0),
                "entry_metadata": getattr(order, "metadata", {}),
                "entry_bar_index": getattr(order, "bar_index", -1),
                "entry_costs": total_cost,
            }

        return FillEvent(
            timestamp=order.timestamp,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            costs=total_cost,
            metadata={},
        )

    def snapshot(self, timestamp, mark_price: float) -> PortfolioSnapshot:
        spread_half = self.spread_points / 2.0
        bid_mark = mark_price - spread_half
        ask_mark = mark_price + spread_half
        if self.position.quantity > 0:
            unrealized = (bid_mark - self.position.average_price) * self.position.quantity * self.contract_size
        elif self.position.quantity < 0:
            unrealized = (self.position.average_price - ask_mark) * abs(self.position.quantity) * self.contract_size
        else:
            unrealized = 0.0
        equity = self.cash + unrealized
        drawdown = max(0.0, (self.initial_cash - equity) / self.initial_cash)
        return PortfolioSnapshot(
            timestamp=timestamp,
            cash=self.cash,
            equity=equity,
            unrealized_pnl=unrealized,
            realized_pnl=self.realized_pnl,
            drawdown=drawdown,
        )

    def get_position_quantity(self) -> float:
        return self.position.quantity

    def get_closed_trade_pnls(self) -> list[float]:
        return list(self.closed_trade_pnls)

    def get_total_costs(self) -> float:
        return self.total_costs

    def get_closed_trades(self) -> list[ClosedTradeRecord]:
        return list(self.closed_trades)
