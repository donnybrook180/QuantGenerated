from __future__ import annotations

from quant_system.agents.base import Agent
from quant_system.agents.common import RollingCloseState, RollingHighLowState, SessionRangeState, directional_metadata, scaled_confidence
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

    def __init__(
        self,
        lookback: int = 12,
        allowed_hours: set[int] | None = None,
        min_atr_proxy: float = 0.0005,
        min_trend_strength: float = 0.0003,
        min_relative_volume: float = 1.0,
        min_momentum_20: float = 0.0,
    ) -> None:
        self.range_state = RollingHighLowState(lookback)
        self.breakout_side: Side = Side.FLAT
        self.entry_anchor: float | None = None
        self.allowed_hours = allowed_hours
        self.min_atr_proxy = min_atr_proxy
        self.min_trend_strength = min_trend_strength
        self.min_relative_volume = min_relative_volume
        self.min_momentum_20 = min_momentum_20

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
            and atr_proxy > self.min_atr_proxy
            and trend_strength > self.min_trend_strength
            and momentum_20 > self.min_momentum_20
            and relative_volume >= self.min_relative_volume
        ):
            self.breakout_side = Side.BUY
            self.entry_anchor = breakout_high
            confidence = scaled_confidence(0.35, ((close / breakout_high) - 1.0, 300), (abs(trend_strength), 100))
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.BUY, confidence, {"breakout_high": breakout_high})
        if (
            close < breakout_low
            and atr_proxy > self.min_atr_proxy
            and trend_strength < -self.min_trend_strength
            and momentum_20 < -self.min_momentum_20
            and relative_volume >= self.min_relative_volume
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

    def __init__(
        self,
        lookback: int = 12,
        allowed_hours: set[int] | None = None,
        min_atr_proxy: float = 0.0005,
        min_trend_strength: float = 0.0003,
        min_relative_volume: float = 1.0,
        min_momentum_20: float = 0.0,
    ) -> None:
        self.range_state = RollingHighLowState(lookback)
        self.breakdown_active = False
        self.entry_anchor: float | None = None
        self.allowed_hours = allowed_hours
        self.min_atr_proxy = min_atr_proxy
        self.min_trend_strength = min_trend_strength
        self.min_relative_volume = min_relative_volume
        self.min_momentum_20 = min_momentum_20

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
            and atr_proxy > self.min_atr_proxy
            and trend_strength < -self.min_trend_strength
            and momentum_20 < -self.min_momentum_20
            and relative_volume >= self.min_relative_volume
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


class AfternoonDownsideContinuationAgent(Agent):
    name = "afternoon_downside_continuation"

    def __init__(
        self,
        allowed_hours: set[int] | None = None,
        min_trend_strength: float = 0.00035,
        min_relative_volume: float = 0.85,
        max_z_score: float = 0.4,
    ) -> None:
        self.allowed_hours = allowed_hours or {15, 16, 17, 18}
        self.min_trend_strength = min_trend_strength
        self.min_relative_volume = min_relative_volume
        self.max_z_score = max_z_score

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        opening_window = feature.values.get("opening_window", 0.0)
        closing_window = feature.values.get("closing_window", 0.0)
        session_position = feature.values.get("session_position", 0.5)
        hour = int(feature.values.get("hour_of_day", 0.0))

        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or closing_window > 0.0
            or hour not in self.allowed_hours
            or relative_volume < self.min_relative_volume
        ):
            side = Side.FLAT
        elif (
            trend_strength < -self.min_trend_strength
            and momentum_20 < -0.00015
            and momentum_5 < 0.0001
            and z_score <= self.max_z_score
            and vwap_distance <= -0.00015
            and session_position >= 0.35
        ):
            side = Side.SELL
        elif trend_strength > 0.0002 or momentum_20 > 0.0 or vwap_distance > 0.0002:
            side = Side.BUY
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.2,
            (max(-trend_strength, 0.0), 150),
            (max(-momentum_20, 0.0), 120),
            (max(-vwap_distance, 0.0), 180),
            (max(0.0, self.max_z_score - z_score), 0.25),
        )
        return SignalEvent(
            feature.timestamp,
            self.name,
            feature.symbol,
            side,
            confidence if side != Side.FLAT else 0.0,
            directional_metadata(
                side,
                trend_strength=trend_strength,
                momentum_20=momentum_20,
                vwap_distance=vwap_distance,
                session_position=session_position,
                close=close,
            ),
        )


