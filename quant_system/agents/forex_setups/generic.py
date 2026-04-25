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


class ForexCarryTrendAgent(Agent):
    name = "forex_carry_trend"

    def __init__(
        self,
        lookback: int = 24,
        min_pair_macro_bias: float = 0.00018,
        min_carry_spread: float = 0.0,
        min_trend_strength: float = 0.00014,
        min_momentum_20: float = 0.00012,
        min_relative_volume: float = 0.62,
    ) -> None:
        self.closes = RollingCloseState(lookback)
        self.in_position = False
        self.entry_side = Side.FLAT
        self.entry_anchor: float | None = None
        self.min_pair_macro_bias = min_pair_macro_bias
        self.min_carry_spread = min_carry_spread
        self.min_trend_strength = min_trend_strength
        self.min_momentum_20 = min_momentum_20
        self.min_relative_volume = min_relative_volume

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        self.closes.append(close)
        if not self.closes.ready:
            return None

        symbol = feature.symbol.upper()
        usd_orientation = 1.0 if symbol.startswith("USD") else (-1.0 if symbol.endswith("USD") else 0.0)
        if (
            usd_orientation == 0.0
            or feature.values.get("cross_dxy_available", 0.0) <= 0.0
            or feature.values.get("cross_yield_available", 0.0) <= 0.0
        ):
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        session_vwap = feature.values.get("session_vwap", close)
        z_score_20 = feature.values.get("z_score_20", 0.0)
        cross_dxy_momentum_20 = feature.values.get("cross_dxy_momentum_20", 0.0)
        cross_yield_momentum_20 = feature.values.get("cross_yield_momentum_20", 0.0)
        broker_swap_available = feature.values.get("broker_swap_available", 0.0) > 0.0
        broker_swap_long = feature.values.get("broker_swap_long", 0.0)
        broker_swap_short = feature.values.get("broker_swap_short", 0.0)
        broker_preferred_carry_side = feature.values.get("broker_preferred_carry_side", 0.0)
        broker_carry_spread = feature.values.get("broker_carry_spread", 0.0)

        pair_macro_bias = usd_orientation * (cross_dxy_momentum_20 + (cross_yield_momentum_20 * 0.75))
        carry_long_ok = True
        carry_short_ok = True
        if broker_swap_available:
            carry_long_ok = (
                broker_preferred_carry_side >= 0.5
                and broker_swap_long > 0.0
                and broker_carry_spread >= self.min_carry_spread
            )
            carry_short_ok = (
                broker_preferred_carry_side <= -0.5
                and broker_swap_short > 0.0
                and (-broker_carry_spread) >= self.min_carry_spread
            )
        local_mean = self.closes.mean()
        local_floor = self.closes.recent_low()
        local_ceiling = self.closes.recent_high()

        if (
            not self.in_position
            and close > session_vwap
            and close > local_mean
            and carry_long_ok
            and pair_macro_bias >= self.min_pair_macro_bias
            and trend_strength >= self.min_trend_strength
            and momentum_20 >= self.min_momentum_20
            and momentum_5 > -0.00012
            and -1.25 <= z_score_20 <= 0.9
            and relative_volume >= self.min_relative_volume
        ):
            self.in_position = True
            self.entry_side = Side.BUY
            self.entry_anchor = local_floor
            confidence = scaled_confidence(0.24, (pair_macro_bias, 1400), (momentum_20, 700))
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                confidence,
                {
                    "pair_macro_bias": pair_macro_bias,
                    "cross_dxy_momentum_20": cross_dxy_momentum_20,
                    "cross_yield_momentum_20": cross_yield_momentum_20,
                    "broker_swap_long": broker_swap_long,
                    "broker_swap_short": broker_swap_short,
                    "broker_carry_spread": broker_carry_spread,
                },
            )

        if (
            not self.in_position
            and close < session_vwap
            and close < local_mean
            and carry_short_ok
            and pair_macro_bias <= -self.min_pair_macroBias
            and trend_strength <= -self.min_trend_strength
            and momentum_20 <= -self.min_momentum_20
            and momentum_5 < 0.00012
            and -0.9 <= z_score_20 <= 1.25
            and relative_volume >= self.min_relative_volume
        ):
            self.in_position = True
            self.entry_side = Side.SELL
            self.entry_anchor = local_ceiling
            confidence = scaled_confidence(0.24, (abs(pair_macro_bias), 1400), (abs(momentum_20), 700))
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.SELL,
                confidence,
                directional_metadata(
                    Side.SELL,
                    short_entry=True,
                    pair_macro_bias=pair_macro_bias,
                    cross_dxy_momentum_20=cross_dxy_momentum_20,
                    cross_yield_momentum_20=cross_yield_momentum_20,
                    broker_swap_long=broker_swap_long,
                    broker_swap_short=broker_swap_short,
                    broker_carry_spread=broker_carry_spread,
                ),
            )

        if self.in_position and self.entry_side == Side.BUY and (
            (broker_swap_available and not carry_long_ok)
            or pair_macro_bias < 0.0
            or trend_strength < -0.00008
            or momentum_20 < -0.0001
            or (self.entry_anchor is not None and close < self.entry_anchor)
        ):
            self.in_position = False
            self.entry_side = Side.FLAT
            self.entry_anchor = None
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.SELL,
                0.7,
                {"macro_flip": 1.0, "pair_macro_bias": pair_macro_bias},
            )

        if self.in_position and self.entry_side == Side.SELL and (
            (broker_swap_available and not carry_short_ok)
            or pair_macro_bias > 0.0
            or trend_strength > 0.00008
            or momentum_20 > 0.0001
            or (self.entry_anchor is not None and close > self.entry_anchor)
        ):
            self.in_position = False
            self.entry_side = Side.FLAT
            self.entry_anchor = None
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                0.7,
                directional_metadata(Side.BUY, short_exit=True, macro_flip=1.0, pair_macro_bias=pair_macro_bias),
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
