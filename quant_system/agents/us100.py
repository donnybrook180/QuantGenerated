from __future__ import annotations

from quant_system.agents.base import Agent
from quant_system.models import FeatureVector, Side, SignalEvent


class TrendPullbackAgent(Agent):
    name = "trend_pullback"

    def __init__(self, min_trend_strength: float, pullback_z_limit: float = -0.35) -> None:
        self.min_trend_strength = min_trend_strength
        self.pullback_z_limit = pullback_z_limit

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        opening_window = feature.values.get("opening_window", 0.0)
        closing_window = feature.values.get("closing_window", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        hour = int(feature.values.get("hour_of_day", 0.0))

        # US100 behaves better as a long-only continuation profile on established intraday uptrends.
        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or closing_window > 0.0
            or not (14 <= hour <= 17)
            or relative_volume < 0.95
        ):
            side = Side.FLAT
        elif (
            trend_strength > max(self.min_trend_strength, 0.0006)
            and momentum_20 > 0.0005
            and -1.5 <= z_score <= self.pullback_z_limit
            and momentum_5 > -0.004
        ):
            side = Side.BUY
        elif trend_strength <= 0 or momentum_20 <= 0 or z_score >= 0.6:
            side = Side.SELL
        else:
            side = Side.FLAT

        confidence = min((abs(trend_strength) * 140) + (abs(momentum_20) * 80) + (max(0.0, -z_score) * 0.15), 1.0)
        return SignalEvent(
            timestamp=feature.timestamp,
            agent_name=self.name,
            symbol=feature.symbol,
            side=side,
            confidence=confidence,
            metadata={"trend_strength": trend_strength, "z_score_20": z_score, "hour_of_day": float(hour)},
        )


class OpeningDriveReclaimAgent(Agent):
    name = "opening_drive_reclaim"

    def __init__(self, min_trend_strength: float, reclaim_buffer: float = 0.0015) -> None:
        self.min_trend_strength = min_trend_strength
        self.reclaim_buffer = reclaim_buffer
        self.current_session: tuple[int, int, int] | None = None
        self.opening_high: float | None = None
        self.opening_low: float | None = None
        self.has_opening_pullback = False

    def _reset_session(self, feature: FeatureVector) -> None:
        timestamp = feature.timestamp
        self.current_session = (timestamp.year, timestamp.month, timestamp.day)
        self.opening_high = None
        self.opening_low = None
        self.has_opening_pullback = False

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        timestamp = feature.timestamp
        session_key = (timestamp.year, timestamp.month, timestamp.day)
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
        minutes_from_open = feature.values.get("minutes_from_open", -1.0)
        opening_window = feature.values.get("opening_window", 0.0)
        closing_window = feature.values.get("closing_window", 0.0)

        if in_regular_session < 1.0:
            return SignalEvent(
                timestamp=feature.timestamp,
                agent_name=self.name,
                symbol=feature.symbol,
                side=Side.FLAT,
                confidence=0.0,
            )

        if opening_window > 0.0:
            self.opening_high = high if self.opening_high is None else max(self.opening_high, high)
            self.opening_low = low if self.opening_low is None else min(self.opening_low, low)
            return SignalEvent(
                timestamp=feature.timestamp,
                agent_name=self.name,
                symbol=feature.symbol,
                side=Side.FLAT,
                confidence=0.0,
                metadata={"opening_high": self.opening_high or high, "opening_low": self.opening_low or low},
            )

        if self.opening_high is None or self.opening_low is None:
            return None

        opening_range = max(self.opening_high - self.opening_low, close * 0.0005)
        opening_mid = self.opening_low + (opening_range * 0.5)
        reclaim_level = opening_mid + (opening_range * 0.05)

        if close <= opening_mid:
            self.has_opening_pullback = True

        if (
            closing_window > 0.0
            or not (30.0 <= minutes_from_open <= 120.0)
            or relative_volume < 0.95
        ):
            side = Side.FLAT
        elif (
            self.has_opening_pullback
            and trend_strength > max(self.min_trend_strength, 0.0008)
            and momentum_20 > 0.0004
            and momentum_5 > 0.0
            and -1.0 <= z_score <= 0.45
            and close >= reclaim_level
        ):
            side = Side.BUY
        else:
            side = Side.FLAT

        confidence = min(
            0.2 + (max(trend_strength, 0.0) * 180) + (max(momentum_20, 0.0) * 120) + (max(momentum_5, 0.0) * 40),
            1.0,
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
                "reclaim_level": reclaim_level,
            },
        )