class FailedBounceShortAgent(Agent):
    name = "failed_bounce_short"

    def __init__(
        self,
        lookback: int = 6,
        allowed_hours: set[int] | None = None,
        min_relative_volume: float = 0.82,
        min_negative_trend: float = 0.00035,
        min_z_score: float = 0.25,
    ) -> None:
        self.state = RollingCloseState(lookback)
        self.allowed_hours = allowed_hours or {15, 16, 17}
        self.min_relative_volume = min_relative_volume
        self.min_negative_trend = min_negative_trend
        self.min_z_score = min_z_score

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        self.state.append(close)
        if not self.state.ready:
            return None

        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        opening_window = feature.values.get("opening_window", 0.0)
        closing_window = feature.values.get("closing_window", 0.0)
        session_position = feature.values.get("session_position", 0.5)
        hour = int(feature.values.get("hour_of_day", 0.0))

        recent_high = self.state.recent_high(4)
        recent_mean = self.state.mean()
        failed_bounce = close < recent_high * 0.9992 and close <= recent_mean

        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or closing_window > 0.0
            or hour not in self.allowed_hours
            or relative_volume < self.min_relative_volume
        ):
            side = Side.FLAT
        elif (
            failed_bounce
            and trend_strength <= -self.min_negative_trend
            and momentum_20 < -0.0001
            and momentum_5 <= 0.00015
            and z_score >= self.min_z_score
            and vwap_distance <= 0.00025
            and session_position >= 0.30
        ):
            side = Side.SELL
        elif trend_strength > 0.0002 or momentum_20 > 0.0 or vwap_distance > 0.00035:
            side = Side.BUY
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.18,
            (max(-trend_strength, 0.0), 150),
            (max(z_score - self.min_z_score, 0.0), 0.22),
            (max(recent_high - close, 0.0), 180),
        )
        return SignalEvent(
            feature.timestamp,
            self.name,
            feature.symbol,
            side,
            confidence if side != Side.FLAT else 0.0,
            directional_metadata(
                side,
                short_entry=True,
                short_exit=True,
                trend_strength=trend_strength,
                z_score_20=z_score,
                vwap_distance=vwap_distance,
                recent_high=recent_high,
                recent_mean=recent_mean,
                session_position=session_position,
            ),
        )


class FailedBreakdownReclaimLongAgent(Agent):
    name = "failed_breakdown_reclaim_long"

    def __init__(
        self,
        lookback: int = 6,
        allowed_hours: set[int] | None = None,
        min_relative_volume: float = 0.75,
        min_negative_extension: float = 0.00025,
        max_negative_trend: float = 0.0015,
    ) -> None:
        self.state = RollingCloseState(lookback)
        self.allowed_hours = allowed_hours or {0, 1, 2, 8, 9, 10}
        self.min_relative_volume = min_relative_volume
        self.min_negative_extension = min_negative_extension
        self.max_negative_trend = max_negative_trend

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        self.state.append(close)
        if not self.state.ready:
            return None

        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        opening_window = feature.values.get("opening_window", 0.0)
        closing_window = feature.values.get("closing_window", 0.0)
        session_position = feature.values.get("session_position", 0.5)
        hour = int(feature.values.get("hour_of_day", 0.0))

        recent_low = self.state.recent_low(4)
        recent_mean = self.state.mean()
        reclaiming = close > recent_low * 1.0008 and close >= recent_mean

        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or closing_window > 0.0
            or hour not in self.allowed_hours
            or relative_volume < self.min_relative_volume
        ):
            side = Side.FLAT
        elif (
            reclaiming
            and trend_strength >= -self.max_negative_trend
            and momentum_20 > -self.min_negative_extension
            and momentum_5 > -0.0002
            and z_score <= -0.20
            and vwap_distance <= -0.00015
            and session_position <= 0.75
        ):
            side = Side.BUY
        elif trend_strength < -0.0018 or momentum_20 < -0.0008 or vwap_distance < -0.0009:
            side = Side.SELL
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.18,
            (max(recent_mean - recent_low, 0.0), 140),
            (max(-z_score - 0.20, 0.0), 0.18),
            (max(close - recent_low, 0.0), 180),
        )
        return SignalEvent(
            feature.timestamp,
            self.name,
            feature.symbol,
            side,
            confidence if side != Side.FLAT else 0.0,
            directional_metadata(
                side,
                trend_strength=trend_strength,
                z_score_20=z_score,
                vwap_distance=vwap_distance,
                recent_low=recent_low,
                recent_mean=recent_mean,
                session_position=session_position,
            ),
        )


