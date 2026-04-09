from __future__ import annotations

from quant_system.agents.base import Agent
from quant_system.agents.common import RollingCloseState, directional_metadata, scaled_confidence
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


class US500MomentumImpulseAgent(Agent):
    name = "us500_momentum_impulse"

    def __init__(
        self,
        min_trend_strength: float,
        allowed_hours: set[int] | None = None,
        min_relative_volume: float = 0.9,
    ) -> None:
        self.min_trend_strength = min_trend_strength
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
            or hour not in (self.allowed_hours if self.allowed_hours is not None else {16, 17, 18})
            or relative_volume < self.min_relative_volume
        ):
            side = Side.FLAT
        elif (
            trend_strength > max(self.min_trend_strength, 0.00055)
            and momentum_20 > 0.00045
            and momentum_5 > 0.00015
            and 0.1 <= z_score <= 1.1
            and 0.00005 <= vwap_distance <= 0.0018
            and session_position >= 0.55
        ):
            side = Side.BUY
        elif trend_strength <= 0.0 or momentum_20 <= 0.0 or momentum_5 <= -0.00025 or z_score < -0.6:
            side = Side.SELL
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.18,
            (max(trend_strength, 0.0), 180),
            (max(momentum_20, 0.0), 120),
            (max(momentum_5, 0.0), 100),
        )
        return SignalEvent(
            timestamp=feature.timestamp,
            agent_name=self.name,
            symbol=feature.symbol,
            side=side,
            confidence=confidence if side != Side.FLAT else 0.0,
            metadata={
                "trend_strength": trend_strength,
                "momentum_20": momentum_20,
                "vwap_distance": vwap_distance,
                "session_position": session_position,
                "hour_of_day": float(hour),
            },
        )


class US500ShortVWAPRejectAgent(Agent):
    name = "us500_short_vwap_reject"

    def __init__(
        self,
        min_trend_strength: float,
        allowed_hours: set[int] | None = None,
        min_relative_volume: float = 0.88,
    ) -> None:
        self.min_trend_strength = min_trend_strength
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
            trend_strength < max(self.min_trend_strength * 0.5, 0.0001)
            and momentum_20 <= 0.0001
            and momentum_5 < 0.0
            and 0.2 <= z_score <= 1.1
            and 0.0 <= vwap_distance <= 0.0015
            and session_position <= 0.62
        ):
            side = Side.SELL
        elif trend_strength > max(self.min_trend_strength, 0.0004) or momentum_20 > 0.0002 or z_score < -0.7:
            side = Side.BUY
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.17,
            (max(z_score, 0.0), 0.14),
            (max(-momentum_5, 0.0), 120),
            (max(0.0, -trend_strength), 140),
        )
        metadata = directional_metadata(
            side,
            short_entry=True,
            short_exit=True,
            trend_strength=trend_strength,
            momentum_20=momentum_20,
            vwap_distance=vwap_distance,
            session_position=session_position,
            hour_of_day=float(hour),
        )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, side, confidence if side != Side.FLAT else 0.0, metadata)


class US500FlatHighReversalAgent(Agent):
    name = "us500_flat_high_reversal"

    def __init__(
        self,
        max_abs_trend_strength: float = 0.00055,
        min_relative_volume: float = 0.82,
        allowed_hours: set[int] | None = None,
        min_z_score: float = 0.85,
    ) -> None:
        self.max_abs_trend_strength = max_abs_trend_strength
        self.min_relative_volume = min_relative_volume
        self.allowed_hours = allowed_hours or {15, 16, 17}
        self.min_z_score = min_z_score

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
            or hour not in self.allowed_hours
            or relative_volume < self.min_relative_volume
        ):
            side = Side.FLAT
        elif (
            abs(trend_strength) <= self.max_abs_trend_strength
            and z_score >= self.min_z_score
            and vwap_distance >= 0.0002
            and momentum_5 <= 0.00025
            and momentum_20 <= 0.00035
            and 0.28 <= session_position <= 0.82
        ):
            side = Side.SELL
        elif z_score < 0.15 or vwap_distance < -0.0002 or momentum_5 < -0.00045:
            side = Side.BUY
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.16,
            (max(z_score - self.min_z_score, 0.0), 0.35),
            (max(vwap_distance, 0.0), 220),
            (max(self.max_abs_trend_strength - abs(trend_strength), 0.0), 800),
        )
        metadata = directional_metadata(
            side,
            short_entry=True,
            short_exit=True,
            trend_strength=trend_strength,
            z_score_20=z_score,
            vwap_distance=vwap_distance,
            session_position=session_position,
            hour_of_day=float(hour),
        )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, side, confidence if side != Side.FLAT else 0.0, metadata)


