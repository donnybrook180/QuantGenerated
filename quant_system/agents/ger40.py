from __future__ import annotations

from quant_system.agents.base import Agent
from quant_system.agents.strategies import OpeningRangeBreakoutAgent
from quant_system.models import FeatureVector, Side, SignalEvent


class RangeRetestContinuationAgent(Agent):
    name = "range_retest_continuation"

    def __init__(self) -> None:
        self.current_day: tuple[int, int, int] | None = None
        self.range_high: float | None = None
        self.range_low: float | None = None
        self.breakout_confirmed = False
        self.breakout_bar_index = -1
        self.bar_index = -1

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        self.bar_index += 1
        day_key = (feature.timestamp.year, feature.timestamp.month, feature.timestamp.day)
        high = feature.values.get("high", feature.values["close"])
        low = feature.values.get("low", feature.values["close"])
        close = feature.values["close"]
        relative_volume = feature.values.get("relative_volume", 1.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        minutes_from_open = feature.values.get("minutes_from_open", -1.0)
        hour = int(feature.values.get("hour_of_day", 0.0))

        if self.current_day != day_key:
            self.current_day = day_key
            self.range_high = None
            self.range_low = None
            self.breakout_confirmed = False
            self.breakout_bar_index = -1

        if in_regular_session >= 1.0 and 0 <= minutes_from_open < 30:
            self.range_high = high if self.range_high is None else max(self.range_high, high)
            self.range_low = low if self.range_low is None else min(self.range_low, low)
            return None

        if self.range_high is None or self.range_low is None:
            return None

        if in_regular_session < 1.0 or not (40 <= minutes_from_open <= 180) or hour not in {14, 15, 16}:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        breakout_trigger = self.range_high * 1.0007
        reclaim_trigger = self.range_high * 1.00015
        invalidate_level = self.range_high * 0.9988

        if (
            not self.breakout_confirmed
            and close >= breakout_trigger
            and relative_volume >= 0.95
            and trend_strength > 0.0004
            and momentum_20 > 0.0
        ):
            self.breakout_confirmed = True
            self.breakout_bar_index = self.bar_index
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        if (
            self.breakout_confirmed
            and self.breakout_bar_index >= 0
            and (self.bar_index - self.breakout_bar_index) >= 2
            and low <= reclaim_trigger
            and close >= reclaim_trigger
            and relative_volume >= 0.9
            and trend_strength > 0.0003
            and momentum_20 > 0.0
            and momentum_5 > -0.0005
        ):
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                min(((close / self.range_high) - 1.0) * 180 + 0.35, 1.0),
                {"range_high": self.range_high, "breakout_high": self.range_high, "retest": 1.0},
            )

        if self.breakout_confirmed and (close <= invalidate_level or momentum_20 < 0):
            self.breakout_confirmed = False
            self.breakout_bar_index = -1
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.7, {"failed_retest": 1.0})

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


__all__ = ["OpeningRangeBreakoutAgent", "RangeRetestContinuationAgent"]
