from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from quant_system.models import Side


def scaled_confidence(base: float, *components: tuple[float, float], max_value: float = 1.0) -> float:
    score = base
    for value, scale in components:
        score += value * scale
    return min(score, max_value)


def directional_metadata(side: Side, *, short_entry: bool = False, short_exit: bool = False, **metadata: float | int | str) -> dict[str, float | int | str]:
    enriched = dict(metadata)
    if side == Side.SELL and short_entry:
        enriched["position_intent"] = "short_entry"
    elif side == Side.BUY and short_exit:
        enriched["position_intent"] = "short_exit"
    return enriched


@dataclass
class SessionRangeState:
    current_day: tuple[int, int, int] | None = None
    range_high: float | None = None
    range_low: float | None = None

    def reset_for_timestamp(self, timestamp) -> None:
        self.current_day = (timestamp.year, timestamp.month, timestamp.day)
        self.range_high = None
        self.range_low = None

    def ensure_day(self, timestamp) -> bool:
        day_key = (timestamp.year, timestamp.month, timestamp.day)
        if self.current_day != day_key:
            self.reset_for_timestamp(timestamp)
            return True
        return False

    def update(self, high: float, low: float) -> None:
        self.range_high = high if self.range_high is None else max(self.range_high, high)
        self.range_low = low if self.range_low is None else min(self.range_low, low)

    @property
    def ready(self) -> bool:
        return self.range_high is not None and self.range_low is not None


@dataclass
class RollingHighLowState:
    lookback: int
    highs: deque[float] = field(init=False)
    lows: deque[float] = field(init=False)

    def __post_init__(self) -> None:
        self.highs = deque(maxlen=self.lookback)
        self.lows = deque(maxlen=self.lookback)

    def append(self, high: float, low: float) -> None:
        self.highs.append(high)
        self.lows.append(low)

    @property
    def ready(self) -> bool:
        return len(self.highs) == self.highs.maxlen

    def breakout_high(self) -> float:
        return max(list(self.highs)[:-1])

    def breakout_low(self) -> float:
        return min(list(self.lows)[:-1])

    def recent_high(self, size: int = 4) -> float:
        return max(list(self.highs)[-size:])

    def recent_low(self, size: int = 4) -> float:
        return min(list(self.lows)[-size:])


@dataclass
class RollingCloseState:
    lookback: int
    closes: deque[float] = field(init=False)

    def __post_init__(self) -> None:
        self.closes = deque(maxlen=self.lookback)

    def append(self, close: float) -> None:
        self.closes.append(close)

    @property
    def ready(self) -> bool:
        return len(self.closes) == self.closes.maxlen

    def mean(self) -> float:
        return sum(self.closes) / len(self.closes)

    def recent_high(self, size: int = 5) -> float:
        return max(list(self.closes)[-size:])

    def recent_low(self, size: int = 5) -> float:
        return min(list(self.closes)[-size:])
