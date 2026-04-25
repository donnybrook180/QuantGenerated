from __future__ import annotations

from quant_system.agents.base import Agent
from quant_system.agents.common import directional_metadata, scaled_confidence
from quant_system.models import FeatureVector, Side, SignalEvent


class EURUSDLondonRangeReclaimAgent(Agent):
    name = "eurusd_london_range_reclaim"

    def __init__(
        self,
        max_abs_trend_strength: float = 0.0007,
        min_distance_to_vwap: float = 0.00018,
        min_relative_volume: float = 0.65,
    ) -> None:
        self.in_position = False
        self.entry_side = Side.FLAT
        self.max_abs_trend_strength = max_abs_trend_strength
        self.min_distance_to_vwap = min_distance_to_vwap
        self.min_relative_volume = min_relative_volume

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        trend_strength = abs(feature.values.get("trend_strength", 0.0))
        relative_volume = feature.values.get("relative_volume", 1.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        session_position = feature.values.get("session_position", 0.5)
        prior_day_position = feature.values.get("prior_day_position", 0.5)
        in_regular_session = feature.values.get("in_regular_session", 0.0) > 0.0
        morning_session = feature.values.get("morning_session", 0.0) > 0.0
        midday_session = feature.values.get("midday_session", 0.0) > 0.0

        if not self.in_position and in_regular_session and (morning_session or midday_session):
            if (
                trend_strength <= self.max_abs_trend_strength
                and relative_volume >= self.min_relative_volume
                and vwap_distance <= -self.min_distance_to_vwap
                and session_position <= 0.30
                and prior_day_position <= 0.45
            ):
                self.in_position = True
                self.entry_side = Side.BUY
                confidence = scaled_confidence(0.28, (abs(vwap_distance), 1800), ((0.5 - session_position), 0.8))
                return SignalEvent(
                    feature.timestamp,
                    self.name,
                    feature.symbol,
                    Side.BUY,
                    confidence,
                    {"setup": "range_reclaim_long", "reclaim_level": close},
                )
            if (
                trend_strength <= self.max_abs_trend_strength
                and relative_volume >= self.min_relative_volume
                and vwap_distance >= self.min_distance_to_vwap
                and session_position >= 0.70
                and prior_day_position >= 0.55
            ):
                self.in_position = True
                self.entry_side = Side.SELL
                confidence = scaled_confidence(0.28, (abs(vwap_distance), 1800), ((session_position - 0.5), 0.8))
                return SignalEvent(
                    feature.timestamp,
                    self.name,
                    feature.symbol,
                    Side.SELL,
                    confidence,
                    directional_metadata(Side.SELL, short_entry=True, setup="range_reclaim_short", reclaim_level=close),
                )

        if self.in_position:
            if self.entry_side == Side.BUY and (vwap_distance >= 0.00005 or session_position >= 0.62 or trend_strength < -0.00035):
                self.in_position = False
                self.entry_side = Side.FLAT
                return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.66, {"mean_reclaim_exit": 1.0})
            if self.entry_side == Side.SELL and (vwap_distance <= -0.00005 or session_position <= 0.38 or trend_strength > 0.00035):
                self.in_position = False
                self.entry_side = Side.FLAT
                return SignalEvent(
                    feature.timestamp,
                    self.name,
                    feature.symbol,
                    Side.BUY,
                    0.66,
                    directional_metadata(Side.BUY, short_exit=True, mean_reclaim_exit=1.0),
                )

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class EURUSDLondonFalseBreakReversalAgent(Agent):
    name = "eurusd_london_false_break_reversal"

    def __init__(
        self,
        breakout_margin: float = 0.00018,
        reclaim_margin: float = 0.00004,
        max_abs_trend_strength: float = 0.0009,
    ) -> None:
        self.in_position = False
        self.entry_side = Side.FLAT
        self.breakout_margin = breakout_margin
        self.reclaim_margin = reclaim_margin
        self.max_abs_trend_strength = max_abs_trend_strength

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        high = feature.values.get("high", close)
        low = feature.values.get("low", close)
        prior_day_high = feature.values.get("prior_day_high", 0.0)
        prior_day_low = feature.values.get("prior_day_low", 0.0)
        overnight_high = feature.values.get("overnight_high", 0.0)
        overnight_low = feature.values.get("overnight_low", 0.0)
        trend_strength = abs(feature.values.get("trend_strength", 0.0))
        relative_volume = feature.values.get("relative_volume", 1.0)
        morning_session = feature.values.get("morning_session", 0.0) > 0.0
        midday_session = feature.values.get("midday_session", 0.0) > 0.0
        session_vwap = feature.values.get("session_vwap", close)

        upper_level = max(prior_day_high, overnight_high)
        lower_level = min(value for value in (prior_day_low, overnight_low) if value > 0.0) if (prior_day_low > 0.0 or overnight_low > 0.0) else 0.0

        if not self.in_position and (morning_session or midday_session) and trend_strength <= self.max_abs_trend_strength and relative_volume >= 0.7:
            if upper_level > 0.0 and high > upper_level * (1.0 + self.breakout_margin) and close < upper_level * (1.0 - self.reclaim_margin) and close < session_vwap:
                self.in_position = True
                self.entry_side = Side.SELL
                confidence = scaled_confidence(0.30, (((high / upper_level) - 1.0), 1500), (((session_vwap / close) - 1.0), 1000))
                return SignalEvent(
                    feature.timestamp,
                    self.name,
                    feature.symbol,
                    Side.SELL,
                    confidence,
                    directional_metadata(Side.SELL, short_entry=True, setup="false_break_short", failed_level=upper_level),
                )
            if lower_level > 0.0 and low < lower_level * (1.0 - self.breakout_margin) and close > lower_level * (1.0 + self.reclaim_margin) and close > session_vwap:
                self.in_position = True
                self.entry_side = Side.BUY
                confidence = scaled_confidence(0.30, (((lower_level / low) - 1.0), 1500), (((close / session_vwap) - 1.0), 1000))
                return SignalEvent(
                    feature.timestamp,
                    self.name,
                    feature.symbol,
                    Side.BUY,
                    confidence,
                    {"setup": "false_break_long", "failed_level": lower_level},
                )

        if self.in_position:
            session_position = feature.values.get("session_position", 0.5)
            if self.entry_side == Side.SELL and (session_position <= 0.42 or close > session_vwap):
                self.in_position = False
                self.entry_side = Side.FLAT
                return SignalEvent(
                    feature.timestamp,
                    self.name,
                    feature.symbol,
                    Side.BUY,
                    0.68,
                    directional_metadata(Side.BUY, short_exit=True, false_break_exit=1.0),
                )
            if self.entry_side == Side.BUY and (session_position >= 0.58 or close < session_vwap):
                self.in_position = False
                self.entry_side = Side.FLAT
                return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.68, {"false_break_exit": 1.0})

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class EURUSDNYOverlapContinuationAgent(Agent):
    name = "eurusd_ny_overlap_continuation"

    def __init__(
        self,
        min_trend_strength: float = 0.00022,
        min_momentum_20: float = 0.00018,
        min_relative_volume: float = 0.75,
    ) -> None:
        self.in_position = False
        self.entry_side = Side.FLAT
        self.min_trend_strength = min_trend_strength
        self.min_momentum_20 = min_momentum_20
        self.min_relative_volume = min_relative_volume

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        prior_day_position = feature.values.get("prior_day_position", 0.5)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        hour = int(feature.values.get("hour_of_day", 0.0))
        in_overlap = 13 <= hour <= 16

        if not self.in_position and in_overlap and relative_volume >= self.min_relative_volume:
            if (
                trend_strength >= self.min_trend_strength
                and momentum_20 >= self.min_momentum_20
                and momentum_5 > -0.00008
                and prior_day_position >= 0.60
                and vwap_distance >= -0.00005
            ):
                self.in_position = True
                self.entry_side = Side.BUY
                confidence = scaled_confidence(0.28, (trend_strength, 1200), (momentum_20, 1500))
                return SignalEvent(
                    feature.timestamp,
                    self.name,
                    feature.symbol,
                    Side.BUY,
                    confidence,
                    {"setup": "ny_overlap_trend_long", "trend_strength": trend_strength},
                )
            if (
                trend_strength <= -self.min_trend_strength
                and momentum_20 <= -self.min_momentum_20
                and momentum_5 < 0.00008
                and prior_day_position <= 0.40
                and vwap_distance <= 0.00005
            ):
                self.in_position = True
                self.entry_side = Side.SELL
                confidence = scaled_confidence(0.28, (abs(trend_strength), 1200), (abs(momentum_20), 1500))
                return SignalEvent(
                    feature.timestamp,
                    self.name,
                    feature.symbol,
                    Side.SELL,
                    confidence,
                    directional_metadata(Side.SELL, short_entry=True, setup="ny_overlap_trend_short", trend_strength=trend_strength),
                )

        if self.in_position:
            if self.entry_side == Side.BUY and (trend_strength < 0.00005 or momentum_20 < -0.00008 or vwap_distance < -0.00012):
                self.in_position = False
                self.entry_side = Side.FLAT
                return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.69, {"trend_exit": 1.0})
            if self.entry_side == Side.SELL and (trend_strength > -0.00005 or momentum_20 > 0.00008 or vwap_distance > 0.00012):
                self.in_position = False
                self.entry_side = Side.FLAT
                return SignalEvent(
                    feature.timestamp,
                    self.name,
                    feature.symbol,
                    Side.BUY,
                    0.69,
                    directional_metadata(Side.BUY, short_exit=True, trend_exit=1.0),
                )

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class EURUSDPostNewsReclaimAgent(Agent):
    name = "eurusd_post_news_reclaim"

    def __init__(
        self,
        min_relative_volume: float = 0.8,
        max_abs_trend_strength: float = 0.0012,
        reclaim_margin: float = 0.00005,
    ) -> None:
        self.in_position = False
        self.entry_side = Side.FLAT
        self.min_relative_volume = min_relative_volume
        self.max_abs_trend_strength = max_abs_trend_strength
        self.reclaim_margin = reclaim_margin

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        session_vwap = feature.values.get("session_vwap", close)
        trend_strength = feature.values.get("trend_strength", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        high_impact_event_day = feature.values.get("high_impact_event_day", 0.0) > 0.0
        event_blackout = feature.values.get("event_blackout", 0.0) > 0.0
        opening_gap_pct = feature.values.get("opening_gap_pct", 0.0)
        prior_day_position = feature.values.get("prior_day_position", 0.5)
        hour = int(feature.values.get("hour_of_day", 0.0))
        post_news_window = 9 <= hour <= 15

        if not self.in_position and high_impact_event_day and not event_blackout and post_news_window and relative_volume >= self.min_relative_volume:
            if (
                abs(trend_strength) <= self.max_abs_trend_strength
                and opening_gap_pct <= 0.0015
                and close > session_vwap * (1.0 + self.reclaim_margin)
                and prior_day_position >= 0.52
            ):
                self.in_position = True
                self.entry_side = Side.BUY
                confidence = scaled_confidence(0.26, (((close / session_vwap) - 1.0), 2200), (relative_volume - 1.0, 0.35))
                return SignalEvent(
                    feature.timestamp,
                    self.name,
                    feature.symbol,
                    Side.BUY,
                    confidence,
                    {"setup": "post_news_vwap_reclaim_long"},
                )
            if (
                abs(trend_strength) <= self.max_abs_trend_strength
                and opening_gap_pct >= -0.0015
                and close < session_vwap * (1.0 - self.reclaim_margin)
                and prior_day_position <= 0.48
            ):
                self.in_position = True
                self.entry_side = Side.SELL
                confidence = scaled_confidence(0.26, (((session_vwap / close) - 1.0), 2200), (relative_volume - 1.0, 0.35))
                return SignalEvent(
                    feature.timestamp,
                    self.name,
                    feature.symbol,
                    Side.SELL,
                    confidence,
                    directional_metadata(Side.SELL, short_entry=True, setup="post_news_vwap_reclaim_short"),
                )

        if self.in_position:
            if self.entry_side == Side.BUY and (close < session_vwap or prior_day_position >= 0.72):
                self.in_position = False
                self.entry_side = Side.FLAT
                return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.67, {"post_news_exit": 1.0})
            if self.entry_side == Side.SELL and (close > session_vwap or prior_day_position <= 0.28):
                self.in_position = False
                self.entry_side = Side.FLAT
                return SignalEvent(
                    feature.timestamp,
                    self.name,
                    feature.symbol,
                    Side.BUY,
                    0.67,
                    directional_metadata(Side.BUY, short_exit=True, post_news_exit=1.0),
                )

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