class TrendContinuationBreakoutAgent(Agent):
    name = "trend_continuation_breakout"

    def __init__(self, min_trend_strength: float, breakout_lookback: int = 6) -> None:
        self.min_trend_strength = min_trend_strength
        self.highs: list[float] = []
        self.breakout_lookback = breakout_lookback

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        high = feature.values.get("high", feature.values["close"])
        close = feature.values["close"]
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        opening_window = feature.values.get("opening_window", 0.0)
        closing_window = feature.values.get("closing_window", 0.0)
        hour = int(feature.values.get("hour_of_day", 0.0))

        self.highs.append(high)
        if len(self.highs) <= self.breakout_lookback:
            return None
        self.highs = self.highs[-self.breakout_lookback :]
        breakout_level = max(self.highs[:-1])

        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or closing_window > 0.0
            or not (16 <= hour <= 17)
            or relative_volume < 0.95
        ):
            side = Side.FLAT
        elif (
            trend_strength > max(self.min_trend_strength, 0.0015)
            and momentum_20 > 0.0009
            and momentum_5 > 0.0
            and -0.35 <= z_score <= 1.05
            and close > breakout_level
        ):
            side = Side.BUY
        elif trend_strength <= 0 or momentum_20 <= 0:
            side = Side.SELL
        else:
            side = Side.FLAT

        confidence = min((abs(trend_strength) * 160) + (abs(momentum_20) * 100) + (abs(momentum_5) * 80), 1.0)
        return SignalEvent(
            timestamp=feature.timestamp,
            agent_name=self.name,
            symbol=feature.symbol,
            side=side,
            confidence=confidence,
            metadata={"trend_strength": trend_strength, "breakout_level": breakout_level, "z_score_20": z_score, "hour_of_day": float(hour)},
        )


class PostPullbackContinuationAgent(Agent):
    name = "post_pullback_continuation"

    def __init__(self, min_trend_strength: float, pullback_lookback: int = 8) -> None:
        self.min_trend_strength = min_trend_strength
        self.pullback_lookback = pullback_lookback
        self.recent_highs: list[float] = []
        self.pullback_armed = False
        self.pullback_high: float | None = None

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        high = feature.values.get("high", close)
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        opening_window = feature.values.get("opening_window", 0.0)
        closing_window = feature.values.get("closing_window", 0.0)
        hour = int(feature.values.get("hour_of_day", 0.0))

        self.recent_highs.append(high)
        self.recent_highs = self.recent_highs[-self.pullback_lookback :]
        local_high = max(self.recent_highs) if self.recent_highs else high

        if trend_strength > max(self.min_trend_strength, 0.0009) and momentum_20 > 0.0006 and -1.8 <= z_score <= -0.2:
            self.pullback_armed = True
            self.pullback_high = local_high

        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or closing_window > 0.0
            or not (15 <= hour <= 18)
            or relative_volume < 0.85
        ):
            side = Side.FLAT
        elif (
            self.pullback_armed
            and self.pullback_high is not None
            and trend_strength > max(self.min_trend_strength, 0.0007)
            and momentum_20 > 0.0004
            and momentum_5 > -0.0002
            and -0.8 <= z_score <= 0.9
            and close >= self.pullback_high * 0.999
        ):
            side = Side.BUY
            self.pullback_armed = False
        elif trend_strength <= 0 or momentum_20 <= 0:
            side = Side.SELL
            self.pullback_armed = False
        else:
            side = Side.FLAT

        confidence = min(
            (max(trend_strength, 0.0) * 160) + (max(momentum_20, 0.0) * 120) + (max(momentum_5, 0.0) * 120) + 0.1,
            1.0,
        )
        return SignalEvent(
            timestamp=feature.timestamp,
            agent_name=self.name,
            symbol=feature.symbol,
            side=side,
            confidence=confidence if side != Side.FLAT else 0.0,
            metadata={
                "trend_strength": trend_strength,
                "pullback_high": self.pullback_high or local_high,
                "z_score_20": z_score,
                "hour_of_day": float(hour),
            },
        )


