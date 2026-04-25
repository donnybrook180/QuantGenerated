from __future__ import annotations

from collections import deque

from quant_system.agents.base import Agent
from quant_system.models import FeatureVector, Side, SignalEvent


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


class CryptoMomentumContinuationAgent(Agent):
    name = "crypto_momentum_continuation"

    def __init__(
        self,
        min_momentum_5: float = 0.00025,
        min_momentum_20: float = 0.00040,
        min_trend_strength: float = 0.00018,
        min_relative_volume: float = 0.60,
        min_atr_proxy: float = 0.0008,
    ) -> None:
        self.min_momentum_5 = min_momentum_5
        self.min_momentum_20 = min_momentum_20
        self.min_trend_strength = min_trend_strength
        self.min_relative_volume = min_relative_volume
        self.min_atr_proxy = min_atr_proxy

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)

        if relative_volume < self.min_relative_volume or atr_proxy < self.min_atr_proxy:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        if (
            momentum_5 >= self.min_momentum_5
            and momentum_20 >= self.min_momentum_20
            and trend_strength >= self.min_trend_strength
            and vwap_distance > -0.004
        ):
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                min((momentum_5 * 400) + (momentum_20 * 300) + (atr_proxy * 120) + 0.2, 1.0),
                {"vwap_distance": vwap_distance},
            )
        if (
            momentum_5 <= -self.min_momentum_5
            and momentum_20 <= -self.min_momentum_20
            and trend_strength <= -self.min_trend_strength
            and vwap_distance < 0.004
        ):
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.SELL,
                min((abs(momentum_5) * 400) + (abs(momentum_20) * 300) + (atr_proxy * 120) + 0.2, 1.0),
                {"position_intent": "short_entry", "vwap_distance": vwap_distance},
            )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class CryptoVWAPReversionAgent(Agent):
    name = "crypto_vwap_reversion"

    def __init__(
        self,
        z_score_entry: float = 1.8,
        min_relative_volume: float = 0.60,
        max_trend_strength: float = 0.00035,
        min_atr_proxy: float = 0.0008,
    ) -> None:
        self.z_score_entry = z_score_entry
        self.min_relative_volume = min_relative_volume
        self.max_trend_strength = max_trend_strength
        self.min_atr_proxy = min_atr_proxy

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        z_score = feature.values.get("z_score_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)

        if relative_volume < self.min_relative_volume or atr_proxy < self.min_atr_proxy or abs(trend_strength) > self.max_trend_strength:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        if z_score <= -self.z_score_entry and vwap_distance < -0.004 and momentum_5 > 0.0:
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                min((abs(z_score) * 0.22) + (abs(vwap_distance) * 40) + 0.15, 1.0),
                {"z_score_20": z_score, "vwap_distance": vwap_distance},
            )
        if z_score >= self.z_score_entry and vwap_distance > 0.004 and momentum_5 < 0.0:
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.SELL,
                min((abs(z_score) * 0.22) + (abs(vwap_distance) * 40) + 0.15, 1.0),
                {"position_intent": "short_entry", "z_score_20": z_score, "vwap_distance": vwap_distance},
            )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
