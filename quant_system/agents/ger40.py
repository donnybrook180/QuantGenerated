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
        in_regular_session = feature.values.get("in_regular_session", 1.0)
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


class GER40OpeningDriveFadeLongAgent(Agent):
    name = "ger40_opening_drive_fade_long"

    def __init__(self) -> None:
        self.range_state = SessionRangeState()
        self.drive_low_seen = False
        self.in_position = False

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
            self.drive_low_seen = False

        if 0 <= minutes_from_open < 25:
            self.range_state.update(high, low)
            return None

        if not self.range_state.ready:
            return None

        if not (15 <= minutes_from_open <= 180) or hour not in {8, 9, 10, 11}:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        range_span = max(self.range_state.range_high - self.range_state.range_low, close * 0.0008)
        washout_level = self.range_state.range_low - (range_span * 0.06)
        reclaim_level = self.range_state.range_low + (range_span * 0.02)
        invalidate_level = self.range_state.range_low - (range_span * 0.12)

        if low <= washout_level:
            self.drive_low_seen = True

        if (
            not self.in_position
            and
            self.drive_low_seen
            and close >= reclaim_level
            and relative_volume >= 0.3
            and trend_strength > -0.0012
            and momentum_5 > -0.003
            and momentum_20 > -0.004
        ):
            self.in_position = True
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                scaled_confidence(0.32, ((close / max(reclaim_level, 1e-9)) - 1.0, 220)),
                {"range_low": self.range_state.range_low, "drive_fade": 1.0},
            )

        if self.in_position and (close <= invalidate_level or momentum_20 < -0.003):
            self.in_position = False
            self.drive_low_seen = False
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.68, {"failed_reclaim": 1.0})

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class GER40RangeReclaimLongAgent(Agent):
    name = "ger40_range_reclaim_long"

    def __init__(self) -> None:
        self.range_state = SessionRangeState()
        self.break_below_seen = False
        self.in_position = False

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        high = feature.values.get("high", feature.values["close"])
        low = feature.values.get("low", feature.values["close"])
        close = feature.values["close"]
        relative_volume = feature.values.get("relative_volume", 1.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        in_regular_session = feature.values.get("in_regular_session", 1.0)
        minutes_from_open = feature.values.get("minutes_from_open", -1.0)
        hour = int(feature.values.get("hour_of_day", 0.0))

        if self.range_state.ensure_day(feature.timestamp):
            self.break_below_seen = False

        if 0 <= minutes_from_open < 35:
            self.range_state.update(high, low)
            return None

        if not self.range_state.ready:
            return None

        if not (25 <= minutes_from_open <= 220) or hour not in {8, 9, 10, 11, 12}:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        if low < self.range_state.range_low * 0.9999:
            self.break_below_seen = True

        if (
            not self.in_position
            and
            self.break_below_seen
            and close > self.range_state.range_low * 0.99995
            and relative_volume >= 0.25
            and trend_strength > -0.0015
            and momentum_20 > -0.004
            and momentum_5 > -0.003
        ):
            self.in_position = True
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                scaled_confidence(0.3, ((close / self.range_state.range_low) - 1.0, 210)),
                {"range_low": self.range_state.range_low, "failed_breakdown": 1.0},
            )

        if self.in_position and (close < self.range_state.range_low * 0.9988 or momentum_20 < -0.0045):
            self.in_position = False
            self.break_below_seen = False
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.68, {"range_lost": 1.0})

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class GER40MiddayBreakoutLongAgent(Agent):
    name = "ger40_midday_breakout_long"

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
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        in_regular_session = feature.values.get("in_regular_session", 1.0)
        minutes_from_open = feature.values.get("minutes_from_open", -1.0)
        hour = int(feature.values.get("hour_of_day", 0.0))

        if self.range_state.ensure_day(feature.timestamp):
            pass

        if 0 <= minutes_from_open < 50:
            self.range_state.update(high, low)
            return None

        if not self.range_state.ready:
            return None

        if not (60 <= minutes_from_open <= 320) or hour not in {9, 10, 11, 12, 13}:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        if (
            not self.in_position
            and
            close >= self.range_state.range_high * 0.9996
            and atr_proxy >= 0.0
            and relative_volume >= 0.2
            and trend_strength > -0.0008
            and momentum_20 > -0.003
            and momentum_5 > -0.0035
        ):
            self.in_position = True
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                scaled_confidence(0.28, ((close / self.range_state.range_high) - 1.0, 180)),
                {"range_high": self.range_state.range_high, "midday_breakout": 1.0},
            )

        if self.in_position and (close < self.range_state.range_high * 0.9985 or momentum_20 < -0.0025):
            self.in_position = False
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.65, {"failed_breakout": 1.0})

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class GER40MiddayBreakoutShortAgent(Agent):
    name = "ger40_midday_breakout_short"

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
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        minutes_from_open = feature.values.get("minutes_from_open", -1.0)
        hour = int(feature.values.get("hour_of_day", 0.0))

        if self.range_state.ensure_day(feature.timestamp):
            pass

        if 0 <= minutes_from_open < 50:
            self.range_state.update(high, low)
            return None

        if not self.range_state.ready:
            return None

        if not (60 <= minutes_from_open <= 320) or hour not in {9, 10, 11, 12, 13}:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        if (
            not self.in_position
            and close <= self.range_state.range_low * 1.0004
            and atr_proxy >= 0.0
            and relative_volume >= 0.2
            and trend_strength < 0.0008
            and momentum_20 < 0.003
            and momentum_5 < 0.0035
        ):
            self.in_position = True
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.SELL,
                scaled_confidence(0.28, ((self.range_state.range_low / max(close, 1e-9)) - 1.0, 180)),
                directional_metadata(Side.SELL, short_entry=True, range_low=self.range_state.range_low, midday_breakout=1.0),
            )

        if self.in_position and (close > self.range_state.range_low * 1.0015 or momentum_20 > 0.0025):
            self.in_position = False
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                0.65,
                directional_metadata(Side.BUY, short_exit=True, failed_breakout=1.0),
            )

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class GER40EuropeMeanReversionLongAgent(Agent):
    name = "ger40_europe_mean_reversion_long"

    def __init__(self) -> None:
        self.in_position = False

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        relative_volume = feature.values.get("relative_volume", 1.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        session_position = feature.values.get("session_position", 0.5)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        minutes_from_open = feature.values.get("minutes_from_open", -1.0)
        hour = int(feature.values.get("hour_of_day", 0.0))

        if not (20 <= minutes_from_open <= 220) or hour not in {8, 9, 10, 11}:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        if (
            not self.in_position
            and session_position <= 0.18
            and vwap_distance <= -0.00035
            and relative_volume >= 0.15
            and trend_strength > -0.003
            and momentum_20 > -0.008
            and momentum_5 > -0.01
        ):
            self.in_position = True
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                scaled_confidence(0.26, (abs(vwap_distance), 1600)),
                {"session_position": session_position, "vwap_distance": vwap_distance, "mean_reversion": 1.0},
            )

        if self.in_position and (
            session_position >= 0.48 or vwap_distance >= -0.00002 or momentum_20 < -0.01
        ):
            self.in_position = False
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.62, {"mean_reverted": 1.0})

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class GER40EuropeMeanReversionShortAgent(Agent):
    name = "ger40_europe_mean_reversion_short"

    def __init__(self) -> None:
        self.in_position = False

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        relative_volume = feature.values.get("relative_volume", 1.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        session_position = feature.values.get("session_position", 0.5)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        minutes_from_open = feature.values.get("minutes_from_open", -1.0)
        hour = int(feature.values.get("hour_of_day", 0.0))

        if not (20 <= minutes_from_open <= 220) or hour not in {8, 9, 10, 11}:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        if (
            not self.in_position
            and session_position >= 0.82
            and vwap_distance >= 0.00035
            and relative_volume >= 0.15
            and trend_strength < 0.003
            and momentum_20 < 0.008
            and momentum_5 < 0.01
        ):
            self.in_position = True
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.SELL,
                scaled_confidence(0.26, (abs(vwap_distance), 1600)),
                directional_metadata(
                    Side.SELL,
                    short_entry=True,
                    session_position=session_position,
                    vwap_distance=vwap_distance,
                    mean_reversion=1.0,
                ),
            )

        if self.in_position and (
            session_position <= 0.52 or vwap_distance <= 0.00002 or momentum_20 > 0.01
        ):
            self.in_position = False
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                0.62,
                directional_metadata(Side.BUY, short_exit=True, mean_reverted=1.0),
            )

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


__all__ = [
    "OpeningRangeBreakoutAgent",
    "RangeRetestContinuationAgent",
    "GER40RangeRejectShortAgent",
    "GER40FailedBreakoutShortAgent",
    "GER40OpeningDriveFadeLongAgent",
    "GER40RangeReclaimLongAgent",
    "GER40MiddayBreakoutLongAgent",
    "GER40MiddayBreakoutShortAgent",
    "GER40EuropeMeanReversionLongAgent",
    "GER40EuropeMeanReversionShortAgent",
]
