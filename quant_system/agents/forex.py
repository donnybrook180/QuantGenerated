from __future__ import annotations

from quant_system.agents.base import Agent
from quant_system.agents.common import RollingCloseState, RollingHighLowState, directional_metadata, scaled_confidence
from quant_system.models import FeatureVector, Side, SignalEvent


class ForexTrendContinuationAgent(Agent):
    name = "forex_trend_continuation"

    def __init__(
        self,
        lookback: int = 14,
        min_trend_strength: float = 0.00025,
        min_momentum_20: float = 0.0002,
        min_relative_volume: float = 0.75,
    ) -> None:
        self.closes = RollingCloseState(lookback)
        self.in_position = False
        self.entry_anchor: float | None = None
        self.min_trend_strength = min_trend_strength
        self.min_momentum_20 = min_momentum_20
        self.min_relative_volume = min_relative_volume

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        self.closes.append(close)
        if not self.closes.ready:
            return None

        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        session_vwap = feature.values.get("session_vwap", close)
        z_score_20 = feature.values.get("z_score_20", 0.0)

        local_mean = self.closes.mean()
        local_floor = self.closes.recent_low()

        if (
            not self.in_position
            and close > session_vwap
            and close > local_mean
            and trend_strength > self.min_trend_strength
            and momentum_20 > self.min_momentum_20
            and momentum_5 > -0.00015
            and -1.5 <= z_score_20 <= 0.25
            and relative_volume >= self.min_relative_volume
        ):
            self.in_position = True
            self.entry_anchor = local_floor
            confidence = scaled_confidence(0.25, (trend_strength, 600), (momentum_20, 500))
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                confidence,
                {"pullback_floor": local_floor},
            )

        if self.in_position and (
            trend_strength < -0.00012
            or momentum_20 < -0.0002
            or (self.entry_anchor is not None and close < self.entry_anchor)
        ):
            self.in_position = False
            self.entry_anchor = None
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.68, {"trend_flip": 1.0})

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class ForexShortTrendContinuationAgent(Agent):
    name = "forex_short_trend_continuation"

    def __init__(
        self,
        lookback: int = 14,
        min_negative_trend: float = -0.00025,
        min_negative_momentum_20: float = -0.0002,
        min_relative_volume: float = 0.75,
    ) -> None:
        self.closes = RollingCloseState(lookback)
        self.in_position = False
        self.entry_anchor: float | None = None
        self.min_negative_trend = min_negative_trend
        self.min_negative_momentum_20 = min_negative_momentum_20
        self.min_relative_volume = min_relative_volume

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        self.closes.append(close)
        if not self.closes.ready:
            return None

        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        session_vwap = feature.values.get("session_vwap", close)
        z_score_20 = feature.values.get("z_score_20", 0.0)

        local_mean = self.closes.mean()
        local_ceiling = self.closes.recent_high()

        if (
            not self.in_position
            and close < session_vwap
            and close < local_mean
            and trend_strength < self.min_negative_trend
            and momentum_20 < self.min_negative_momentum_20
            and momentum_5 < 0.00015
            and -0.25 <= z_score_20 <= 1.5
            and relative_volume >= self.min_relative_volume
        ):
            self.in_position = True
            self.entry_anchor = local_ceiling
            confidence = scaled_confidence(0.25, (abs(trend_strength), 600), (abs(momentum_20), 500))
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.SELL,
                confidence,
                directional_metadata(Side.SELL, short_entry=True, rebound_high=local_ceiling),
            )

        if self.in_position and (
            trend_strength > 0.00012
            or momentum_20 > 0.0002
            or (self.entry_anchor is not None and close > self.entry_anchor)
        ):
            self.in_position = False
            self.entry_anchor = None
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                0.68,
                directional_metadata(Side.BUY, short_exit=True, trend_flip=1.0),
            )

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class ForexRangeReversionAgent(Agent):
    name = "forex_range_reversion"

    def __init__(
        self,
        lookback: int = 20,
        min_z_score: float = -1.8,
        max_trend_strength: float = 0.00035,
    ) -> None:
        self.closes = RollingCloseState(lookback)
        self.in_position = False
        self.mean_level: float | None = None
        self.min_z_score = min_z_score
        self.max_trend_strength = max_trend_strength

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        self.closes.append(close)
        if not self.closes.ready:
            return None

        z_score_20 = feature.values.get("z_score_20", 0.0)
        trend_strength = abs(feature.values.get("trend_strength", 0.0))
        momentum_5 = feature.values.get("momentum_5", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        mean_level = self.closes.mean()

        if (
            not self.in_position
            and z_score_20 <= self.min_z_score
            and trend_strength <= self.max_trend_strength
            and momentum_5 > -0.0004
            and relative_volume >= 0.7
        ):
            self.in_position = True
            self.mean_level = mean_level
            confidence = min((abs(z_score_20) * 0.25) + 0.25, 1.0)
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                confidence,
                {"mean_level": mean_level},
            )

        if self.in_position and (
            (self.mean_level is not None and close >= self.mean_level)
            or momentum_5 < -0.0004
            or z_score_20 >= 0.5
        ):
            self.in_position = False
            self.mean_level = None
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.66, {"mean_reached": 1.0})

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class ForexBreakoutMomentumAgent(Agent):
    name = "forex_breakout_momentum"

    def __init__(
        self,
        lookback: int = 18,
        min_atr_proxy: float = 0.00035,
        min_momentum_5: float = 0.00025,
        min_momentum_20: float = 0.0003,
    ) -> None:
        self.range_state = RollingHighLowState(lookback)
        self.in_position = False
        self.entry_anchor: float | None = None
        self.min_atr_proxy = min_atr_proxy
        self.min_momentum_5 = min_momentum_5
        self.min_momentum_20 = min_momentum_20

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        high = feature.values.get("high", feature.values["close"])
        low = feature.values.get("low", feature.values["close"])
        close = feature.values["close"]
        self.range_state.append(high, low)
        if not self.range_state.ready:
            return None

        atr_proxy = feature.values.get("atr_proxy", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        breakout_high = self.range_state.breakout_high()
        breakout_low = self.range_state.breakout_low()

        if (
            not self.in_position
            and close > breakout_high
            and atr_proxy >= self.min_atr_proxy
            and momentum_5 > self.min_momentum_5
            and momentum_20 > self.min_momentum_20
            and relative_volume >= 0.8
        ):
            self.in_position = True
            self.entry_anchor = breakout_high
            confidence = scaled_confidence(0.25, (((close / breakout_high) - 1.0), 1800), (momentum_20, 600))
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                confidence,
                {"breakout_high": breakout_high},
            )

        if self.in_position and (
            close < breakout_low
            or momentum_20 < -0.0002
            or (self.entry_anchor is not None and close < self.entry_anchor * 0.9992)
        ):
            self.in_position = False
            self.entry_anchor = None
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.7, {"breakout_low": breakout_low})

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class ForexShortBreakdownMomentumAgent(Agent):
    name = "forex_short_breakdown_momentum"

    def __init__(
        self,
        lookback: int = 18,
        min_atr_proxy: float = 0.00035,
        min_momentum_5: float = -0.00025,
        min_momentum_20: float = -0.0003,
    ) -> None:
        self.range_state = RollingHighLowState(lookback)
        self.in_position = False
        self.entry_anchor: float | None = None
        self.min_atr_proxy = min_atr_proxy
        self.min_momentum_5 = min_momentum_5
        self.min_momentum_20 = min_momentum_20

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        high = feature.values.get("high", feature.values["close"])
        low = feature.values.get("low", feature.values["close"])
        close = feature.values["close"]
        self.range_state.append(high, low)
        if not self.range_state.ready:
            return None

        atr_proxy = feature.values.get("atr_proxy", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        breakout_low = self.range_state.breakout_low()
        rebound_high = self.range_state.recent_high()

        if (
            not self.in_position
            and close < breakout_low
            and atr_proxy >= self.min_atr_proxy
            and momentum_5 < self.min_momentum_5
            and momentum_20 < self.min_momentum_20
            and relative_volume >= 0.8
        ):
            self.in_position = True
            self.entry_anchor = rebound_high
            confidence = scaled_confidence(0.25, (((breakout_low / close) - 1.0), 1800), (abs(momentum_20), 600))
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.SELL,
                confidence,
                directional_metadata(Side.SELL, short_entry=True, breakout_low=breakout_low, rebound_high=rebound_high),
            )

        if self.in_position and (
            close > rebound_high
            or momentum_20 > 0.0002
            or (self.entry_anchor is not None and close > self.entry_anchor)
        ):
            self.in_position = False
            self.entry_anchor = None
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                0.7,
                directional_metadata(Side.BUY, short_exit=True, breakout_reversal=1.0),
            )

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


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
        close = feature.values["close"]
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


class ForexLondonRangeReentryAgent(Agent):
    name = "forex_london_range_reentry"

    def __init__(self, max_abs_trend_strength: float = 0.0011, min_relative_volume: float = 0.65) -> None:
        self.max_abs_trend_strength = max_abs_trend_strength
        self.min_relative_volume = min_relative_volume

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
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


__all__ = [
    "ForexTrendContinuationAgent",
    "ForexShortTrendContinuationAgent",
    "ForexRangeReversionAgent",
    "ForexBreakoutMomentumAgent",
    "ForexShortBreakdownMomentumAgent",
    "EURUSDLondonRangeReclaimAgent",
    "EURUSDLondonFalseBreakReversalAgent",
    "EURUSDNYOverlapContinuationAgent",
    "EURUSDPostNewsReclaimAgent",
    "GBPUSDLondonRangeFadeAgent",
    "GBPUSDLondonBreakoutReclaimAgent",
    "GBPUSDOverlapImpulseAgent",
    "GBPUSDPriorDaySweepReversalAgent",
    "ForexLondonRangeReentryAgent",
    "ForexOverlapRangeReentryAgent",
]
