from __future__ import annotations

from quant_system.agents.base import Agent
from quant_system.agents.common import directional_metadata, scaled_confidence
from quant_system.models import FeatureVector, Side, SignalEvent


class GBPUSDLondonRangeFadeAgent(Agent):
    name = "gbpusd_london_range_fade"

    def __init__(
        self,
        max_abs_trend_strength: float = 0.00075,
        min_relative_volume: float = 0.68,
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
        morning_session = feature.values.get("morning_session", 0.0) > 0.0
        midday_session = feature.values.get("midday_session", 0.0) > 0.0
        in_regular_session = feature.values.get("in_regular_session", 0.0) > 0.0

        if not in_regular_session or (not morning_session and not midday_session) or relative_volume < self.min_relative_volume:
            side = Side.FLAT
        elif (
            abs(trend_strength) <= self.max_abs_trend_strength
            and abs(momentum_20) <= 0.00035
            and z_score >= 1.0
            and vwap_distance >= 0.00025
            and session_position >= 0.65
            and momentum_5 <= 0.0002
        ):
            side = Side.SELL
        elif (
            abs(trend_strength) <= self.max_abs_trend_strength
            and abs(momentum_20) <= 0.00035
            and z_score <= -1.0
            and vwap_distance <= -0.00025
            and session_position <= 0.35
            and momentum_5 >= -0.0002
        ):
            side = Side.BUY
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.18,
            (max(abs(z_score) - 1.0, 0.0), 0.3),
            (max(abs(vwap_distance) - 0.00025, 0.0), 200),
            (max(self.max_abs_trend_strength - abs(trend_strength), 0.0), 800),
        )
        metadata = directional_metadata(
            side,
            short_entry=side == Side.SELL,
            short_exit=side == Side.BUY,
            trend_strength=trend_strength,
            z_score_20=z_score,
            vwap_distance=vwap_distance,
            session_position=session_position,
        )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, side, confidence if side != Side.FLAT else 0.0, metadata)


class GBPUSDLondonBreakoutReclaimAgent(Agent):
    name = "gbpusd_london_breakout_reclaim"

    def __init__(
        self,
        min_trend_strength: float = 0.00022,
        min_relative_volume: float = 0.72,
    ) -> None:
        self.min_trend_strength = min_trend_strength
        self.min_relative_volume = min_relative_volume

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        prior_day_position = feature.values.get("prior_day_position", 0.5)
        overnight_position = feature.values.get("overnight_position", 0.5)
        relative_volume = feature.values.get("relative_volume", 1.0)
        morning_session = feature.values.get("morning_session", 0.0) > 0.0
        in_regular_session = feature.values.get("in_regular_session", 0.0) > 0.0

        if not in_regular_session or not morning_session or relative_volume < self.min_relative_volume:
            side = Side.FLAT
        elif (
            trend_strength >= self.min_trend_strength
            and momentum_20 > 0.00012
            and momentum_5 > -0.00008
            and vwap_distance >= -0.00005
            and prior_day_position >= 0.55
            and overnight_position >= 0.55
        ):
            side = Side.BUY
        elif (
            trend_strength <= -self.min_trend_strength
            and momentum_20 < -0.00012
            and momentum_5 < 0.00008
            and vwap_distance <= 0.00005
            and prior_day_position <= 0.45
            and overnight_position <= 0.45
        ):
            side = Side.SELL
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.20,
            (abs(trend_strength), 1100),
            (abs(momentum_20), 1500),
            (relative_volume - 1.0, 0.2),
        )
        metadata = directional_metadata(
            side,
            short_entry=side == Side.SELL,
            short_exit=side == Side.BUY,
            trend_strength=trend_strength,
            prior_day_position=prior_day_position,
            overnight_position=overnight_position,
            breakout_level=close,
        )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, side, confidence if side != Side.FLAT else 0.0, metadata)


class GBPUSDOverlapImpulseAgent(Agent):
    name = "gbpusd_overlap_impulse"

    def __init__(
        self,
        min_trend_strength: float = 0.00024,
        min_relative_volume: float = 0.78,
    ) -> None:
        self.min_trend_strength = min_trend_strength
        self.min_relative_volume = min_relative_volume

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        session_position = feature.values.get("session_position", 0.5)
        hour = int(feature.values.get("hour_of_day", 0.0))
        in_overlap = 12 <= hour <= 16

        if not in_overlap or relative_volume < self.min_relative_volume:
            side = Side.FLAT
        elif (
            trend_strength >= self.min_trend_strength
            and momentum_20 > 0.00018
            and momentum_5 > 0.0
            and -0.2 <= z_score <= 1.0
            and vwap_distance >= 0.0
            and session_position >= 0.52
        ):
            side = Side.BUY
        elif (
            trend_strength <= -self.min_trend_strength
            and momentum_20 < -0.00018
            and momentum_5 < 0.0
            and -1.0 <= z_score <= 0.2
            and vwap_distance <= 0.0
            and session_position <= 0.48
        ):
            side = Side.SELL
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.2,
            (abs(trend_strength), 1200),
            (abs(momentum_20), 1400),
            (abs(momentum_5), 800),
        )
        metadata = directional_metadata(
            side,
            short_entry=side == Side.SELL,
            short_exit=side == Side.BUY,
            trend_strength=trend_strength,
            momentum_20=momentum_20,
            vwap_distance=vwap_distance,
            session_position=session_position,
            hour_of_day=float(hour),
        )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, side, confidence if side != Side.FLAT else 0.0, metadata)


class GBPUSDPriorDaySweepReversalAgent(Agent):
    name = "gbpusd_prior_day_sweep_reversal"

    def __init__(
        self,
        max_abs_trend_strength: float = 0.0009,
        min_relative_volume: float = 0.7,
    ) -> None:
        self.max_abs_trend_strength = max_abs_trend_strength
        self.min_relative_volume = min_relative_volume

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        high = feature.values.get("high", close)
        low = feature.values.get("low", close)
        prior_day_high = feature.values.get("prior_day_high", 0.0)
        prior_day_low = feature.values.get("prior_day_low", 0.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        morning_session = feature.values.get("morning_session", 0.0) > 0.0
        midday_session = feature.values.get("midday_session", 0.0) > 0.0

        if (not morning_session and not midday_session) or relative_volume < self.min_relative_volume:
            side = Side.FLAT
        elif (
            prior_day_high > 0.0
            and high > prior_day_high
            and close < prior_day_high
            and abs(trend_strength) <= self.max_abs_trend_strength
            and vwap_distance <= 0.0001
            and z_score >= 0.5
        ):
            side = Side.SELL
        elif (
            prior_day_low > 0.0
            and low < prior_day_low
            and close > prior_day_low
            and abs(trend_strength) <= self.max_abs_trend_strength
            and vwap_distance >= -0.0001
            and z_score <= -0.5
        ):
            side = Side.BUY
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.18,
            (max(abs(z_score) - 0.5, 0.0), 0.28),
            (max(self.max_abs_trend_strength - abs(trend_strength), 0.0), 700),
            (relative_volume - 1.0, 0.2),
        )
        metadata = directional_metadata(
            side,
            short_entry=side == Side.SELL,
            short_exit=side == Side.BUY,
            prior_day_high=prior_day_high,
            prior_day_low=prior_day_low,
            z_score_20=z_score,
            vwap_distance=vwap_distance,
        )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, side, confidence if side != Side.FLAT else 0.0, metadata)
