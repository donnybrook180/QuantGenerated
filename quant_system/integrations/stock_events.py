from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class DailyEventFlags:
    news_count: int = 0
    high_impact_count: int = 0
    earnings_like_count: int = 0
    event_blackout: bool = False


def fetch_stock_event_flags(
    symbol: str,
    start_day: date,
    end_day: date,
) -> dict[date, DailyEventFlags]:
    _ = (symbol, start_day, end_day)
    return {}
