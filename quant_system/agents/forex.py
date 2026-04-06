from __future__ import annotations

from collections import deque

from quant_system.agents.base import Agent
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
        self.closes: deque[float] = deque(maxlen=lookback)
        self.in_position = False
        self.entry_anchor: float | None = None
        self.min_trend_strength = min_trend_strength
        self.min_momentum_20 = min_momentum_20
        self.min_relative_volume = min_relative_volume

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        self.closes.append(close)
        if len(self.closes) < self.closes.maxlen:
            return None

        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        session_vwap = feature.values.get("session_vwap", close)
        z_score_20 = feature.values.get("z_score_20", 0.0)

        local_mean = sum(self.closes) / len(self.closes)
        local_floor = min(list(self.closes)[-5:])

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
            confidence = min((trend_strength * 600) + (momentum_20 * 500) + 0.25, 1.0)
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


class ForexRangeReversionAgent(Agent):
    name = "forex_range_reversion"

    def __init__(
        self,
        lookback: int = 20,
        min_z_score: float = -1.8,
        max_trend_strength: float = 0.00035,
    ) -> None:
        self.closes: deque[float] = deque(maxlen=lookback)
        self.in_position = False
        self.mean_level: float | None = None
        self.min_z_score = min_z_score
        self.max_trend_strength = max_trend_strength

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        self.closes.append(close)
        if len(self.closes) < self.closes.maxlen:
            return None

        z_score_20 = feature.values.get("z_score_20", 0.0)
        trend_strength = abs(feature.values.get("trend_strength", 0.0))
        momentum_5 = feature.values.get("momentum_5", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        mean_level = sum(self.closes) / len(self.closes)

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
        self.highs: deque[float] = deque(maxlen=lookback)
        self.lows: deque[float] = deque(maxlen=lookback)
        self.in_position = False
        self.entry_anchor: float | None = None
        self.min_atr_proxy = min_atr_proxy
        self.min_momentum_5 = min_momentum_5
        self.min_momentum_20 = min_momentum_20

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        high = feature.values.get("high", feature.values["close"])
        low = feature.values.get("low", feature.values["close"])
        close = feature.values["close"]
        self.highs.append(high)
        self.lows.append(low)
        if len(self.highs) < self.highs.maxlen:
            return None

        atr_proxy = feature.values.get("atr_proxy", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        breakout_high = max(list(self.highs)[:-1])
        breakout_low = min(list(self.lows)[:-1])

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
            confidence = min(((close / breakout_high) - 1.0) * 1800 + (momentum_20 * 600) + 0.25, 1.0)
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
