from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging

import MetaTrader5 as mt5

from quant_system.config import MT5Config
from quant_system.models import FillEvent, MarketBar, OrderRequest, PortfolioSnapshot, Position, Side


LOGGER = logging.getLogger(__name__)


TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}


class MT5Error(RuntimeError):
    pass


@dataclass(slots=True)
class MT5Client:
    config: MT5Config
    resolved_symbol: str | None = field(default=None, init=False)

    def initialize(self) -> None:
        kwargs: dict[str, object] = {}
        if self.config.terminal_path:
            kwargs["path"] = self.config.terminal_path
        if self.config.login is not None:
            kwargs["login"] = self.config.login
        if self.config.password:
            kwargs["password"] = self.config.password
        if self.config.server:
            kwargs["server"] = self.config.server

        if not mt5.initialize(**kwargs):
            raise MT5Error(f"MT5 initialize failed: {mt5.last_error()}")
        self.resolved_symbol = self._resolve_symbol(self.config.symbol)
        if not mt5.symbol_select(self.resolved_symbol, True):
            raise MT5Error(f"Unable to select symbol {self.resolved_symbol}: {mt5.last_error()}")

    def shutdown(self) -> None:
        mt5.shutdown()

    def _resolve_symbol(self, requested_symbol: str) -> str:
        if mt5.symbol_info(requested_symbol) is not None:
            return requested_symbol

        normalized = requested_symbol.replace(".", "").replace("_", "").lower()
        candidates = mt5.symbols_get()
        if candidates is None:
            raise MT5Error(f"MT5 symbols_get failed: {mt5.last_error()}")

        for symbol in candidates:
            candidate = symbol.name.replace(".", "").replace("_", "").lower()
            if candidate == normalized:
                LOGGER.info("resolved MT5 symbol %s -> %s", requested_symbol, symbol.name)
                return symbol.name
        for symbol in candidates:
            candidate = symbol.name.replace(".", "").replace("_", "").lower()
            if normalized in candidate or candidate in normalized:
                LOGGER.info("resolved MT5 symbol %s -> %s", requested_symbol, symbol.name)
                return symbol.name
        raise MT5Error(f"Unable to resolve symbol {requested_symbol} in MT5 terminal")

    def fetch_bars(self, bar_count: int | None = None) -> list[MarketBar]:
        timeframe_code = TIMEFRAME_MAP[self.config.timeframe]
        count = bar_count or self.config.history_bars
        symbol = self.resolved_symbol or self.config.symbol
        rates = mt5.copy_rates_from_pos(symbol, timeframe_code, 0, count)
        if rates is None:
            raise MT5Error(f"MT5 copy_rates_from_pos failed: {mt5.last_error()}")
        bars = [
            MarketBar(
                timestamp=datetime.fromtimestamp(int(rate["time"]), UTC),
                symbol=symbol,
                open=float(rate["open"]),
                high=float(rate["high"]),
                low=float(rate["low"]),
                close=float(rate["close"]),
                volume=float(rate["tick_volume"]),
            )
            for rate in rates
        ]
        return [bar for bar in bars if bar.close > 0 and bar.high >= bar.low]

    def account_snapshot(self) -> PortfolioSnapshot:
        info = mt5.account_info()
        if info is None:
            raise MT5Error(f"MT5 account_info failed: {mt5.last_error()}")
        timestamp = datetime.now(UTC)
        return PortfolioSnapshot(
            timestamp=timestamp,
            cash=float(info.balance),
            equity=float(info.equity),
            unrealized_pnl=float(info.profit),
            realized_pnl=float(info.equity - info.balance - info.profit),
            drawdown=0.0,
        )

    def get_position(self) -> Position:
        symbol = self.resolved_symbol or self.config.symbol
        positions = mt5.positions_get(symbol=symbol)
        if positions is None:
            raise MT5Error(f"MT5 positions_get failed: {mt5.last_error()}")
        quantity = 0.0
        weighted_price = 0.0
        for position in positions:
            if position.type == mt5.POSITION_TYPE_BUY:
                quantity += float(position.volume)
                weighted_price += float(position.price_open) * float(position.volume)
            elif position.type == mt5.POSITION_TYPE_SELL:
                quantity -= float(position.volume)
                weighted_price += float(position.price_open) * float(position.volume)
        average_price = weighted_price / abs(quantity) if quantity else 0.0
        return Position(symbol=symbol, quantity=quantity, average_price=average_price)

    def current_price(self, side: Side) -> float:
        symbol = self.resolved_symbol or self.config.symbol
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise MT5Error(f"MT5 symbol_info_tick failed: {mt5.last_error()}")
        if side == Side.BUY:
            return float(tick.ask)
        return float(tick.bid)

    def send_market_order(self, order: OrderRequest) -> FillEvent:
        side_map = {
            Side.BUY: mt5.ORDER_TYPE_BUY,
            Side.SELL: mt5.ORDER_TYPE_SELL,
        }
        symbol = self.resolved_symbol or self.config.symbol
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            raise MT5Error(f"MT5 symbol_info failed: {mt5.last_error()}")
        volume_step = float(symbol_info.volume_step or 0.01)
        volume = max(float(symbol_info.volume_min), round(order.quantity / volume_step) * volume_step)
        price = self.current_price(order.side)
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": side_map[order.side],
            "price": price,
            "deviation": self.config.deviation,
            "magic": self.config.magic_number,
            "comment": order.reason[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise MT5Error(f"MT5 order_send failed: {result.retcode if result else None} {mt5.last_error()}")
        LOGGER.info("mt5 order sent side=%s volume=%.2f price=%.2f", order.side.value, volume, result.price)
        return FillEvent(
            timestamp=order.timestamp,
            symbol=order.symbol,
            side=order.side,
            quantity=volume,
            price=float(result.price),
        )


@dataclass(slots=True)
class MT5Broker:
    client: MT5Client
    starting_equity: float

    def submit_order(self, order: OrderRequest, market_price: float) -> FillEvent:
        del market_price
        return self.client.send_market_order(order)

    def snapshot(self, timestamp, mark_price: float) -> PortfolioSnapshot:
        del timestamp, mark_price
        snapshot = self.client.account_snapshot()
        snapshot.drawdown = max(0.0, (self.starting_equity - snapshot.equity) / self.starting_equity)
        return snapshot

    def get_position_quantity(self) -> float:
        return self.client.get_position().quantity

    def get_closed_trade_pnls(self) -> list[float]:
        return []

    def get_total_costs(self) -> float:
        return 0.0
