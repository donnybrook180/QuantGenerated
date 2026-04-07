from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import logging
import time

from polygon import RESTClient

from quant_system.config import PolygonConfig
from quant_system.models import MarketBar


class PolygonError(RuntimeError):
    pass


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PolygonDataClient:
    config: PolygonConfig
    client: RESTClient = field(init=False)

    def __post_init__(self) -> None:
        if not self.config.api_key:
            raise PolygonError("POLYGON_API_KEY ontbreekt. Vul die in in .env.")
        self.client = RESTClient(api_key=self.config.api_key)

    def _is_rate_limit_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        name = exc.__class__.__name__.lower()
        return "429" in message or "rate limit" in message or "too many" in message or "responseerror" in name

    def _list_aggs_with_retry(self, *, start_date: str, end_date: str):
        max_attempts = max(self.config.max_retries, 1)
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return list(
                    self.client.list_aggs(
                        ticker=self.config.symbol,
                        multiplier=self.config.multiplier,
                        timespan=self.config.timespan,
                        from_=start_date,
                        to=end_date,
                        adjusted=self.config.adjusted,
                        sort="asc",
                        limit=50_000,
                    )
                )
            except Exception as exc:
                last_error = exc
                if not self._is_rate_limit_error(exc) or attempt == max_attempts:
                    break
                sleep_seconds = self.config.retry_backoff_seconds * (2 ** (attempt - 1))
                LOGGER.warning(
                    "Polygon rate limit for %s on attempt %d/%d; backing off %.1fs",
                    self.config.symbol,
                    attempt,
                    max_attempts,
                    sleep_seconds,
                )
                time.sleep(sleep_seconds)
        if last_error is not None:
            raise PolygonError(f"Polygon request failed for {self.config.symbol}: {last_error}") from last_error
        raise PolygonError(f"Polygon request failed for {self.config.symbol}.")

    def fetch_bars(self) -> list[MarketBar]:
        end = datetime.now(UTC)
        start = end - timedelta(days=self.config.history_days)
        aggs = self._list_aggs_with_retry(
            start_date=start.date().isoformat(),
            end_date=end.date().isoformat(),
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
