from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from quant_system.models import FillEvent, OrderRequest, PortfolioSnapshot, Position, Side


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


@dataclass(slots=True)
class SimulatedBroker:
    initial_cash: float
    fee_bps: float
    commission_per_unit: float
    slippage_bps: float
    cash: float = field(init=False)
    realized_pnl: float = 0.0
    total_costs: float = 0.0
    position: Position = field(default_factory=lambda: Position(symbol=""))
    closed_trade_pnls: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cash = self.initial_cash

    def submit_order(self, order: OrderRequest, market_price: float) -> FillEvent:
        if not self.position.symbol:
            self.position.symbol = order.symbol
        multiplier = 1 + ((self.slippage_bps / 10_000) if order.side == Side.BUY else -(self.slippage_bps / 10_000))
        fill_price = market_price * multiplier
        gross = fill_price * order.quantity
        fee = abs(gross) * (self.fee_bps / 10_000)
        commission = abs(order.quantity) * self.commission_per_unit
        total_cost = fee + commission
        self.total_costs += total_cost

        if order.side == Side.BUY:
            self.cash -= gross + total_cost
            new_quantity = self.position.quantity + order.quantity
            if new_quantity:
                self.position.average_price = (
                    (self.position.average_price * self.position.quantity) + gross
                ) / new_quantity
            self.position.quantity = new_quantity
        elif order.side == Side.SELL:
            self.cash += gross - total_cost
            closed_quantity = min(order.quantity, self.position.quantity)
            trade_pnl = (fill_price - self.position.average_price) * closed_quantity - total_cost
            self.realized_pnl += trade_pnl
            if closed_quantity > 0:
                self.closed_trade_pnls.append(trade_pnl)
            self.position.quantity -= order.quantity
            if self.position.quantity <= 0:
                self.position.quantity = 0.0
                self.position.average_price = 0.0

        return FillEvent(
            timestamp=order.timestamp,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            costs=total_cost,
        )

    def snapshot(self, timestamp, mark_price: float) -> PortfolioSnapshot:
        unrealized = (mark_price - self.position.average_price) * self.position.quantity
        equity = self.cash + (self.position.quantity * mark_price)
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
