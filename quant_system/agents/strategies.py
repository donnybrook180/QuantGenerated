from __future__ import annotations

from quant_system.agents.base import Agent
from quant_system.agents.common import RollingHighLowState, SessionRangeState, directional_metadata, scaled_confidence
from quant_system.models import FeatureVector, Side, SignalEvent


class OpeningRangeBreakoutAgent(Agent):
    name = "opening_range_breakout"

    def __init__(self) -> None:
        self.range_state = SessionRangeState()
        self.breakout_side: Side = Side.FLAT

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        high = feature.values.get("high", feature.values["close"])
        low = feature.values.get("low", feature.values["close"])
        close = feature.values["close"]
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        minutes_from_open = feature.values.get("minutes_from_open", -1.0)

        if self.range_state.ensure_day(feature.timestamp):
            self.breakout_side = Side.FLAT

        if in_regular_session >= 1.0 and 0 <= minutes_from_open < 30:
            self.range_state.update(high, low)
            return None

        if not self.range_state.ready:
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
            and close > self.range_state.range_high * (1.0 + breakout_buffer)
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
                scaled_confidence(0.35, ((close / self.range_state.range_high) - 1.0, 220)),
                {"range_high": self.range_state.range_high, "breakout_high": self.range_state.range_high},
            )
        if self.breakout_side == Side.BUY and close < self.range_state.range_high:
            self.breakout_side = Side.FLAT
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.7, {"failed_breakout": 1.0})
        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class OpeningRangeShortBreakdownAgent(Agent):
    name = "opening_range_short_breakdown"

    def __init__(self) -> None:
        self.range_state = SessionRangeState()
        self.breakdown_active = False

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        high = feature.values.get("high", feature.values["close"])
        low = feature.values.get("low", feature.values["close"])
        close = feature.values["close"]
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        minutes_from_open = feature.values.get("minutes_from_open", -1.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)

        if self.range_state.ensure_day(feature.timestamp):
            self.breakdown_active = False

        if in_regular_session >= 1.0 and 0 <= minutes_from_open < 30:
            self.range_state.update(high, low)
            return None

        if not self.range_state.ready:
            return None

        if in_regular_session < 1.0 or not (30 <= minutes_from_open <= 90):
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        breakdown_buffer = 0.0009
        hour = int(feature.values.get("hour_of_day", 0.0))
        minute = feature.timestamp.minute
        if (
            hour == 14
            and minute in {0, 15, 40}
            and close < self.range_state.range_low * (1.0 - breakdown_buffer)
            and relative_volume >= 0.95
            and trend_strength < -0.0004
            and momentum_20 < 0.0
        ):
            self.breakdown_active = True
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.SELL,
                scaled_confidence(0.35, ((self.range_state.range_low / close) - 1.0, 220)),
                directional_metadata(
                    Side.SELL,
                    short_entry=True,
                    breakout_low=self.range_state.range_low,
                    rebound_high=self.range_state.range_high,
                ),
            )
        if self.breakdown_active and close > self.range_state.range_low:
            self.breakdown_active = False
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                0.7,
                directional_metadata(Side.BUY, short_exit=True, failed_breakdown=1.0),
            )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class VolatilityBreakoutAgent(Agent):
    name = "volatility_breakout"

    def __init__(self, lookback: int = 12, allowed_hours: set[int] | None = None) -> None:
        self.range_state = RollingHighLowState(lookback)
        self.breakout_side: Side = Side.FLAT
        self.entry_anchor: float | None = None
        self.allowed_hours = allowed_hours

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        high = feature.values.get("high", feature.values["close"])
        low = feature.values.get("low", feature.values["close"])
        close = feature.values["close"]
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        hour = int(feature.values.get("hour_of_day", 0))
        trend_strength = feature.values.get("trend_strength", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)

        self.range_state.append(high, low)
        if not self.range_state.ready:
            return None

        breakout_high = self.range_state.breakout_high()
        breakout_low = self.range_state.breakout_low()

        if self.allowed_hours is not None and hour not in self.allowed_hours:
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
            confidence = scaled_confidence(0.35, ((close / breakout_high) - 1.0, 300), (abs(trend_strength), 100))
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


class VolatilityShortBreakdownAgent(Agent):
    name = "volatility_short_breakdown"

    def __init__(self, lookback: int = 12, allowed_hours: set[int] | None = None) -> None:
        self.range_state = RollingHighLowState(lookback)
        self.breakdown_active = False
        self.entry_anchor: float | None = None
        self.allowed_hours = allowed_hours

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        high = feature.values.get("high", feature.values["close"])
        low = feature.values.get("low", feature.values["close"])
        close = feature.values["close"]
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        hour = int(feature.values.get("hour_of_day", 0))
        trend_strength = feature.values.get("trend_strength", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)

        self.range_state.append(high, low)
        if not self.range_state.ready:
            return None

        breakout_low = self.range_state.breakout_low()
        rebound_high = self.range_state.recent_high()

        if self.allowed_hours is not None and hour not in self.allowed_hours:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        if (
            not self.breakdown_active
            and close < breakout_low
            and atr_proxy > 0.0005
            and trend_strength < -0.0003
            and momentum_20 < 0.0
            and relative_volume >= 1.0
        ):
            self.breakdown_active = True
            self.entry_anchor = breakout_low
            confidence = scaled_confidence(0.35, ((breakout_low / close) - 1.0, 300), (abs(trend_strength), 100))
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.SELL,
                confidence,
                directional_metadata(Side.SELL, short_entry=True, breakout_low=breakout_low, rebound_high=rebound_high),
            )
        if self.breakdown_active and (
            trend_strength > 0.00025
            or momentum_20 > 0
            or (self.entry_anchor is not None and close > rebound_high)
        ):
            self.breakdown_active = False
            self.entry_anchor = None
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                0.7,
                directional_metadata(Side.BUY, short_exit=True, trend_flip=1.0),
            )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
