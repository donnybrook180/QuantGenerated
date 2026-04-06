from __future__ import annotations

from dataclasses import dataclass, field
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
    cash: float = field(init=False)
    realized_pnl: float = 0.0
    total_costs: float = 0.0
    position: Position = field(default_factory=lambda: Position(symbol=""))
    closed_trade_pnls: list[float] = field(default_factory=list)
    closed_trades: list[ClosedTradeRecord] = field(default_factory=list)
    _open_trade: dict[str, object] | None = None

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
        elif order.side == Side.SELL:
            self.cash += gross - total_cost
            closed_quantity = min(order.quantity, self.position.quantity)
            trade_pnl = (fill_price - self.position.average_price) * closed_quantity - total_cost
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
                            costs=float(self._open_trade.get("entry_costs", 0.0)) + total_cost,
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

    def get_closed_trades(self) -> list[ClosedTradeRecord]:
        return list(self.closed_trades)
