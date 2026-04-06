from __future__ import annotations

from quant_system.agents.base import Agent
from quant_system.agents.common import directional_metadata, scaled_confidence
from quant_system.models import FeatureVector, Side, SignalEvent


class US500TrendPullbackAgent(Agent):
    name = "us500_trend_pullback"

    def __init__(self, min_trend_strength: float, pullback_z_limit: float = -0.2) -> None:
        self.min_trend_strength = min_trend_strength
        self.pullback_z_limit = pullback_z_limit

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        session_position = feature.values.get("session_position", 0.5)
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        opening_window = feature.values.get("opening_window", 0.0)
        closing_window = feature.values.get("closing_window", 0.0)
        hour = int(feature.values.get("hour_of_day", 0.0))

        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or closing_window > 0.0
            or hour not in {16, 18}
            or relative_volume < 0.85
        ):
            side = Side.FLAT
        elif (
            trend_strength > max(self.min_trend_strength, 0.00045)
            and momentum_20 > 0.0003
            and momentum_5 > -0.0015
            and self.pullback_z_limit >= z_score >= -1.25
            and vwap_distance >= -0.0012
            and session_position >= 0.45
        ):
            side = Side.BUY
        elif trend_strength <= 0 or momentum_20 <= -0.0002 or z_score >= 0.95:
            side = Side.SELL
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.15,
            (max(trend_strength, 0.0), 160),
            (max(momentum_20, 0.0), 120),
            (max(0.0, -z_score), 0.12),
        )
        return SignalEvent(
            timestamp=feature.timestamp,
            agent_name=self.name,
            symbol=feature.symbol,
            side=side,
            confidence=confidence if side != Side.FLAT else 0.0,
            metadata={
                "trend_strength": trend_strength,
                "z_score_20": z_score,
                "vwap_distance": vwap_distance,
                "hour_of_day": float(hour),
            },
        )


class US500VWAPContinuationAgent(Agent):
    name = "us500_vwap_continuation"

    def __init__(self, min_trend_strength: float) -> None:
        self.min_trend_strength = min_trend_strength

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        session_position = feature.values.get("session_position", 0.5)
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        opening_window = feature.values.get("opening_window", 0.0)
        closing_window = feature.values.get("closing_window", 0.0)
        hour = int(feature.values.get("hour_of_day", 0.0))

        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or closing_window > 0.0
            or not (16 <= hour <= 18)
            or relative_volume < 0.9
        ):
            side = Side.FLAT
        elif (
            trend_strength > max(self.min_trend_strength, 0.00055)
            and momentum_20 > 0.00035
            and momentum_5 > 0.0
            and 0.00005 <= vwap_distance <= 0.0018
            and session_position >= 0.55
        ):
            side = Side.BUY
        elif trend_strength <= 0 or momentum_20 <= 0 or vwap_distance < -0.0008:
            side = Side.SELL
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.2,
            (max(trend_strength, 0.0), 170),
            (max(momentum_20, 0.0), 110),
            (max(momentum_5, 0.0), 80),
        )
        return SignalEvent(
            timestamp=feature.timestamp,
            agent_name=self.name,
            symbol=feature.symbol,
            side=side,
            confidence=confidence if side != Side.FLAT else 0.0,
            metadata={
                "trend_strength": trend_strength,
                "vwap_distance": vwap_distance,
                "session_position": session_position,
                "hour_of_day": float(hour),
            },
        )


