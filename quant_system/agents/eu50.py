from __future__ import annotations

from quant_system.agents.base import Agent
from quant_system.agents.common import SessionRangeState, scaled_confidence
from quant_system.models import FeatureVector, Side, SignalEvent


class EU50OpenReclaimLongAgent(Agent):
    name = "eu50_open_reclaim_long"

    def __init__(self) -> None:
        self.range_state = SessionRangeState()
        self.washout_seen = False
        self.in_position = False

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        high = feature.values.get("high", feature.values["close"])
        low = feature.values.get("low", feature.values["close"])
        close = feature.values["close"]
        relative_volume = feature.values.get("relative_volume", 1.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        minutes_from_open = feature.values.get("minutes_from_open", -1.0)

        if self.range_state.ensure_day(feature.timestamp):
            self.washout_seen = False
            self.in_position = False

        if in_regular_session >= 1.0 and 0 <= minutes_from_open < 30:
            self.range_state.update(high, low)
            return None

        if not self.range_state.ready:
            return None

        if in_regular_session < 1.0 or not (30 <= minutes_from_open <= 150):
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        range_span = max(self.range_state.range_high - self.range_state.range_low, close * 0.0006)
        washout_level = self.range_state.range_low - (range_span * 0.06)
        reclaim_level = self.range_state.range_low + (range_span * 0.10)
        fail_level = self.range_state.range_low - (range_span * 0.10)

        if low <= washout_level and z_score <= -1.0 and vwap_distance <= -0.00045:
            self.washout_seen = True

        if (
            not self.in_position
            and self.washout_seen
            and close >= reclaim_level
            and relative_volume >= 0.7
            and trend_strength > -0.0008
            and momentum_20 > -0.0006
            and momentum_5 > -0.00035
        ):
            self.in_position = True
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                scaled_confidence(
                    0.24,
                    (max(close - reclaim_level, 0.0), 140),
                    (max(-z_score - 1.0, 0.0), 0.12),
                    (max(-vwap_distance - 0.00045, 0.0), 250),
                ),
                {
                    "range_low": self.range_state.range_low,
                    "reclaim_level": reclaim_level,
                    "washout_seen": 1.0,
                },
            )

        if self.in_position and (
            close <= fail_level
            or trend_strength < -0.0011
            or momentum_20 < -0.0009
            or vwap_distance < -0.0009
        ):
            self.in_position = False
            self.washout_seen = False
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.66, {"failed_reclaim": 1.0})

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