class US500FlatTapeMeanReversionAgent(Agent):
    name = "us500_flat_tape_mean_reversion"

    def __init__(
        self,
        lookback: int = 8,
        max_abs_trend_strength: float = 0.00055,
        min_relative_volume: float = 0.78,
        allowed_hours: set[int] | None = None,
        min_abs_z_score: float = 0.9,
    ) -> None:
        self.state = RollingCloseState(lookback)
        self.max_abs_trend_strength = max_abs_trend_strength
        self.min_relative_volume = min_relative_volume
        self.allowed_hours = allowed_hours or {15, 16, 17}
        self.min_abs_z_score = min_abs_z_score

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
        session_position = feature.values.get("session_position", 0.5)
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        opening_window = feature.values.get("opening_window", 0.0)
        closing_window = feature.values.get("closing_window", 0.0)
        hour = int(feature.values.get("hour_of_day", 0.0))

        rolling_mean = self.state.mean()
        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or closing_window > 0.0
            or hour not in self.allowed_hours
            or relative_volume < self.min_relative_volume
        ):
            side = Side.FLAT
        elif (
            abs(trend_strength) <= self.max_abs_trend_strength
            and abs(momentum_20) <= 0.00045
            and z_score >= self.min_abs_z_score
            and vwap_distance >= 0.00035
            and momentum_5 <= 0.0002
            and 0.25 <= session_position <= 0.85
            and close >= rolling_mean
        ):
            side = Side.SELL
        elif (
            abs(trend_strength) <= self.max_abs_trend_strength
            and abs(momentum_20) <= 0.00045
            and z_score <= -self.min_abs_z_score
            and vwap_distance <= -0.00035
            and momentum_5 >= -0.0002
            and 0.25 <= session_position <= 0.85
            and close <= rolling_mean
        ):
            side = Side.BUY
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.14,
            (max(abs(z_score) - self.min_abs_z_score, 0.0), 0.28),
            (max(abs(vwap_distance) - 0.00035, 0.0), 220),
            (max(self.max_abs_trend_strength - abs(trend_strength), 0.0), 900),
        )
        metadata = directional_metadata(
            side,
            short_entry=side == Side.SELL,
            short_exit=side == Side.BUY,
            trend_strength=trend_strength,
            z_score_20=z_score,
            vwap_distance=vwap_distance,
            rolling_mean=rolling_mean,
            session_position=session_position,
            hour_of_day=float(hour),
        )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, side, confidence if side != Side.FLAT else 0.0, metadata)


class US500OvernightGapFadeAgent(Agent):
    name = "us500_overnight_gap_fade"

    def __init__(
        self,
        min_gap_pct: float = 0.0015,
        max_abs_trend_strength: float = 0.0007,
        min_relative_volume: float = 0.82,
    ) -> None:
        self.min_gap_pct = min_gap_pct
        self.max_abs_trend_strength = max_abs_trend_strength
        self.min_relative_volume = min_relative_volume

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        opening_window = feature.values.get("opening_window", 0.0)
        morning_session = feature.values.get("morning_session", 0.0)
        midday_session = feature.values.get("midday_session", 0.0)
        opening_gap_pct = feature.values.get("opening_gap_pct", 0.0)
        distance_to_prior_day_close = feature.values.get("distance_to_prior_day_close", 0.0)
        distance_to_overnight_high = feature.values.get("distance_to_overnight_high", 0.0)
        distance_to_overnight_low = feature.values.get("distance_to_overnight_low", 0.0)

        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or (morning_session < 1.0 and midday_session < 1.0)
            or relative_volume < self.min_relative_volume
        ):
            side = Side.FLAT
        elif (
            opening_gap_pct >= self.min_gap_pct
            and abs(trend_strength) <= self.max_abs_trend_strength
            and z_score >= 0.9
            and vwap_distance >= 0.0004
            and momentum_5 <= 0.0002
            and distance_to_prior_day_close > 0.0
            and distance_to_overnight_high <= 0.0001
        ):
            side = Side.SELL
        elif (
            opening_gap_pct <= -self.min_gap_pct
            and abs(trend_strength) <= self.max_abs_trend_strength
            and z_score <= -0.9
            and vwap_distance <= -0.0004
            and momentum_5 >= -0.0002
            and distance_to_prior_day_close < 0.0
            and distance_to_overnight_low >= -0.0001
        ):
            side = Side.BUY
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.16,
            (max(abs(opening_gap_pct) - self.min_gap_pct, 0.0), 120),
            (max(abs(z_score) - 0.9, 0.0), 0.25),
            (max(abs(vwap_distance) - 0.0004, 0.0), 180),
        )
        metadata = directional_metadata(
            side,
            short_entry=side == Side.SELL,
            short_exit=side == Side.BUY,
            opening_gap_pct=opening_gap_pct,
            distance_to_prior_day_close=distance_to_prior_day_close,
            distance_to_overnight_high=distance_to_overnight_high,
            distance_to_overnight_low=distance_to_overnight_low,
            vwap_distance=vwap_distance,
        )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, side, confidence if side != Side.FLAT else 0.0, metadata)


