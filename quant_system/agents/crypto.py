from __future__ import annotations

from collections import deque

from quant_system.agents.base import Agent
from quant_system.models import FeatureVector, Side, SignalEvent


class CryptoTrendPullbackAgent(Agent):
    name = "crypto_trend_pullback"

    def __init__(
        self,
        lookback: int = 12,
        min_trend_strength: float = 0.0009,
        min_momentum_20: float = 0.001,
        z_score_low: float = -1.8,
        z_score_high: float = -0.2,
        min_relative_volume: float = 0.85,
        min_atr_proxy: float = 0.002,
    ) -> None:
        self.closes: deque[float] = deque(maxlen=lookback)
        self.in_position = False
        self.entry_anchor: float | None = None
        self.min_trend_strength = min_trend_strength
        self.min_momentum_20 = min_momentum_20
        self.z_score_low = z_score_low
        self.z_score_high = z_score_high
        self.min_relative_volume = min_relative_volume
        self.min_atr_proxy = min_atr_proxy

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        self.closes.append(close)
        if len(self.closes) < self.closes.maxlen:
            return None

        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score_20 = feature.values.get("z_score_20", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        session_vwap = feature.values.get("session_vwap", close)

        pullback_floor = min(list(self.closes)[-4:])
        local_mean = sum(self.closes) / len(self.closes)

        if (
            not self.in_position
            and close > session_vwap
            and close > local_mean
            and trend_strength > self.min_trend_strength
            and momentum_20 > self.min_momentum_20
            and self.z_score_low <= z_score_20 <= self.z_score_high
            and momentum_5 > -0.002
            and relative_volume >= self.min_relative_volume
            and atr_proxy >= self.min_atr_proxy
        ):
            self.in_position = True
            self.entry_anchor = pullback_floor
            confidence = min((trend_strength * 220) + (momentum_20 * 140) + 0.3, 1.0)
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                confidence,
                {"pullback_floor": pullback_floor},
            )

        if self.in_position and (
            trend_strength < -0.0004
            or momentum_20 < -0.001
            or (self.entry_anchor is not None and close < self.entry_anchor)
        ):
            self.in_position = False
            self.entry_anchor = None
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.72, {"trend_flip": 1.0})

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class CryptoBreakoutReclaimAgent(Agent):
    name = "crypto_breakout_reclaim"

    def __init__(
        self,
        lookback: int = 20,
        reclaim_buffer: float = 0.998,
        min_trend_strength: float = 0.0007,
        min_momentum_20: float = 0.0008,
        min_relative_volume: float = 0.9,
        min_atr_proxy: float = 0.002,
    ) -> None:
        self.highs: deque[float] = deque(maxlen=lookback)
        self.lows: deque[float] = deque(maxlen=lookback)
        self.armed = False
        self.reclaim_level: float | None = None
        self.in_position = False
        self.reclaim_buffer = reclaim_buffer
        self.min_trend_strength = min_trend_strength
        self.min_momentum_20 = min_momentum_20
        self.min_relative_volume = min_relative_volume
        self.min_atr_proxy = min_atr_proxy

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        high = feature.values.get("high", feature.values["close"])
        low = feature.values.get("low", feature.values["close"])
        close = feature.values["close"]
        self.highs.append(high)
        self.lows.append(low)
        if len(self.highs) < self.highs.maxlen:
            return None

        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)

        breakout_high = max(list(self.highs)[:-1])
        reclaim_band = breakout_high * self.reclaim_buffer

        if (
            not self.armed
            and close < breakout_high
            and close > reclaim_band
            and trend_strength > self.min_trend_strength
            and momentum_20 > self.min_momentum_20
            and relative_volume >= self.min_relative_volume
        ):
            self.armed = True
            self.reclaim_level = breakout_high

        if (
            not self.in_position
            and self.armed
            and self.reclaim_level is not None
            and close > self.reclaim_level
            and momentum_5 > 0.0006
            and atr_proxy >= self.min_atr_proxy
            and vwap_distance > -0.002
        ):
            self.in_position = True
            self.armed = False
            confidence = min(((close / self.reclaim_level) - 1.0) * 180 + (momentum_20 * 120) + 0.35, 1.0)
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                confidence,
                {"breakout_high": self.reclaim_level},
            )

        if self.in_position and (
            trend_strength < -0.0004
            or momentum_20 < -0.0008
            or (self.reclaim_level is not None and close < self.reclaim_level * 0.9975)
        ):
            self.in_position = False
            self.reclaim_level = None
            self.armed = False
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.7, {"failed_reclaim": 1.0})

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class CryptoVolatilityExpansionAgent(Agent):
    name = "crypto_volatility_expansion"

    def __init__(
        self,
        lookback: int = 18,
        min_atr_proxy: float = 0.003,
        min_trend_strength: float = 0.0006,
        min_momentum_5: float = 0.001,
        min_momentum_20: float = 0.0015,
        min_relative_volume: float = 1.0,
    ) -> None:
        self.highs: deque[float] = deque(maxlen=lookback)
        self.lows: deque[float] = deque(maxlen=lookback)
        self.in_position = False
        self.entry_anchor: float | None = None
        self.min_atr_proxy = min_atr_proxy
        self.min_trend_strength = min_trend_strength
        self.min_momentum_5 = min_momentum_5
        self.min_momentum_20 = min_momentum_20
        self.min_relative_volume = min_relative_volume

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        high = feature.values.get("high", feature.values["close"])
        low = feature.values.get("low", feature.values["close"])
        close = feature.values["close"]
        self.highs.append(high)
        self.lows.append(low)
        if len(self.highs) < self.highs.maxlen:
            return None

        atr_proxy = feature.values.get("atr_proxy", 0.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)

        breakout_high = max(list(self.highs)[:-1])
        breakout_low = min(list(self.lows)[:-1])

        if (
            not self.in_position
            and close > breakout_high
            and atr_proxy >= self.min_atr_proxy
            and trend_strength > self.min_trend_strength
            and momentum_5 > self.min_momentum_5
            and momentum_20 > self.min_momentum_20
            and relative_volume >= self.min_relative_volume
        ):
            self.in_position = True
            self.entry_anchor = breakout_high
            confidence = min(((close / breakout_high) - 1.0) * 160 + (atr_proxy * 40) + 0.3, 1.0)
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
            or momentum_20 < -0.001
            or (self.entry_anchor is not None and close < self.entry_anchor * 0.998)
        ):
            self.in_position = False
            self.entry_anchor = None
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.74, {"breakout_low": breakout_low})

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class CryptoShortBreakdownAgent(Agent):
    name = "crypto_short_breakdown"

    def __init__(
        self,
        lookback: int = 18,
        min_atr_proxy: float = 0.0025,
        min_negative_trend: float = -0.0006,
        min_negative_momentum_5: float = -0.0008,
        min_negative_momentum_20: float = -0.0012,
        min_relative_volume: float = 0.9,
    ) -> None:
        self.lows: deque[float] = deque(maxlen=lookback)
        self.highs: deque[float] = deque(maxlen=lookback)
        self.armed = False
        self.breakdown_level: float | None = None
        self.min_atr_proxy = min_atr_proxy
        self.min_negative_trend = min_negative_trend
        self.min_negative_momentum_5 = min_negative_momentum_5
        self.min_negative_momentum_20 = min_negative_momentum_20
        self.min_relative_volume = min_relative_volume

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        low = feature.values.get("low", feature.values["close"])
        high = feature.values.get("high", feature.values["close"])
        close = feature.values["close"]
        self.lows.append(low)
        self.highs.append(high)
        if len(self.lows) < self.lows.maxlen:
            return None

        breakdown_low = min(list(self.lows)[:-1])
        rebound_high = max(list(self.highs)[-4:])
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)

        if (
            not self.armed
            and close < breakdown_low
            and atr_proxy >= self.min_atr_proxy
            and trend_strength <= self.min_negative_trend
            and momentum_5 <= self.min_negative_momentum_5
            and momentum_20 <= self.min_negative_momentum_20
            and relative_volume >= self.min_relative_volume
        ):
            self.armed = True
            self.breakdown_level = breakdown_low
            confidence = min(((breakdown_low / close) - 1.0) * 160 + (atr_proxy * 50) + 0.3, 1.0)
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.SELL,
                confidence,
                {
                    "position_intent": "short_entry",
                    "breakout_low": breakdown_low,
                    "rebound_high": rebound_high,
                    "short_breakdown_low": breakdown_low,
                    "short_rebound_high": rebound_high,
                },
            )

        if self.armed and self.breakdown_level is not None and (
            close > rebound_high
            or trend_strength > 0.0002
            or momentum_20 > 0.0004
        ):
            self.armed = False
            self.breakdown_level = None
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                0.7,
                {"position_intent": "short_exit", "short_exit": 1.0},
            )

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class CryptoShortReversionAgent(Agent):
    name = "crypto_short_reversion"

    def __init__(
        self,
        lookback: int = 14,
        min_negative_trend: float = -0.0005,
        z_score_low: float = 0.9,
        z_score_high: float = 2.8,
        min_relative_volume: float = 0.8,
        min_atr_proxy: float = 0.0018,
    ) -> None:
        self.closes: deque[float] = deque(maxlen=lookback)
        self.armed = False
        self.reversion_anchor: float | None = None
        self.min_negative_trend = min_negative_trend
        self.z_score_low = z_score_low
        self.z_score_high = z_score_high
        self.min_relative_volume = min_relative_volume
        self.min_atr_proxy = min_atr_proxy

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        self.closes.append(close)
        if len(self.closes) < self.closes.maxlen:
            return None

        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score_20 = feature.values.get("z_score_20", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        session_vwap = feature.values.get("session_vwap", close)

        local_ceiling = max(list(self.closes)[-5:])
        local_mean = sum(self.closes) / len(self.closes)

        if (
            not self.armed
            and close < session_vwap
            and close < local_mean
            and trend_strength <= self.min_negative_trend
            and self.z_score_low <= z_score_20 <= self.z_score_high
            and momentum_5 < 0.002
            and momentum_20 <= -0.0008
            and relative_volume >= self.min_relative_volume
            and atr_proxy >= self.min_atr_proxy
        ):
            self.armed = True
            self.reversion_anchor = local_ceiling
            confidence = min((abs(trend_strength) * 220) + (abs(momentum_20) * 120) + 0.25, 1.0)
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.SELL,
                confidence,
                {
                    "position_intent": "short_entry",
                    "rebound_high": local_ceiling,
                    "short_reversion_anchor": local_ceiling,
                },
            )

        if self.armed and (
            trend_strength > 0.0002
            or momentum_20 > 0.0005
            or (self.reversion_anchor is not None and close > self.reversion_anchor)
        ):
            self.armed = False
            self.reversion_anchor = None
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                0.68,
                {"position_intent": "short_exit", "short_reversion_exit": 1.0},
            )

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
