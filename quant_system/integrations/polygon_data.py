from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from polygon import RESTClient

from quant_system.config import PolygonConfig
from quant_system.models import MarketBar


class PolygonError(RuntimeError):
    pass


@dataclass(slots=True)
class PolygonDataClient:
    config: PolygonConfig
    client: RESTClient = field(init=False)

    def __post_init__(self) -> None:
        if not self.config.api_key:
            raise PolygonError("POLYGON_API_KEY ontbreekt. Vul die in in .env.")
        self.client = RESTClient(api_key=self.config.api_key)

    def fetch_bars(self) -> list[MarketBar]:
        end = datetime.now(UTC)
        start = end - timedelta(days=self.config.history_days)
        aggs = self.client.list_aggs(
            ticker=self.config.symbol,
            multiplier=self.config.multiplier,
            timespan=self.config.timespan,
            from_=start.date().isoformat(),
            to=end.date().isoformat(),
            adjusted=self.config.adjusted,
            sort="asc",
            limit=50_000,
        )
        bars: list[MarketBar] = []
        for agg in aggs:
            timestamp_ms = getattr(agg, "timestamp", None)
            if timestamp_ms is None:
                continue
            bars.append(
                MarketBar(
                    timestamp=datetime.fromtimestamp(timestamp_ms / 1000, UTC),
                    symbol=self.config.symbol,
                    open=float(agg.open),
                    high=float(agg.high),
                    low=float(agg.low),
                    close=float(agg.close),
                    volume=float(agg.volume or 0.0),
                )
            )
        if not bars:
            raise PolygonError(f"Geen Polygon bars ontvangen voor {self.config.symbol}.")
        return [bar for bar in bars if bar.close > 0 and bar.high >= bar.low]
