from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
import json
import logging
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import urlopen


LOGGER = logging.getLogger(__name__)

_EARNINGS_KEYWORDS = ("earnings", "quarter", "results", "guidance", "revenue", "eps")
_HIGH_IMPACT_KEYWORDS = _EARNINGS_KEYWORDS + (
    "downgrade",
    "upgrade",
    "sec",
    "investigation",
    "offering",
    "merger",
    "acquisition",
    "fda",
    "bankruptcy",
    "lawsuit",
)


@dataclass(frozen=True, slots=True)
class DailyEventFlags:
    news_count: int = 0
    high_impact_count: int = 0
    earnings_like_count: int = 0
    event_blackout: bool = False


def _request_json(url: str, max_retries: int = 4, backoff_seconds: float = 2.0) -> dict[str, object]:
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            with urlopen(url) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            message = str(exc).lower()
            if ("429" not in message and "too many" not in message) or attempt == max_retries:
                break
            sleep_seconds = backoff_seconds * (2 ** (attempt - 1))
            LOGGER.warning("Polygon events rate limit on attempt %d/%d; backing off %.1fs", attempt, max_retries, sleep_seconds)
            time.sleep(sleep_seconds)
    if last_error is not None:
        raise RuntimeError(f"Polygon events request failed: {last_error}") from last_error
    raise RuntimeError("Polygon events request failed.")


def _append_api_key(next_url: str, api_key: str) -> str:
    parsed = urlparse(next_url)
    query = dict(parse_qsl(parsed.query))
    query["apiKey"] = api_key
    return urlunparse(parsed._replace(query=urlencode(query)))


def _news_day(news_item: dict[str, object]) -> date | None:
    published = str(news_item.get("published_utc") or "").strip()
    if not published:
        return None
    try:
        return datetime.fromisoformat(published.replace("Z", "+00:00")).astimezone(UTC).date()
    except ValueError:
        return None


def _contains_keywords(news_item: dict[str, object], keywords: tuple[str, ...]) -> bool:
    title = str(news_item.get("title") or "").lower()
    description = str(news_item.get("description") or "").lower()
    article_keywords = " ".join(str(item).lower() for item in (news_item.get("keywords") or []))
    haystack = " ".join((title, description, article_keywords))
    return any(keyword in haystack for keyword in keywords)


@lru_cache(maxsize=128)
def fetch_stock_event_flags(
    api_key: str | None,
    symbol: str,
    start_day: date,
    end_day: date,
    *,
    max_retries: int = 4,
    backoff_seconds: float = 2.0,
) -> dict[date, DailyEventFlags]:
    if not api_key:
        return {}

    flags: dict[date, DailyEventFlags] = {}
    blackout_days: set[date] = set()
    current_url = (
        "https://api.polygon.io/v2/reference/news?"
        + urlencode(
            {
                "ticker": symbol.upper(),
                "published_utc.gte": f"{start_day.isoformat()}T00:00:00Z",
                "published_utc.lte": f"{end_day.isoformat()}T23:59:59Z",
                "limit": 1000,
                "sort": "published_utc",
                "order": "asc",
                "apiKey": api_key,
            }
        )
    )
    pages = 0
    while current_url and pages < 20:
        payload = _request_json(current_url, max_retries=max_retries, backoff_seconds=backoff_seconds)
        pages += 1
        for item in payload.get("results") or []:
            if not isinstance(item, dict):
                continue
            item_day = _news_day(item)
            if item_day is None or item_day < start_day or item_day > end_day:
                continue
            previous = flags.get(item_day, DailyEventFlags())
            high_impact = _contains_keywords(item, _HIGH_IMPACT_KEYWORDS)
            earnings_like = _contains_keywords(item, _EARNINGS_KEYWORDS)
            flags[item_day] = DailyEventFlags(
                news_count=previous.news_count + 1,
                high_impact_count=previous.high_impact_count + (1 if high_impact else 0),
                earnings_like_count=previous.earnings_like_count + (1 if earnings_like else 0),
                event_blackout=previous.event_blackout,
            )
            if earnings_like:
                blackout_days.update({item_day - timedelta(days=1), item_day, item_day + timedelta(days=1)})
            elif high_impact:
                blackout_days.add(item_day)
        next_url = payload.get("next_url")
        current_url = _append_api_key(str(next_url), api_key) if next_url else ""

    for day in list(flags):
        if day in blackout_days:
            existing = flags[day]
            flags[day] = DailyEventFlags(
                news_count=existing.news_count,
                high_impact_count=existing.high_impact_count,
                earnings_like_count=existing.earnings_like_count,
                event_blackout=True,
            )
    for day in blackout_days:
        if start_day <= day <= end_day and day not in flags:
            flags[day] = DailyEventFlags(event_blackout=True)
    return flags
