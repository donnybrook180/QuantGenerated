from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import logging
from typing import ClassVar

import MetaTrader5 as mt5

from quant_system.ai.storage import ExperimentStore
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
class MT5AccountModeInfo:
    margin_mode_code: int
    margin_mode_label: str
    strategy_isolation_supported: bool


@dataclass(slots=True)
class MT5PositionInfo:
    ticket: int
    symbol: str
    side: Side
    quantity: float
    price_open: float
    magic_number: int
    comment: str


@dataclass(slots=True)
class MT5MarketSnapshot:
    symbol: str
    bid: float
    ask: float
    point: float
    spread_points: float


@dataclass(slots=True)
class MT5FundingInfo:
    symbol: str
    swap_long: float
    swap_short: float
    swap_rollover3days: int
    contract_size: float
    point: float


@dataclass(slots=True)
class MT5DealCost:
    deal_ticket: int
    order_ticket: int
    position_id: int
    commission: float
    swap: float
    fee: float
    total_cost: float


@dataclass(slots=True)
class MT5Client:
    config: MT5Config
    resolved_symbol: str | None = field(default=None, init=False)
    _session_signature: tuple[str | None, int | None, str | None, str | None] | None = field(default=None, init=False)

    _GLOBAL_SESSION_SIGNATURE: ClassVar[tuple[str | None, int | None, str | None, str | None] | None] = None
    _GLOBAL_SESSION_REFS: ClassVar[int] = 0

    def _connection_signature(self) -> tuple[str | None, int | None, str | None, str | None]:
        return (
            self.config.terminal_path,
            self.config.login,
            self.config.server,
            self.config.password,
        )

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

        signature = self._connection_signature()
        if MT5Client._GLOBAL_SESSION_REFS > 0 and MT5Client._GLOBAL_SESSION_SIGNATURE != signature:
            raise MT5Error("MT5 session already initialized with a different terminal/login configuration.")
        if MT5Client._GLOBAL_SESSION_REFS == 0:
            if not mt5.initialize(**kwargs):
                raise MT5Error(f"MT5 initialize failed: {mt5.last_error()}")
            MT5Client._GLOBAL_SESSION_SIGNATURE = signature
        MT5Client._GLOBAL_SESSION_REFS += 1
        self._session_signature = signature
        self.resolved_symbol = self._resolve_symbol(self.config.symbol)
        if not mt5.symbol_select(self.resolved_symbol, True):
            raise MT5Error(f"Unable to select symbol {self.resolved_symbol}: {mt5.last_error()}")

    def shutdown(self) -> None:
        if self._session_signature is None:
            return
        if MT5Client._GLOBAL_SESSION_REFS > 0:
            MT5Client._GLOBAL_SESSION_REFS -= 1
        if MT5Client._GLOBAL_SESSION_REFS <= 0:
            mt5.shutdown()
            MT5Client._GLOBAL_SESSION_REFS = 0
            MT5Client._GLOBAL_SESSION_SIGNATURE = None
        self._session_signature = None

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

    def account_mode_info(self) -> MT5AccountModeInfo:
        info = mt5.account_info()
        if info is None:
            raise MT5Error(f"MT5 account_info failed: {mt5.last_error()}")
        margin_mode = int(getattr(info, "margin_mode", -1))
        hedging_code = int(getattr(mt5, "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING", -999999))
        netting_codes = {
            int(getattr(mt5, "ACCOUNT_MARGIN_MODE_RETAIL_NETTING", -999998)),
            int(getattr(mt5, "ACCOUNT_MARGIN_MODE_EXCHANGE", -999997)),
        }
        if margin_mode == hedging_code:
            label = "hedging"
            supported = True
        elif margin_mode in netting_codes:
            label = "netting"
            supported = False
        else:
            label = f"unknown({margin_mode})"
            supported = False
        return MT5AccountModeInfo(
            margin_mode_code=margin_mode,
            margin_mode_label=label,
            strategy_isolation_supported=supported,
        )

    def get_position(self) -> Position:
        positions = self.list_positions()
        quantity = 0.0
        weighted_price = 0.0
        for position in positions:
            signed_quantity = position.quantity if position.side == Side.BUY else -position.quantity
            quantity += signed_quantity
            weighted_price += position.price_open * position.quantity
        average_price = weighted_price / abs(quantity) if quantity else 0.0
        return Position(symbol=self.resolved_symbol or self.config.symbol, quantity=quantity, average_price=average_price)

    def list_positions(self, magic_number: int | None = None) -> list[MT5PositionInfo]:
        symbol = self.resolved_symbol or self.config.symbol
        positions = mt5.positions_get(symbol=symbol)
        if positions is None:
            raise MT5Error(f"MT5 positions_get failed: {mt5.last_error()}")
        mapped: list[MT5PositionInfo] = []
        for position in positions:
            pos_magic = int(getattr(position, "magic", 0) or 0)
            if magic_number is not None and pos_magic != magic_number:
                continue
            side = Side.BUY if position.type == mt5.POSITION_TYPE_BUY else Side.SELL
            mapped.append(
                MT5PositionInfo(
                    ticket=int(position.ticket),
                    symbol=str(position.symbol),
                    side=side,
                    quantity=float(position.volume),
                    price_open=float(position.price_open),
                    magic_number=pos_magic,
                    comment=str(getattr(position, "comment", "") or ""),
                )
            )
        return mapped

    def current_price(self, side: Side) -> float:
        symbol = self.resolved_symbol or self.config.symbol
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise MT5Error(f"MT5 symbol_info_tick failed: {mt5.last_error()}")
        if side == Side.BUY:
            return float(tick.ask)
        return float(tick.bid)

    def market_snapshot(self) -> MT5MarketSnapshot:
        symbol = self.resolved_symbol or self.config.symbol
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise MT5Error(f"MT5 symbol_info_tick failed: {mt5.last_error()}")
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            raise MT5Error(f"MT5 symbol_info failed: {mt5.last_error()}")
        bid = float(tick.bid)
        ask = float(tick.ask)
        point = float(symbol_info.point or 0.0)
        raw_spread = max(ask - bid, 0.0)
        quoted_spread = float(getattr(symbol_info, "spread", 0.0) or 0.0) * point
        spread_points = max(raw_spread, quoted_spread)
        return MT5MarketSnapshot(
            symbol=symbol,
            bid=bid,
            ask=ask,
            point=point,
            spread_points=spread_points,
        )

    def funding_info(self) -> MT5FundingInfo:
        symbol = self.resolved_symbol or self.config.symbol
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            raise MT5Error(f"MT5 symbol_info failed: {mt5.last_error()}")
        return MT5FundingInfo(
            symbol=symbol,
            swap_long=float(getattr(symbol_info, "swap_long", 0.0) or 0.0),
            swap_short=float(getattr(symbol_info, "swap_short", 0.0) or 0.0),
            swap_rollover3days=int(getattr(symbol_info, "swap_rollover3days", 0) or 0),
            contract_size=float(getattr(symbol_info, "trade_contract_size", 0.0) or 0.0),
            point=float(getattr(symbol_info, "point", 0.0) or 0.0),
        )

    def _lookup_deal_cost(self, result, symbol: str) -> MT5DealCost:
        deal_ticket = int(getattr(result, "deal", 0) or 0)
        order_ticket = int(getattr(result, "order", 0) or 0)
        if deal_ticket <= 0 and order_ticket <= 0:
            return MT5DealCost(0, 0, 0, 0.0, 0.0, 0.0, 0.0)

        now = datetime.now(UTC)
        start = now - timedelta(minutes=15)
        deals = mt5.history_deals_get(start, now)
        if deals is None:
            LOGGER.warning("mt5 history_deals_get failed while loading broker costs: %s", mt5.last_error())
            return MT5DealCost(deal_ticket, order_ticket, 0, 0.0, 0.0, 0.0, 0.0)

        matched = None
        for deal in deals:
            current_deal_ticket = int(getattr(deal, "ticket", 0) or 0)
            current_order_ticket = int(getattr(deal, "order", 0) or 0)
            current_symbol = str(getattr(deal, "symbol", "") or "")
            if current_symbol != symbol:
                continue
            if deal_ticket > 0 and current_deal_ticket == deal_ticket:
                matched = deal
                break
            if order_ticket > 0 and current_order_ticket == order_ticket:
                matched = deal
        if matched is None:
            return MT5DealCost(deal_ticket, order_ticket, 0, 0.0, 0.0, 0.0, 0.0)

        commission = abs(float(getattr(matched, "commission", 0.0) or 0.0))
        swap = abs(float(getattr(matched, "swap", 0.0) or 0.0))
        fee = abs(float(getattr(matched, "fee", 0.0) or 0.0))
        return MT5DealCost(
            deal_ticket=int(getattr(matched, "ticket", 0) or 0),
            order_ticket=int(getattr(matched, "order", 0) or 0),
            position_id=int(getattr(matched, "position_id", 0) or 0),
            commission=commission,
            swap=swap,
            fee=fee,
            total_cost=commission + swap + fee,
        )

    def send_market_order(
        self,
        order: OrderRequest,
        *,
        magic_number: int | None = None,
        comment: str | None = None,
        position_ticket: int | None = None,
    ) -> FillEvent:
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
        snapshot = self.market_snapshot()
        price = snapshot.ask if order.side == Side.BUY else snapshot.bid
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": side_map[order.side],
            "price": price,
            "deviation": self.config.deviation,
            "magic": magic_number if magic_number is not None else self.config.magic_number,
            "comment": (comment or order.reason)[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if position_ticket is not None:
            request["position"] = int(position_ticket)
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise MT5Error(f"MT5 order_send failed: {result.retcode if result else None} {mt5.last_error()}")
        LOGGER.info("mt5 order sent side=%s volume=%.2f price=%.2f", order.side.value, volume, result.price)
        fill_price = float(result.price)
        slippage_points = abs(fill_price - price)
        slippage_bps = (slippage_points / price * 10_000.0) if price > 0 else 0.0
        deal_cost = self._lookup_deal_cost(result, symbol)
        fill = FillEvent(
            timestamp=order.timestamp,
            symbol=order.symbol,
            side=order.side,
            quantity=volume,
            price=fill_price,
            costs=deal_cost.total_cost,
            metadata={
                "broker_symbol": symbol,
                "requested_price": price,
                "bid": snapshot.bid,
                "ask": snapshot.ask,
                "spread_points": snapshot.spread_points,
                "slippage_points": slippage_points,
                "slippage_bps": slippage_bps,
                "reason": order.reason,
                "confidence": order.confidence,
                "magic_number": int(magic_number if magic_number is not None else self.config.magic_number),
                "comment": (comment or order.reason)[:31],
                "position_ticket": int(position_ticket) if position_ticket is not None else 0,
                "deal_ticket": deal_cost.deal_ticket,
                "order_ticket": deal_cost.order_ticket,
                "broker_position_id": deal_cost.position_id,
                "commission": deal_cost.commission,
                "swap": deal_cost.swap,
                "fee": deal_cost.fee,
                "broker_cost_total": deal_cost.total_cost,
            },
        )
        try:
            ExperimentStore(self.config.database_path).record_mt5_fill_event(
                event_timestamp=order.timestamp.replace(tzinfo=None),
                broker_symbol=symbol,
                requested_symbol=order.symbol,
                side=order.side.value,
                quantity=volume,
                requested_price=price,
                fill_price=fill_price,
                bid=snapshot.bid,
                ask=snapshot.ask,
                spread_points=snapshot.spread_points,
                slippage_points=slippage_points,
                slippage_bps=slippage_bps,
                costs=deal_cost.total_cost,
                reason=order.reason,
                confidence=order.confidence,
                metadata={
                    **dict(order.metadata),
                    "deal_ticket": deal_cost.deal_ticket,
                    "order_ticket": deal_cost.order_ticket,
                    "broker_position_id": deal_cost.position_id,
                    "commission": deal_cost.commission,
                    "swap": deal_cost.swap,
                    "fee": deal_cost.fee,
                    "broker_cost_total": deal_cost.total_cost,
                },
                magic_number=int(magic_number if magic_number is not None else self.config.magic_number),
                comment=(comment or order.reason)[:31],
                position_ticket=int(position_ticket) if position_ticket is not None else None,
            )
        except Exception as exc:
            LOGGER.warning("Failed to persist MT5 fill event for %s: %s", symbol, exc)
        return fill


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