class US500FailedBreakdownReclaimAgent(Agent):
    name = "us500_failed_breakdown_reclaim"

    def __init__(
        self,
        max_abs_trend_strength: float = 0.0009,
        min_relative_volume: float = 0.82,
    ) -> None:
        self.max_abs_trend_strength = max_abs_trend_strength
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
        morning_session = feature.values.get("morning_session", 0.0)
        midday_session = feature.values.get("midday_session", 0.0)
        failed_prior = feature.values.get("failed_break_below_prior_day_low", 0.0)
        failed_overnight = feature.values.get("failed_break_below_overnight_low", 0.0)
        reclaimed_prior = feature.values.get("reclaimed_prior_day_low", 0.0)
        reclaimed_overnight = feature.values.get("reclaimed_overnight_low", 0.0)

        trigger = max(failed_prior, failed_overnight, reclaimed_prior, reclaimed_overnight)

        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or closing_window > 0.0
            or (morning_session < 1.0 and midday_session < 1.0)
            or relative_volume < self.min_relative_volume
        ):
            side = Side.FLAT
        elif (
            trigger > 0.0
            and abs(trend_strength) <= self.max_abs_trend_strength
            and z_score <= -0.2
            and momentum_5 >= -0.0006
            and momentum_20 >= -0.0005
            and vwap_distance >= -0.0012
            and 0.15 <= session_position <= 0.65
        ):
            side = Side.BUY
        elif trend_strength < -0.0012 or momentum_20 < -0.001 or vwap_distance < -0.002:
            side = Side.SELL
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.16,
            (trigger, 0.35),
            (max(-z_score, 0.0), 0.12),
            (max(self.max_abs_trend_strength - abs(trend_strength), 0.0), 700),
        )
        metadata = directional_metadata(
            side,
            short_entry=False,
            short_exit=True,
            failed_break_below_prior_day_low=failed_prior,
            failed_break_below_overnight_low=failed_overnight,
            reclaimed_prior_day_low=reclaimed_prior,
            reclaimed_overnight_low=reclaimed_overnight,
            trend_strength=trend_strength,
            z_score_20=z_score,
            vwap_distance=vwap_distance,
        )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, side, confidence if side != Side.FLAT else 0.0, metadata)


class US500FailedUpsideRejectShortAgent(Agent):
    name = "us500_failed_upside_reject_short"

    def __init__(
        self,
        min_negative_trend: float = 0.00035,
        min_relative_volume: float = 0.82,
    ) -> None:
        self.min_negative_trend = min_negative_trend
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
        morning_session = feature.values.get("morning_session", 0.0)
        midday_session = feature.values.get("midday_session", 0.0)
        failed_prior = feature.values.get("failed_break_above_prior_day_high", 0.0)
        failed_overnight = feature.values.get("failed_break_above_overnight_high", 0.0)
        reclaimed_prior = feature.values.get("reclaimed_prior_day_high", 0.0)
        reclaimed_overnight = feature.values.get("reclaimed_overnight_high", 0.0)

        trigger = max(failed_prior, failed_overnight, reclaimed_prior, reclaimed_overnight)

        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or closing_window > 0.0
            or (morning_session < 1.0 and midday_session < 1.0)
            or relative_volume < self.min_relative_volume
        ):
            side = Side.FLAT
        elif (
            trigger > 0.0
            and trend_strength <= -self.min_negative_trend
            and momentum_20 <= 0.00015
            and momentum_5 <= 0.0005
            and z_score >= -0.1
            and vwap_distance <= 0.0008
            and session_position <= 0.78
        ):
            side = Side.SELL
        elif trend_strength > 0.0004 or momentum_20 > 0.00035 or z_score <= -1.0:
            side = Side.BUY
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.18,
            (trigger, 0.34),
            (max(-trend_strength, 0.0), 170),
            (max(z_score, 0.0), 0.14),
        )
        metadata = directional_metadata(
            side,
            short_entry=side == Side.SELL,
            short_exit=side == Side.BUY,
            failed_break_above_prior_day_high=failed_prior,
            failed_break_above_overnight_high=failed_overnight,
            reclaimed_prior_day_high=reclaimed_prior,
            reclaimed_overnight_high=reclaimed_overnight,
            trend_strength=trend_strength,
            z_score_20=z_score,
            vwap_distance=vwap_distance,
        )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, side, confidence if side != Side.FLAT else 0.0, metadata)


__all__ = [
    "US500TrendPullbackAgent",
    "US500VWAPContinuationAgent",
    "US500OpeningDriveReclaimAgent",
    "US500ShortTrendRejectionAgent",
    "US500OpeningDriveShortReclaimAgent",
    "US500MomentumImpulseAgent",
    "US500ShortVWAPRejectAgent",
    "US500FlatHighReversalAgent",
    "US500FlatTapeMeanReversionAgent",
    "US500OvernightGapFadeAgent",
    "US500FailedBreakdownReclaimAgent",
    "US500FailedUpsideRejectShortAgent",
]
