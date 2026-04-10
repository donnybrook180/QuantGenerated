from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
import csv

from quant_system.models import FeatureVector


@dataclass(frozen=True, slots=True)
class MacroCalendarEvent:
    timestamp: datetime
    importance: str
    currencies: tuple[str, ...]
    event_code: str
    description: str = ""
    symbols: tuple[str, ...] = ()


def _as_utc(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _normalize_token(raw: str) -> str:
    return raw.strip().upper().replace(" ", "")


def _parse_tokens(raw: str) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(token for token in (_normalize_token(part) for part in raw.split(",")) if token)


def _parse_event_row(row: dict[str, str]) -> MacroCalendarEvent | None:
    raw_timestamp = (row.get("timestamp_utc") or "").strip()
    raw_importance = (row.get("importance") or "medium").strip().lower()
    raw_code = (row.get("event_code") or "").strip()
    if not raw_timestamp or not raw_code:
        return None
    try:
        timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None
    if raw_importance not in {"low", "medium", "high"}:
        raw_importance = "medium"
    return MacroCalendarEvent(
        timestamp=timestamp,
        importance=raw_importance,
        currencies=_parse_tokens(row.get("currencies") or ""),
        event_code=raw_code,
        description=(row.get("description") or "").strip(),
        symbols=_parse_tokens(row.get("symbols") or ""),
    )


@lru_cache(maxsize=16)
def load_macro_calendar(calendar_path: str) -> tuple[MacroCalendarEvent, ...]:
    path = Path(calendar_path)
    if not path.exists():
        return ()
    events: list[MacroCalendarEvent] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            event = _parse_event_row(row)
            if event is not None:
                events.append(event)
    return tuple(sorted(events, key=lambda item: item.timestamp))


def _symbol_event_tags(symbol: str) -> set[str]:
    upper = _normalize_token(symbol.replace("C:", ""))
    if len(upper) == 6 and upper.isalpha() and upper.endswith(("USD", "JPY", "EUR", "GBP", "CHF", "CAD", "AUD", "NZD")):
        return {upper[:3], upper[3:], upper}
    if upper == "XAUUSD":
        return {"XAU", "USD", "GOLD", "XAUUSD"}
    return {upper}


def _is_relevant_event(symbol: str, event: MacroCalendarEvent) -> bool:
    tags = _symbol_event_tags(symbol)
    if tags.intersection(event.symbols):
        return True
    return bool(tags.intersection(event.currencies))


def apply_macro_event_context(
    features: list[FeatureVector],
    symbol: str,
    calendar_path: str | None,
    *,
    pre_event_minutes: int = 60,
    post_event_minutes: int = 120,
) -> list[FeatureVector]:
    if not features or not calendar_path:
        return features
    events = [event for event in load_macro_calendar(calendar_path) if _is_relevant_event(symbol, event)]
    if not events:
        return features

    events_by_day: dict[date, list[MacroCalendarEvent]] = {}
    for event in events:
        events_by_day.setdefault(event.timestamp.date(), []).append(event)

    next_index = 0
    for feature in features:
        timestamp = _as_utc(feature.timestamp)
        while next_index < len(events) and events[next_index].timestamp < timestamp:
            next_index += 1

        day_events = events_by_day.get(timestamp.date(), [])
        event_count = float(len(day_events))
        high_impact_count = float(sum(1 for event in day_events if event.importance == "high"))
        event_day = 1.0 if day_events else 0.0
        high_impact_day = 1.0 if high_impact_count > 0 else 0.0

        next_event_minutes = -1.0
        previous_event_minutes = -1.0
        pre_window = 0.0
        post_window = 0.0

        if next_index < len(events):
            delta_next = (events[next_index].timestamp - timestamp).total_seconds() / 60.0
            next_event_minutes = delta_next
            if 0.0 <= delta_next <= pre_event_minutes:
                pre_window = 1.0

        if next_index > 0:
            previous_event = events[next_index - 1]
            delta_prev = (timestamp - previous_event.timestamp).total_seconds() / 60.0
            previous_event_minutes = delta_prev
            if 0.0 <= delta_prev <= post_event_minutes:
                post_window = 1.0

        blackout = 1.0 if (pre_window > 0.0 or post_window > 0.0) else 0.0
        feature.values.update(
            {
                "macro_event_count_1d": event_count,
                "macro_high_impact_count_1d": high_impact_count,
                "macro_event_day": event_day,
                "macro_high_impact_event_day": high_impact_day,
                "macro_pre_event_window": pre_window,
                "macro_post_event_window": post_window,
                "macro_event_blackout": blackout,
                "macro_minutes_to_next_event": next_event_minutes,
                "macro_minutes_since_event": previous_event_minutes,
            }
        )
    return features
