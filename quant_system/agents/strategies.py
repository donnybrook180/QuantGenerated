from __future__ import annotations

from collections import deque

from quant_system.agents.base import Agent
from quant_system.models import FeatureVector, Side, SignalEvent


class OpeningRangeBreakoutAgent(Agent):
    name = "opening_range_breakout"

    def __init__(self) -> None:
        self.current_day: tuple[int, int, int] | None = None
        self.range_high: float | None = None
        self.range_low: float | None = None
        self.breakout_side: Side = Side.FLAT

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        day_key = (feature.timestamp.year, feature.timestamp.month, feature.timestamp.day)
        high = feature.values.get("high", feature.values["close"])
        low = feature.values.get("low", feature.values["close"])
        close = feature.values["close"]
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        minutes_from_open = feature.values.get("minutes_from_open", -1.0)

        if self.current_day != day_key:
            self.current_day = day_key
            self.range_high = None
            self.range_low = None
            self.breakout_side = Side.FLAT

        if in_regular_session >= 1.0 and 0 <= minutes_from_open < 30:
            self.range_high = high if self.range_high is None else max(self.range_high, high)
            self.range_low = low if self.range_low is None else min(self.range_low, low)
            return None

        if self.range_high is None or self.range_low is None:
            return None

        if in_regular_session < 1.0 or not (30 <= minutes_from_open <= 90):
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        breakout_buffer = 0.0009
        hour = int(feature.values.get("hour_of_day", 0.0))
        minute = feature.timestamp.minute
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        if (
            hour == 14
            and minute in {0, 15, 40}
            and close > self.range_high * (1.0 + breakout_buffer)
            and relative_volume >= 0.95
            and trend_strength > 0.0004
            and momentum_20 > 0.0
        ):
            self.breakout_side = Side.BUY
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                min(((close / self.range_high) - 1.0) * 220 + 0.35, 1.0),
                {"range_high": self.range_high, "breakout_high": self.range_high},
            )
        if self.breakout_side == Side.BUY and close < self.range_high:
            self.breakout_side = Side.FLAT
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.7, {"failed_breakout": 1.0})
        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class VolatilityBreakoutAgent(Agent):
    name = "volatility_breakout"

    def __init__(self, lookback: int = 12) -> None:
        self.highs: deque[float] = deque(maxlen=lookback)
        self.lows: deque[float] = deque(maxlen=lookback)
        self.breakout_side: Side = Side.FLAT
        self.entry_anchor: float | None = None
        self.allowed_hours = {13, 14, 16}

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        high = feature.values.get("high", feature.values["close"])
        low = feature.values.get("low", feature.values["close"])
        close = feature.values["close"]
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        hour = int(feature.values.get("hour_of_day", 0))
        trend_strength = feature.values.get("trend_strength", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)

        self.highs.append(high)
        self.lows.append(low)
        if len(self.highs) < self.highs.maxlen:
            return None

        breakout_high = max(list(self.highs)[:-1])
        breakout_low = min(list(self.lows)[:-1])

        if hour not in self.allowed_hours:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        if (
            self.breakout_side == Side.FLAT
            and close > breakout_high
            and atr_proxy > 0.0005
            and trend_strength > 0.0003
            and momentum_20 > 0.0
            and relative_volume >= 1.0
        ):
            self.breakout_side = Side.BUY
            self.entry_anchor = breakout_high
            confidence = min(((close / breakout_high) - 1.0) * 300 + abs(trend_strength) * 100 + 0.35, 1.0)
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.BUY, confidence, {"breakout_high": breakout_high})
        if (
            close < breakout_low
            and atr_proxy > 0.0005
            and trend_strength < -0.0003
            and momentum_20 < 0
            and relative_volume >= 1.0
        ):
            self.breakout_side = Side.FLAT
            self.entry_anchor = None
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.75, {"breakout_low": breakout_low})
        if self.breakout_side == Side.BUY and (
            trend_strength < -0.00025
            or momentum_20 < 0
            or (self.entry_anchor is not None and close < self.entry_anchor)
        ):
            self.breakout_side = Side.FLAT
            self.entry_anchor = None
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.7, {"trend_flip": 1.0})
        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
