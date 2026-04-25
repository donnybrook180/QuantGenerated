from __future__ import annotations

from quant_system.agents.base import Agent
from quant_system.agents.common import directional_metadata, scaled_confidence
from quant_system.models import FeatureVector, Side, SignalEvent


class ForexLondonRangeReentryAgent(Agent):
    name = "forex_london_range_reentry"

    def __init__(self, max_abs_trend_strength: float = 0.0011, min_relative_volume: float = 0.65) -> None:
        self.max_abs_trend_strength = max_abs_trend_strength
        self.min_relative_volume = min_relative_volume

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        trend_strength = feature.values.get("trend_strength", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        z_score = feature.values.get("z_score_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        hour = int(feature.values.get("hour_of_day", 0.0))
        london_high = feature.values.get("london_high", 0.0)
        london_low = feature.values.get("london_low", 0.0)
        reclaimed_high = feature.values.get("reclaimed_london_high", 0.0)
        reclaimed_low = feature.values.get("reclaimed_london_low", 0.0)
        broke_up = feature.values.get("broke_london_range_up", 0.0)
        broke_down = feature.values.get("broke_london_range_down", 0.0)
        reentered = feature.values.get("reentered_london_range", 0.0)

        if hour < 8 or hour > 16 or relative_volume < self.min_relative_volume:
            side = Side.FLAT
        elif (
            london_low > 0.0
            and broke_down > 0.0
            and reclaimed_low > 0.0
            and reentered > 0.0
            and abs(trend_strength) <= self.max_abs_trend_strength
            and z_score <= -0.15
            and vwap_distance >= -0.0004
        ):
            side = Side.BUY
        elif (
            london_high > 0.0
            and broke_up > 0.0
            and reclaimed_high > 0.0
            and reentered > 0.0
            and abs(trend_strength) <= self.max_abs_trend_strength
            and z_score >= 0.15
            and vwap_distance <= 0.0004
        ):
            side = Side.SELL
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.18,
            (reentered, 0.18),
            (max(self.max_abs_trend_strength - abs(trend_strength), 0.0), 800),
            (max(abs(z_score) - 0.15, 0.0), 0.24),
        )
        metadata = directional_metadata(
            side,
            short_entry=side == Side.SELL,
            short_exit=side == Side.BUY,
            london_high=london_high,
            london_low=london_low,
            z_score_20=z_score,
            vwap_distance=vwap_distance,
        )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, side, confidence if side != Side.FLAT else 0.0, metadata)


class ForexOverlapRangeReentryAgent(Agent):
    name = "forex_overlap_range_reentry"

    def __init__(self, min_relative_volume: float = 0.68, min_trend_strength: float = 0.0001) -> None:
        self.min_relative_volume = min_relative_volume
        self.min_trend_strength = min_trend_strength

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        z_score = feature.values.get("z_score_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        hour = int(feature.values.get("hour_of_day", 0.0))
        overlap_high = feature.values.get("overlap_high", 0.0)
        overlap_low = feature.values.get("overlap_low", 0.0)
        reclaimed_high = feature.values.get("reclaimed_overlap_high", 0.0)
        reclaimed_low = feature.values.get("reclaimed_overlap_low", 0.0)
        broke_up = feature.values.get("broke_overlap_range_up", 0.0)
        broke_down = feature.values.get("broke_overlap_range_down", 0.0)
        reentered = feature.values.get("reentered_overlap_range", 0.0)

        if hour < 12 or hour > 16 or relative_volume < self.min_relative_volume:
            side = Side.FLAT
        elif (
            overlap_low > 0.0
            and broke_down > 0.0
            and reclaimed_low > 0.0
            and reentered > 0.0
            and trend_strength >= -self.min_trend_strength
            and momentum_20 >= -0.0002
            and z_score <= -0.1
            and vwap_distance >= -0.0005
        ):
            side = Side.BUY
        elif (
            overlap_high > 0.0
            and broke_up > 0.0
            and reclaimed_high > 0.0
            and reentered > 0.0
            and trend_strength <= self.min_trend_strength
            and momentum_20 <= 0.0002
            and z_score >= 0.1
            and vwap_distance <= 0.0005
        ):
            side = Side.SELL
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.18,
            (reentered, 0.18),
            (relative_volume - 1.0, 0.2),
            (max(abs(z_score) - 0.1, 0.0), 0.22),
        )
        metadata = directional_metadata(
            side,
            short_entry=side == Side.SELL,
            short_exit=side == Side.BUY,
            overlap_high=overlap_high,
            overlap_low=overlap_low,
            z_score_20=z_score,
            vwap_distance=vwap_distance,
        )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, side, confidence if side != Side.FLAT else 0.0, metadata)