class US500OpeningDriveReclaimAgent(Agent):
    name = "us500_opening_drive_reclaim"

    def __init__(self, min_trend_strength: float) -> None:
        self.min_trend_strength = min_trend_strength
        self.current_session: tuple[int, int, int] | None = None
        self.opening_high: float | None = None
        self.opening_low: float | None = None
        self.pullback_seen = False

    def _reset_session(self, feature: FeatureVector) -> None:
        timestamp = feature.timestamp
        self.current_session = (timestamp.year, timestamp.month, timestamp.day)
        self.opening_high = None
        self.opening_low = None
        self.pullback_seen = False

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        session_key = (feature.timestamp.year, feature.timestamp.month, feature.timestamp.day)
        if session_key != self.current_session:
            self._reset_session(feature)

        close = feature.values["close"]
        high = feature.values.get("high", close)
        low = feature.values.get("low", close)
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        opening_window = feature.values.get("opening_window", 0.0)
        closing_window = feature.values.get("closing_window", 0.0)
        minutes_from_open = feature.values.get("minutes_from_open", -1.0)
        hour = int(feature.values.get("hour_of_day", 0.0))

        if in_regular_session < 1.0:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        if opening_window > 0.0 or (0.0 <= minutes_from_open <= 20.0):
            self.opening_high = high if self.opening_high is None else max(self.opening_high, high)
            self.opening_low = low if self.opening_low is None else min(self.opening_low, low)
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        if self.opening_high is None or self.opening_low is None:
            return None

        opening_range = max(self.opening_high - self.opening_low, close * 0.0008)
        reclaim_level = self.opening_high - (opening_range * 0.35)
        invalidate_level = self.opening_low + (opening_range * 0.1)

        if low <= reclaim_level:
            self.pullback_seen = True

        if (
            closing_window > 0.0
            or not (15 <= hour <= 17)
            or not (20.0 <= minutes_from_open <= 120.0)
            or relative_volume < 0.8
        ):
            side = Side.FLAT
        elif (
            self.pullback_seen
            and trend_strength > max(self.min_trend_strength, 0.00025)
            and momentum_20 > 0.00015
            and momentum_5 > -0.0002
            and -0.9 <= z_score <= 0.8
            and close >= reclaim_level
            and close > invalidate_level
        ):
            side = Side.BUY
        elif trend_strength <= 0 or momentum_20 <= 0 or close < invalidate_level:
            side = Side.SELL
            self.pullback_seen = False
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.18,
            (max(trend_strength, 0.0), 180),
            (max(momentum_20, 0.0), 110),
            (max(momentum_5, 0.0), 90),
        )
        return SignalEvent(
            timestamp=feature.timestamp,
            agent_name=self.name,
            symbol=feature.symbol,
            side=side,
            confidence=confidence if side != Side.FLAT else 0.0,
            metadata={
                "opening_high": self.opening_high,
                "opening_low": self.opening_low,
                "breakout_high": reclaim_level,
                "hour_of_day": float(hour),
            },
        )

class US500ShortTrendRejectionAgent(Agent):
    name = "us500_short_trend_rejection"

    def __init__(
        self,
        min_trend_strength: float,
        rebound_z_limit: float = 0.35,
        allowed_hours: set[int] | None = None,
        min_relative_volume: float = 0.85,
    ) -> None:
        self.min_trend_strength = min_trend_strength
        self.rebound_z_limit = rebound_z_limit
        self.allowed_hours = allowed_hours
        self.min_relative_volume = min_relative_volume

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        session_position = feature.values.get("session_position", 0.5)
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        opening_window = feature.values.get("opening_window", 0.0)
        closing_window = feature.values.get("closing_window", 0.0)
        hour = int(feature.values.get("hour_of_day", 0.0))

        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or closing_window > 0.0
            or hour not in (self.allowed_hours if self.allowed_hours is not None else {16, 17})
            or relative_volume < self.min_relative_volume
        ):
            side = Side.FLAT
        elif (
            trend_strength < -max(self.min_trend_strength, 0.0004)
            and momentum_20 < -0.0002
            and momentum_5 < 0.0004
            and self.rebound_z_limit <= z_score <= 1.2
            and -0.0002 <= vwap_distance <= 0.0016
            and session_position <= 0.58
        ):
            side = Side.SELL
        elif trend_strength >= 0 or momentum_20 >= 0.00015 or z_score <= -0.9:
            side = Side.BUY
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.16,
            (max(-trend_strength, 0.0), 170),
            (max(-momentum_20, 0.0), 120),
            (max(z_score, 0.0), 0.12),
        )
        metadata = directional_metadata(
            side,
            short_entry=True,
            short_exit=True,
            trend_strength=trend_strength,
            z_score_20=z_score,
            vwap_distance=vwap_distance,
            hour_of_day=float(hour),
        )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, side, confidence if side != Side.FLAT else 0.0, metadata)


