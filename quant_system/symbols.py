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
    "NAS100": ("US100", "QQQ", "US100.cash"),
    "QQQ": ("US100", "QQQ", "US100.cash"),
    "I:NDX": ("US100", "QQQ", "US100.cash"),
    "NDX": ("US100", "QQQ", "US100.cash"),
    "US30": ("US30", "DIA", "US30.cash"),
    "DJ30": ("US30", "DIA", "US30.cash"),
    "DOW30": ("US30", "DIA", "US30.cash"),
    "DIA": ("US30", "DIA", "US30.cash"),
    "I:DJI": ("US30", "DIA", "US30.cash"),
    "DJI": ("US30", "DIA", "US30.cash"),
    "GER40": ("GER40", "DAX", "GER40.cash"),
    "DAX": ("GER40", "DAX", "GER40.cash"),
    "DE40": ("GER40", "DAX", "GER40.cash"),
    "SX5E": ("EU50", "SX5E", "EU50.cash"),
    "EU50": ("EU50", "SX5E", "EU50.cash"),
    "EU50.CASH": ("EU50", "SX5E", "EU50.cash"),
    "ESTX50": ("EU50", "SX5E", "EU50.cash"),
    "JP225": ("JP225", "JP225", "JP225.cash"),
    "JP225.CASH": ("JP225", "JP225", "JP225.cash"),
    "JPN225": ("JP225", "JP225", "JP225.cash"),
    "NK225": ("JP225", "JP225", "JP225.cash"),
    "UK100": ("UK100", "UK100", "UK100.cash"),
    "UK100.CASH": ("UK100", "UK100", "UK100.cash"),
    "FTSE100": ("UK100", "UK100", "UK100.cash"),
    "FTSE": ("UK100", "UK100", "UK100.cash"),
    "HK50": ("HK50", "HK50", "HK50"),
    "HK50.CASH": ("HK50", "HK50", "HK50.cash"),
    "HSI50": ("HK50", "HK50", "HK50"),
    "HANGSENG": ("HK50", "HK50", "HK50"),
    "XAUUSD": ("XAUUSD", "C:XAUUSD", "XAUUSD"),
    "C:XAUUSD": ("XAUUSD", "C:XAUUSD", "XAUUSD"),
    "GOLD": ("XAUUSD", "C:XAUUSD", "XAUUSD"),
    "BTC": ("BTC", "X:BTCUSD", "BTCUSD"),
    "BTCUSD": ("BTC", "X:BTCUSD", "BTCUSD"),
    "X:BTCUSD": ("BTC", "X:BTCUSD", "BTCUSD"),
    "ETH": ("ETH", "X:ETHUSD", "ETHUSD"),
    "ETHUSD": ("ETH", "X:ETHUSD", "ETHUSD"),
    "X:ETHUSD": ("ETH", "X:ETHUSD", "ETHUSD"),
    "EURUSD": ("EURUSD", "C:EURUSD", "EURUSD"),
    "C:EURUSD": ("EURUSD", "C:EURUSD", "EURUSD"),
    "GBPUSD": ("GBPUSD", "C:GBPUSD", "GBPUSD"),
    "C:GBPUSD": ("GBPUSD", "C:GBPUSD", "GBPUSD"),
    "USDJPY": ("USDJPY", "C:USDJPY", "USDJPY"),
    "C:USDJPY": ("USDJPY", "C:USDJPY", "USDJPY"),
    "AUDUSD": ("AUDUSD", "C:AUDUSD", "AUDUSD"),
    "C:AUDUSD": ("AUDUSD", "C:AUDUSD", "AUDUSD"),
}


def is_crypto_symbol(symbol: str) -> bool:
    upper = symbol.upper()
    return "BTC" in upper or "ETH" in upper


def is_metal_symbol(symbol: str) -> bool:
    return "XAU" in symbol.upper()


def is_forex_symbol(symbol: str) -> bool:
    upper = symbol.upper()
    return upper.endswith("USD") or upper.endswith("JPY") or upper.startswith("EUR") or upper.startswith("GBP") or upper.startswith("AUD")


def is_index_symbol(symbol: str) -> bool:
    upper = symbol.upper()
    return upper in {
        "US500",
        "SPY",
        "SPX",
        "I:SPX",
        "US100",
        "NAS100",
        "QQQ",
        "NDX",
        "I:NDX",
        "US30",
        "DJ30",
        "DOW30",
        "DIA",
        "DJI",
        "I:DJI",
        "GER40",
        "DAX",
        "DE40",
        "SX5E",
        "EU50",
        "EU50.CASH",
        "ESTX50",
        "JP225",
        "JP225.CASH",
        "JPN225",
        "NK225",
        "UK100",
        "UK100.CASH",
        "FTSE100",
        "FTSE",
        "HK50",
        "HK50.CASH",
        "HSI50",
        "HANGSENG",
    }


def is_stock_symbol(symbol: str) -> bool:
    requested = symbol.strip()
    upper = requested.upper()
    if not upper:
        return False
    if is_crypto_symbol(upper) or is_metal_symbol(upper) or is_forex_symbol(upper) or is_index_symbol(upper):
        return False
    return ":" not in upper and upper.replace(".", "").replace("-", "").isalnum()


def resolve_symbol_request(symbol: str, broker_symbol: str | None = None) -> ResolvedSymbol:
    requested = symbol.strip()
    upper = requested.upper()
    alias = _SYMBOL_ALIASES.get(upper)
    if alias is None:
        normalized = upper if is_stock_symbol(requested) else requested
        data_symbol = normalized
        resolved_broker = broker_symbol.strip() if broker_symbol and broker_symbol.strip() else normalized
        profile_symbol = normalized
    else:
        profile_symbol, data_symbol, default_broker = alias
        resolved_broker = broker_symbol.strip() if broker_symbol and broker_symbol.strip() else default_broker

    return ResolvedSymbol(
        requested_symbol=requested,
        profile_symbol=profile_symbol,
        data_symbol=data_symbol,
        broker_symbol=resolved_broker,
    )
