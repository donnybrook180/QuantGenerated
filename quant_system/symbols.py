from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResolvedSymbol:
    requested_symbol: str
    profile_symbol: str
    data_symbol: str
    broker_symbol: str


_SYMBOL_ALIASES: dict[str, tuple[str, str, str]] = {
    "US500": ("US500", "SPY", "US500.cash"),
    "SPY": ("US500", "SPY", "US500.cash"),
    "I:SPX": ("US500", "SPY", "US500.cash"),
    "SPX": ("US500", "SPY", "US500.cash"),
    "US100": ("US100", "QQQ", "US100.cash"),
    "QQQ": ("US100", "QQQ", "US100.cash"),
    "I:NDX": ("US100", "QQQ", "US100.cash"),
    "NDX": ("US100", "QQQ", "US100.cash"),
    "GER40": ("GER40", "DAX", "GER40.cash"),
    "DAX": ("GER40", "DAX", "GER40.cash"),
    "DE40": ("GER40", "DAX", "GER40.cash"),
    "XAUUSD": ("XAUUSD", "C:XAUUSD", "XAUUSD"),
    "C:XAUUSD": ("XAUUSD", "C:XAUUSD", "XAUUSD"),
    "GOLD": ("XAUUSD", "C:XAUUSD", "XAUUSD"),
    "BTC": ("BTC", "X:BTCUSD", "BTCUSD"),
    "BTCUSD": ("BTC", "X:BTCUSD", "BTCUSD"),
    "X:BTCUSD": ("BTC", "X:BTCUSD", "BTCUSD"),
    "EURUSD": ("EURUSD", "C:EURUSD", "EURUSD"),
    "C:EURUSD": ("EURUSD", "C:EURUSD", "EURUSD"),
    "GBPUSD": ("GBPUSD", "C:GBPUSD", "GBPUSD"),
    "C:GBPUSD": ("GBPUSD", "C:GBPUSD", "GBPUSD"),
    "USDJPY": ("USDJPY", "C:USDJPY", "USDJPY"),
    "C:USDJPY": ("USDJPY", "C:USDJPY", "USDJPY"),
    "AUDUSD": ("AUDUSD", "C:AUDUSD", "AUDUSD"),
    "C:AUDUSD": ("AUDUSD", "C:AUDUSD", "AUDUSD"),
}


def resolve_symbol_request(symbol: str, broker_symbol: str | None = None) -> ResolvedSymbol:
    requested = symbol.strip()
    upper = requested.upper()
    alias = _SYMBOL_ALIASES.get(upper)
    if alias is None:
        data_symbol = requested
        resolved_broker = broker_symbol.strip() if broker_symbol and broker_symbol.strip() else requested
        profile_symbol = requested
    else:
        profile_symbol, data_symbol, default_broker = alias
        resolved_broker = broker_symbol.strip() if broker_symbol and broker_symbol.strip() else default_broker

    return ResolvedSymbol(
        requested_symbol=requested,
        profile_symbol=profile_symbol,
        data_symbol=data_symbol,
        broker_symbol=resolved_broker,
    )