class US500OpeningDriveShortReclaimAgent(Agent):
    name = "us500_opening_drive_short_reclaim"

    def __init__(
        self,
        min_trend_strength: float,
        allowed_hours: set[int] | None = None,
        min_relative_volume: float = 0.8,
        max_session_position: float = 0.55,
    ) -> None:
        self.min_trend_strength = min_trend_strength
        self.allowed_hours = allowed_hours
        self.min_relative_volume = min_relative_volume
        self.max_session_position = max_session_position
        self.current_session: tuple[int, int, int] | None = None
        self.opening_high: float | None = None
        self.opening_low: float | None = None
        self.rebound_seen = False

    def _reset_session(self, feature: FeatureVector) -> None:
        timestamp = feature.timestamp
        self.current_session = (timestamp.year, timestamp.month, timestamp.day)
        self.opening_high = None
        self.opening_low = None
        self.rebound_seen = False

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        session_key = (feature.timestamp.year, feature.timestamp.month, feature.timestamp.day)
        if session_key != self.current_session:
            self._reset_session(feature)

        close = feature.values["close"]
        high = feature.values.get("high", close)
        low = feature.values.get("low", close)
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        session_position = feature.values.get("session_position", 0.5)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        opening_window = feature.values.get("opening_window", 0.0)
        closing_window = feature.values.get("closing_window", 0.0)
        minutes_from_open = feature.values.get("minutes_from_open", -1.0)
        hour = int(feature.values.get("hour_of_day", 0.0))

        if in_regular_session < 1.0:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        if opening_window > 0.0 or (0.0 <= minutes_from_open <= 20.0):
            self.opening_high = high if self.opening_high is None else max(self.opening_high, high)
            self.opening_low = low if self.opening_low is None else min(self.opening_low, low)
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        if self.opening_high is None or self.opening_low is None:
            return None

        opening_range = max(self.opening_high - self.opening_low, close * 0.0008)
        reclaim_level = self.opening_low + (opening_range * 0.35)
        invalidate_level = self.opening_high - (opening_range * 0.1)

        if high >= reclaim_level:
            self.rebound_seen = True

        if (
            closing_window > 0.0
            or hour not in (self.allowed_hours if self.allowed_hours is not None else {15, 16, 17})
            or not (20.0 <= minutes_from_open <= 120.0)
            or relative_volume < self.min_relative_volume
        ):
            side = Side.FLAT
        elif (
            self.rebound_seen
            and trend_strength < -max(self.min_trend_strength, 0.00025)
            and momentum_20 < -0.00015
            and momentum_5 < 0.0002
            and 0.05 <= z_score <= 1.05
            and close <= reclaim_level
            and close < invalidate_level
            and session_position <= self.max_session_position
        ):
            side = Side.SELL
        elif trend_strength >= 0 or momentum_20 >= 0 or close > invalidate_level:
            side = Side.BUY
            self.rebound_seen = False
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.18,
            (max(-trend_strength, 0.0), 180),
            (max(-momentum_20, 0.0), 110),
            (max(0.0, -momentum_5), 90),
        )
        metadata = directional_metadata(
            side,
            short_entry=True,
            short_exit=True,
            opening_high=self.opening_high,
            opening_low=self.opening_low,
            breakout_low=reclaim_level,
            session_position=session_position,
            hour_of_day=float(hour),
        )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, side, confidence if side != Side.FLAT else 0.0, metadata)


__all__ = [
    "US500TrendPullbackAgent",
    "US500VWAPContinuationAgent",
    "US500OpeningDriveReclaimAgent",
    "US500ShortTrendRejectionAgent",
    "US500OpeningDriveShortReclaimAgent",
]