class VWAPReclaimContinuationAgent(Agent):
    name = "vwap_reclaim_continuation"

    def __init__(self, min_trend_strength: float) -> None:
        self.min_trend_strength = min_trend_strength
        self.pullback_seen = False
        self.reclaimed_vwap = False
        self.reference_low: float | None = None
        self.higher_low_confirmed = False

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        low = feature.values.get("low", close)
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        session_vwap = feature.values.get("session_vwap", close)
        session_position = feature.values.get("session_position", 0.5)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        opening_window = feature.values.get("opening_window", 0.0)
        closing_window = feature.values.get("closing_window", 0.0)
        hour = int(feature.values.get("hour_of_day", 0.0))

        if vwap_distance <= -0.0008 and trend_strength > max(self.min_trend_strength, 0.0008) and momentum_20 > 0:
            self.pullback_seen = True
            self.reclaimed_vwap = False
            self.higher_low_confirmed = False
            self.reference_low = low

        if self.pullback_seen and close >= session_vwap and momentum_5 > 0:
            self.reclaimed_vwap = True
        if self.pullback_seen and self.reference_low is not None and low > (self.reference_low * 1.0002):
            self.higher_low_confirmed = True

        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or closing_window > 0.0
            or not (16 <= hour <= 17)
            or relative_volume < 0.9
        ):
            side = Side.FLAT
        elif (
            self.pullback_seen
            and self.reclaimed_vwap
            and self.higher_low_confirmed
            and trend_strength > max(self.min_trend_strength, 0.0008)
            and momentum_20 > 0.0007
            and momentum_5 > 0.0002
            and -0.35 <= z_score <= 0.6
            and vwap_distance >= 0.0003
            and session_position >= 0.55
            and close >= session_vwap
        ):
            side = Side.BUY
            self.pullback_seen = False
            self.reclaimed_vwap = False
            self.higher_low_confirmed = False
            self.reference_low = None
        elif trend_strength <= 0 or momentum_20 <= 0:
            side = Side.SELL
            self.pullback_seen = False
            self.reclaimed_vwap = False
            self.higher_low_confirmed = False
            self.reference_low = None
        else:
            side = Side.FLAT

        confidence = min(
            (max(trend_strength, 0.0) * 160) + (max(momentum_20, 0.0) * 100) + (max(momentum_5, 0.0) * 100) + 0.1,
            1.0,
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


class LateSessionBreakoutAgent(Agent):
    name = "late_session_breakout"

    def __init__(self, min_trend_strength: float, lookback: int = 8) -> None:
        self.min_trend_strength = min_trend_strength
        self.highs: list[float] = []
        self.lookback = lookback

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        high = feature.values.get("high", feature.values["close"])
        close = feature.values["close"]
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        opening_window = feature.values.get("opening_window", 0.0)
        closing_window = feature.values.get("closing_window", 0.0)
        hour = int(feature.values.get("hour_of_day", 0.0))

        self.highs.append(high)
        if len(self.highs) <= self.lookback:
            return None
        self.highs = self.highs[-self.lookback :]
        breakout_level = max(self.highs[:-1])

        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or closing_window > 0.0
            or not (15 <= hour <= 18)
            or relative_volume < 1.0
        ):
            side = Side.FLAT
        elif (
            trend_strength > max(self.min_trend_strength, 0.0012)
            and momentum_20 > 0.001
            and momentum_5 > 0
            and -0.4 <= z_score <= 1.3
            and close > breakout_level
        ):
            side = Side.BUY
        elif trend_strength <= 0 or momentum_20 <= 0:
            side = Side.SELL
        else:
            side = Side.FLAT

        confidence = min((trend_strength * 180) + (momentum_20 * 120) + (momentum_5 * 80) + 0.2, 1.0) if side == Side.BUY else 0.6
        return SignalEvent(
            timestamp=feature.timestamp,
            agent_name=self.name,
            symbol=feature.symbol,
            side=side,
            confidence=confidence,
            metadata={"trend_strength": trend_strength, "breakout_level": breakout_level, "z_score_20": z_score, "hour_of_day": float(hour)},
        )
