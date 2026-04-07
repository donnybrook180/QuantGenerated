from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import urllib.parse
import urllib.request

from quant_system.models import MarketBar


class KrakenError(RuntimeError):
    pass


def _map_symbol(symbol: str) -> str:
    upper = symbol.upper()
    if upper == "X:ETHUSD":
        return "ETHUSD"
    if upper == "X:BTCUSD":
        return "XBTUSD"
    raise KrakenError(f"Unsupported Kraken crypto symbol mapping for {symbol}.")


def _map_interval(multiplier: int, timespan: str) -> int:
    if timespan != "minute":
        raise KrakenError(f"Unsupported Kraken timespan {timespan}.")
    supported = {1, 5, 15, 30}
    if multiplier not in supported:
        raise KrakenError(f"Unsupported Kraken minute multiplier {multiplier}.")
    return multiplier


@dataclass(slots=True)
class KrakenOHLCClient:
    symbol: str
    multiplier: int
    timespan: str
    history_days: int
    base_url: str = "https://api.kraken.com"

    def fetch_bars(self) -> list[MarketBar]:
        mapped_symbol = _map_symbol(self.symbol)
        interval = _map_interval(self.multiplier, self.timespan)
        start = datetime.now(UTC) - timedelta(days=self.history_days)
        since = int(start.timestamp())
        bars: list[MarketBar] = []

        while True:
            query = urllib.parse.urlencode({"pair": mapped_symbol, "interval": interval, "since": since})
            url = f"{self.base_url}/0/public/OHLC?{query}"
            request = urllib.request.Request(url, headers={"User-Agent": "QuantGenerated/1.0"})
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except Exception as exc:
                raise KrakenError(f"Kraken request failed for {mapped_symbol}: {exc}") from exc

            errors = payload.get("error", [])
            if errors:
                raise KrakenError(f"Kraken error for {mapped_symbol}: {errors}")

            result = payload.get("result", {})
            ohlc_rows = result.get(mapped_symbol) or next(
                (value for key, value in result.items() if key != "last" and isinstance(value, list)),
                [],
            )
            if not ohlc_rows:
                break

            initial_count = len(bars)
            for row in ohlc_rows:
                open_time = int(row[0])
                if open_time < since:
                    continue
                bars.append(
                    MarketBar(
                        timestamp=datetime.fromtimestamp(open_time, UTC),
                        symbol=self.symbol,
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=float(row[6]),
                    )
                )

            next_since = int(result.get("last", since))
            if next_since <= since or len(bars) == initial_count:
                break
            since = next_since

        filtered = [bar for bar in bars if bar.close > 0 and bar.high >= bar.low]
        if not filtered:
            raise KrakenError(f"No Kraken bars received for {mapped_symbol}.")
        return filtered
