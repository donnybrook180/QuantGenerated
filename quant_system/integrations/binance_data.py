from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import urllib.parse
import urllib.request

from quant_system.models import MarketBar


class BinanceError(RuntimeError):
    pass


def _map_symbol(symbol: str) -> str:
    upper = symbol.upper()
    if upper == "X:ETHUSD":
        return "ETHUSDT"
    if upper == "X:BTCUSD":
        return "BTCUSDT"
    raise BinanceError(f"Unsupported Binance crypto symbol mapping for {symbol}.")


def _map_interval(multiplier: int, timespan: str) -> str:
    if timespan != "minute":
        raise BinanceError(f"Unsupported Binance timespan {timespan}.")
    supported = {1, 3, 5, 15, 30}
    if multiplier not in supported:
        raise BinanceError(f"Unsupported Binance minute multiplier {multiplier}.")
    return f"{multiplier}m"


@dataclass(slots=True)
class BinanceKlineClient:
    symbol: str
    multiplier: int
    timespan: str
    history_days: int
    base_url: str = "https://api.binance.com"

    def fetch_bars(self) -> list[MarketBar]:
        mapped_symbol = _map_symbol(self.symbol)
        interval = _map_interval(self.multiplier, self.timespan)
        end = datetime.now(UTC)
        start = end - timedelta(days=self.history_days)
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        bars: list[MarketBar] = []

        while start_ms < end_ms:
            query = urllib.parse.urlencode(
                {
                    "symbol": mapped_symbol,
                    "interval": interval,
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "limit": 1000,
                }
            )
            url = f"{self.base_url}/api/v3/klines?{query}"
            request = urllib.request.Request(url, headers={"User-Agent": "QuantGenerated/1.0"})
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except Exception as exc:
                raise BinanceError(f"Binance request failed for {mapped_symbol}: {exc}") from exc

            if not isinstance(payload, list):
                raise BinanceError(f"Unexpected Binance response for {mapped_symbol}: {payload}")
            if not payload:
                break

            for row in payload:
                open_time_ms = int(row[0])
                bars.append(
                    MarketBar(
                        timestamp=datetime.fromtimestamp(open_time_ms / 1000, UTC),
                        symbol=self.symbol,
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=float(row[5]),
                    )
                )

            next_start_ms = int(payload[-1][0]) + 1
            if next_start_ms <= start_ms:
                break
            start_ms = next_start_ms

        filtered = [bar for bar in bars if bar.close > 0 and bar.high >= bar.low]
        if not filtered:
            raise BinanceError(f"No Binance bars received for {mapped_symbol}.")
        return filtered