class JP225OpenDriveMeanReversionLongAgent(Agent):
    name = "jp225_open_drive_mean_reversion_long"

    def __init__(self) -> None:
        self.range_state = SessionRangeState()
        self.in_position = False

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        high = feature.values.get("high", feature.values["close"])
        low = feature.values.get("low", feature.values["close"])
        close = feature.values["close"]
        relative_volume = feature.values.get("relative_volume", 1.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        minutes_from_open = feature.values.get("minutes_from_open", -1.0)

        if self.range_state.ensure_day(feature.timestamp):
            self.in_position = False

        if in_regular_session >= 1.0 and 0 <= minutes_from_open < 25:
            self.range_state.update(high, low)
            return None

        if not self.range_state.ready:
            return None

        if in_regular_session < 1.0 or not (25 <= minutes_from_open <= 120):
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        range_span = max(self.range_state.range_high - self.range_state.range_low, close * 0.0006)
        reclaim_level = self.range_state.range_low + (range_span * 0.18)
        invalidate_level = self.range_state.range_low - (range_span * 0.08)

        if (
            not self.in_position
            and low <= self.range_state.range_low * 1.0002
            and close >= reclaim_level
            and relative_volume >= 0.75
            and trend_strength > -0.0008
            and momentum_20 > -0.0012
            and momentum_5 > -0.0006
            and vwap_distance > -0.0018
        ):
            self.in_position = True
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                scaled_confidence(0.24, (max(close - reclaim_level, 0.0), 160)),
                {"range_low": self.range_state.range_low, "reclaim_level": reclaim_level, "open_drive_fade": 1.0},
            )

        if self.in_position and (close <= invalidate_level or momentum_20 < -0.0018 or vwap_distance < -0.0022):
            self.in_position = False
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.65, {"failed_reclaim": 1.0})

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class JP225AsiaContinuationLongAgent(Agent):
    name = "jp225_asia_continuation_long"

    def __init__(self, lookback: int = 8) -> None:
        self.range_state = RollingHighLowState(lookback)
        self.in_position = False
        self.entry_anchor: float | None = None

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        high = feature.values.get("high", feature.values["close"])
        low = feature.values.get("low", feature.values["close"])
        close = feature.values["close"]
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        minutes_from_open = feature.values.get("minutes_from_open", -1.0)

        self.range_state.append(high, low)
        if not self.range_state.ready:
            return None

        if in_regular_session < 1.0 or not (45 <= minutes_from_open <= 240):
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        breakout_high = self.range_state.breakout_high()

        if (
            not self.in_position
            and close >= breakout_high * 1.00015
            and atr_proxy >= 0.0
            and relative_volume >= 0.8
            and trend_strength > 0.0002
            and momentum_20 > 0.00005
            and momentum_5 > -0.00015
        ):
            self.in_position = True
            self.entry_anchor = breakout_high
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                scaled_confidence(0.24, (max(close - breakout_high, 0.0), 170), (max(trend_strength, 0.0), 120)),
                {"breakout_high": breakout_high, "asia_continuation": 1.0},
            )

        if self.in_position and (
            (self.entry_anchor is not None and close < self.entry_anchor * 0.9993)
            or momentum_20 < -0.00035
            or trend_strength < -0.00025
        ):
            self.in_position = False
            self.entry_anchor = None
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.65, {"trend_flip": 1.0})

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
