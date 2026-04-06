from __future__ import annotations

from quant_system.agents.base import Agent
from quant_system.agents.common import SessionRangeState, directional_metadata, scaled_confidence
from quant_system.agents.strategies import OpeningRangeBreakoutAgent
from quant_system.models import FeatureVector, Side, SignalEvent


class RangeRetestContinuationAgent(Agent):
    name = "range_retest_continuation"

    def __init__(self) -> None:
        self.range_state = SessionRangeState()
        self.breakout_confirmed = False
        self.breakout_bar_index = -1
        self.bar_index = -1

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        self.bar_index += 1
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

        if self.range_state.ensure_day(feature.timestamp):
            self.breakout_confirmed = False
            self.breakout_bar_index = -1

        if in_regular_session >= 1.0 and 0 <= minutes_from_open < 30:
            self.range_state.update(high, low)
            return None

        if not self.range_state.ready:
            return None

        if in_regular_session < 1.0 or not (40 <= minutes_from_open <= 180) or hour not in {14, 15, 16}:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        breakout_trigger = self.range_state.range_high * 1.0007
        reclaim_trigger = self.range_state.range_high * 1.00015
        invalidate_level = self.range_state.range_high * 0.9988

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
                scaled_confidence(0.35, ((close / self.range_state.range_high) - 1.0, 180)),
                {"range_high": self.range_state.range_high, "breakout_high": self.range_state.range_high, "retest": 1.0},
            )

        if self.breakout_confirmed and (close <= invalidate_level or momentum_20 < 0):
            self.breakout_confirmed = False
            self.breakout_bar_index = -1
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.7, {"failed_retest": 1.0})

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


__all__ = ["OpeningRangeBreakoutAgent", "RangeRetestContinuationAgent"]


class GER40RangeRejectShortAgent(Agent):
    name = "ger40_range_reject_short"

    def __init__(self) -> None:
        self.range_state = SessionRangeState()
        self.reclaim_seen = False

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
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

        if self.range_state.ensure_day(feature.timestamp):
            self.reclaim_seen = False

        if in_regular_session >= 1.0 and 0 <= minutes_from_open < 30:
            self.range_state.update(high, low)
            return None

        if not self.range_state.ready:
            return None

        if in_regular_session < 1.0 or not (35 <= minutes_from_open <= 180) or hour not in {14, 15, 16}:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        range_span = max(self.range_state.range_high - self.range_state.range_low, close * 0.0006)
        reclaim_level = self.range_state.range_low + (range_span * 0.28)
        invalidate_level = self.range_state.range_high - (range_span * 0.08)

        if high >= reclaim_level:
            self.reclaim_seen = True

        if (
            self.reclaim_seen
            and close < self.range_state.range_low * 0.9999
            and relative_volume >= 0.9
            and trend_strength < -0.0003
            and momentum_20 < 0.0
            and momentum_5 < 0.00015
        ):
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.SELL,
                scaled_confidence(0.3, ((self.range_state.range_low / close) - 1.0, 170)),
                directional_metadata(
                    Side.SELL,
                    short_entry=True,
                    breakout_low=self.range_state.range_low,
                    rebound_high=invalidate_level,
                ),
            )

        if close > invalidate_level or momentum_20 > 0.0:
            self.reclaim_seen = False
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                0.7,
                directional_metadata(Side.BUY, short_exit=True, failed_retest=1.0),
            )

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class GER40FailedBreakoutShortAgent(Agent):
    name = "ger40_failed_breakout_short"

    def __init__(self) -> None:
        self.range_state = SessionRangeState()
        self.up_break_seen = False

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
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

        if self.range_state.ensure_day(feature.timestamp):
            self.up_break_seen = False

        if in_regular_session >= 1.0 and 0 <= minutes_from_open < 30:
            self.range_state.update(high, low)
            return None

        if not self.range_state.ready:
            return None

        if in_regular_session < 1.0 or not (30 <= minutes_from_open <= 150) or hour not in {14, 15}:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        if high > self.range_state.range_high * 1.0005:
            self.up_break_seen = True

        if (
            self.up_break_seen
            and close < self.range_state.range_high * 0.9999
            and relative_volume >= 0.9
            and trend_strength < 0.0001
            and momentum_20 < 0.0
            and momentum_5 < 0.0
        ):
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.SELL,
                scaled_confidence(0.3, ((self.range_state.range_high / close) - 1.0, 160)),
                directional_metadata(
                    Side.SELL,
                    short_entry=True,
                    breakout_low=self.range_state.range_low,
                    rebound_high=self.range_state.range_high,
                    failed_breakout=1.0,
                ),
            )

        if close > self.range_state.range_high * 1.0006 or momentum_20 > 0.0002:
            self.up_break_seen = False
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                0.7,
                directional_metadata(Side.BUY, short_exit=True, trend_flip=1.0),
            )

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


__all__ = [
    "OpeningRangeBreakoutAgent",
    "RangeRetestContinuationAgent",
    "GER40RangeRejectShortAgent",
    "GER40FailedBreakoutShortAgent",
]
