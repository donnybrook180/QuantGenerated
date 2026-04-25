from __future__ import annotations

from quant_system.agents.base import Agent
from quant_system.agents.common import scaled_confidence
from quant_system.models import FeatureVector, Side, SignalEvent


class XAUUSDVWAPReclaimAgent(Agent):
    name = "xauusd_vwap_reclaim"

    def __init__(self) -> None:
        self.in_position = False
        self.allowed_hours = {13, 14, 15, 16}

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        hour = int(feature.values.get("hour_of_day", 0))
        relative_volume = feature.values.get("relative_volume", 1.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        z_score_20 = feature.values.get("z_score_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        atr_proxy = feature.values.get("atr_proxy", 0.0)

        if hour not in self.allowed_hours:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        if (
            not self.in_position
            and atr_proxy > 0.0004
            and relative_volume >= 0.9
            and z_score_20 <= -0.75
            and vwap_distance <= -0.0005
            and trend_strength > -0.0006
            and momentum_20 > -0.0005
            and momentum_5 > -0.0003
        ):
            self.in_position = True
            confidence = scaled_confidence(
                0.28,
                (max(-z_score_20 - 0.75, 0.0), 0.18),
                (max(-vwap_distance - 0.0005, 0.0), 300),
            )
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                confidence,
                {"vwap_distance": vwap_distance, "z_score_20": z_score_20, "reclaim_setup": 1.0},
            )

        if self.in_position and (
            z_score_20 >= 0.1
            or vwap_distance >= -0.00005
            or trend_strength < -0.0008
            or momentum_20 < -0.0008
        ):
            self.in_position = False
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.68, {"mean_reverted": 1.0})

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class XAUUSDOpeningDriveReclaimAgent(Agent):
    name = "xauusd_opening_drive_reclaim"

    def __init__(self) -> None:
        self.in_position = False
        self.allowed_hours = {13, 14, 15, 16}

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        hour = int(feature.values.get("hour_of_day", 0))
        relative_volume = feature.values.get("relative_volume", 1.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        z_score_20 = feature.values.get("z_score_20", 0.0)
        drive_range_pct = feature.values.get("opening_drive_range_pct_1m", 0.0)
        distance_to_open_low = feature.values.get("distance_to_opening_drive_low_1m", 0.0)
        break_below = feature.values.get("opening_drive_break_below_1m", 0.0)
        vwap_distance_1m = feature.values.get("vwap_distance_1m", 0.0)

        if hour not in self.allowed_hours:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        if (
            not self.in_position
            and break_below > 0.0
            and drive_range_pct > 0.0008
            and distance_to_open_low >= -0.0004
            and relative_volume >= 0.85
            and z_score_20 <= -0.15
            and trend_strength > -0.0007
            and momentum_20 > -0.0006
            and momentum_5 > -0.0004
            and vwap_distance_1m >= -0.0012
        ):
            self.in_position = True
            confidence = scaled_confidence(
                0.24,
                (break_below, 0.25),
                (max(-z_score_20, 0.0), 0.16),
                (max(drive_range_pct - 0.0008, 0.0), 180),
            )
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                confidence,
                {
                    "opening_drive_break_below_1m": break_below,
                    "distance_to_opening_drive_low_1m": distance_to_open_low,
                    "opening_drive_range_pct_1m": drive_range_pct,
                    "vwap_distance_1m": vwap_distance_1m,
                },
            )

        if self.in_position and (
            z_score_20 >= 0.2
            or trend_strength < -0.0009
            or momentum_20 < -0.0008
            or vwap_distance_1m < -0.0015
        ):
            self.in_position = False
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.7, {"opening_drive_reclaim_exit": 1.0})

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class XAUUSDUSOpenRangeReclaimAgent(Agent):
    name = "xauusd_us_open_range_reclaim"

    def __init__(self) -> None:
        self.in_position = False
        self.allowed_hours = {13, 14, 15, 16}

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        hour = int(feature.values.get("hour_of_day", 0))
        relative_volume = feature.values.get("relative_volume", 1.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        us_high = feature.values.get("us_high", 0.0)
        us_low = feature.values.get("us_low", 0.0)
        reclaimed_high = feature.values.get("reclaimed_us_high", 0.0)
        reclaimed_low = feature.values.get("reclaimed_us_low", 0.0)
        broke_up = feature.values.get("broke_us_range_up", 0.0)
        broke_down = feature.values.get("broke_us_range_down", 0.0)
        reentered = feature.values.get("reentered_us_range", 0.0)

        if hour not in self.allowed_hours or relative_volume < 0.85:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        if (
            not self.in_position
            and us_low > 0.0
            and broke_down > 0.0
            and reclaimed_low > 0.0
            and reentered > 0.0
            and trend_strength > -0.0008
            and momentum_20 > -0.0007
            and momentum_5 > -0.0005
            and z_score <= -0.1
            and vwap_distance >= -0.0007
        ):
            self.in_position = True
            confidence = scaled_confidence(
                0.24,
                (reentered, 0.22),
                (relative_volume - 1.0, 0.2),
                (max(-z_score, 0.0), 0.16),
            )
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                confidence,
                {"us_high": us_high, "us_low": us_low, "reentered_us_range": reentered},
            )

        if self.in_position and (
            z_score >= 0.2
            or trend_strength < -0.0009
            or momentum_20 < -0.0008
            or vwap_distance < -0.001
            or (us_high > 0.0 and broke_up > 0.0 and reclaimed_high > 0.0)
        ):
            self.in_position = False
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.68, {"us_range_reclaim_exit": 1.0})

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
