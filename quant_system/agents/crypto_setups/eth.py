from __future__ import annotations

from collections import deque

from quant_system.agents.base import Agent
from quant_system.models import FeatureVector, Side, SignalEvent


class EthOpeningDriveContinuationAgent(Agent):
    name = "eth_opening_drive_continuation"

    def __init__(
        self,
        lookback: int = 12,
        min_relative_volume: float = 0.55,
        min_atr_proxy: float = 0.0007,
        min_trend_strength: float = 0.00018,
        min_momentum_5: float = 0.00018,
        min_momentum_20: float = 0.00025,
    ) -> None:
        self.highs: deque[float] = deque(maxlen=lookback)
        self.lows: deque[float] = deque(maxlen=lookback)
        self.min_relative_volume = min_relative_volume
        self.min_atr_proxy = min_atr_proxy
        self.min_trend_strength = min_trend_strength
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

        relative_volume = feature.values.get("relative_volume", 1.0)
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        session_position = feature.values.get("session_position", 0.5)
        session_vwap = feature.values.get("session_vwap", close)

        if relative_volume < self.min_relative_volume or atr_proxy < self.min_atr_proxy:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        breakout_high = max(list(self.highs)[:-1])
        breakout_low = min(list(self.lows)[:-1])

        if (
            0.10 <= session_position <= 0.60
            and close > breakout_high * 1.0002
            and close >= session_vwap
            and trend_strength >= self.min_trend_strength
            and momentum_5 >= self.min_momentum_5
            and momentum_20 >= self.min_momentum_20
            and -0.001 <= vwap_distance <= 0.006
        ):
            confidence = min((trend_strength * 700) + (momentum_20 * 420) + (atr_proxy * 150) + 0.12, 1.0)
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                confidence,
                {"breakout_high": breakout_high, "session_drive": 1.0},
            )

        if (
            0.20 <= session_position <= 0.75
            and close < breakout_low * 0.9998
            and close <= session_vwap
            and trend_strength <= -self.min_trend_strength
            and momentum_5 <= -self.min_momentum_5
            and momentum_20 <= -self.min_momentum_20
            and -0.006 <= vwap_distance <= 0.001
        ):
            confidence = min((abs(trend_strength) * 700) + (abs(momentum_20) * 420) + (atr_proxy * 150) + 0.12, 1.0)
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.SELL,
                confidence,
                {"position_intent": "short_entry", "breakout_low": breakout_low, "session_drive": -1.0},
            )

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class EthCompressionBreakoutAgent(Agent):
    name = "eth_compression_breakout"

    def __init__(
        self,
        lookback: int = 10,
        max_range_width: float = 0.0045,
        min_relative_volume: float = 0.70,
        min_atr_proxy: float = 0.0006,
        min_momentum_5: float = 0.00012,
    ) -> None:
        self.highs: deque[float] = deque(maxlen=lookback)
        self.lows: deque[float] = deque(maxlen=lookback)
        self.max_range_width = max_range_width
        self.min_relative_volume = min_relative_volume
        self.min_atr_proxy = min_atr_proxy
        self.min_momentum_5 = min_momentum_5

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        high = feature.values.get("high", feature.values["close"])
        low = feature.values.get("low", feature.values["close"])
        close = feature.values["close"]
        self.highs.append(high)
        self.lows.append(low)
        if len(self.highs) < self.highs.maxlen:
            return None

        relative_volume = feature.values.get("relative_volume", 1.0)
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        session_position = feature.values.get("session_position", 0.5)

        if relative_volume < self.min_relative_volume or atr_proxy < self.min_atr_proxy:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        range_high = max(list(self.highs)[:-1])
        range_low = min(list(self.lows)[:-1])
        if range_high <= range_low:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
        range_width = (range_high - range_low) / close if close else 0.0
        if range_width > self.max_range_width:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        if (
            0.18 <= session_position <= 0.80
            and close > range_high * 1.00025
            and momentum_5 >= self.min_momentum_5
            and momentum_20 >= -0.0001
            and trend_strength >= -0.00005
            and -0.0015 <= vwap_distance <= 0.005
        ):
            confidence = min((range_width * 180) + (momentum_5 * 700) + (atr_proxy * 140) + 0.10, 1.0)
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                confidence,
                {"breakout_high": range_high, "compression_width": range_width},
            )

        if (
            0.18 <= session_position <= 0.80
            and close < range_low * 0.99975
            and momentum_5 <= -self.min_momentum_5
            and momentum_20 <= 0.0001
            and trend_strength <= 0.00005
            and -0.005 <= vwap_distance <= 0.0015
        ):
            confidence = min((range_width * 180) + (abs(momentum_5) * 700) + (atr_proxy * 140) + 0.10, 1.0)
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.SELL,
                confidence,
                {"position_intent": "short_entry", "breakout_low": range_low, "compression_width": range_width},
            )

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class EthSessionHandoffAgent(Agent):
    name = "eth_session_handoff"

    def __init__(
        self,
        lookback: int = 8,
        min_relative_volume: float = 0.85,
        min_atr_proxy: float = 0.0007,
        min_trend_strength: float = 0.00010,
        min_momentum_5: float = 0.00010,
    ) -> None:
        self.highs: deque[float] = deque(maxlen=lookback)
        self.lows: deque[float] = deque(maxlen=lookback)
        self.min_relative_volume = min_relative_volume
        self.min_atr_proxy = min_atr_proxy
        self.min_trend_strength = min_trend_strength
        self.min_momentum_5 = min_momentum_5

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        high = feature.values.get("high", feature.values["close"])
        low = feature.values.get("low", feature.values["close"])
        close = feature.values["close"]
        self.highs.append(high)
        self.lows.append(low)
        if len(self.highs) < self.highs.maxlen:
            return None

        hour = int(feature.values.get("hour_of_day", 0.0))
        minute = int(feature.timestamp.minute)
        relative_volume = feature.values.get("relative_volume", 1.0)
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        session_position = feature.values.get("session_position", 0.5)
        session_vwap = feature.values.get("session_vwap", close)

        if hour not in {12, 13, 14, 15, 16, 17, 18, 19} or minute not in {0, 15, 30, 45}:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
        if relative_volume < self.min_relative_volume or atr_proxy < self.min_atr_proxy:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        handoff_high = max(list(self.highs)[:-1])
        handoff_low = min(list(self.lows)[:-1])
        reclaim_long = close > handoff_high * 1.00015 and close >= session_vwap and -0.0008 <= vwap_distance <= 0.0035
        reclaim_short = close < handoff_low * 0.99985 and close <= session_vwap and -0.0035 <= vwap_distance <= 0.0008

        if (
            0.35 <= session_position <= 0.90
            and reclaim_long
            and trend_strength >= self.min_trend_strength
            and momentum_5 >= self.min_momentum_5
            and momentum_20 >= -0.00005
        ):
            confidence = min((trend_strength * 900) + (momentum_5 * 900) + (atr_proxy * 140) + 0.10, 1.0)
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                confidence,
                {"breakout_high": handoff_high, "session_handoff": 1.0},
            )

        if (
            0.10 <= session_position <= 0.65
            and reclaim_short
            and trend_strength <= -self.min_trend_strength
            and momentum_5 <= -self.min_momentum_5
            and momentum_20 <= 0.00005
        ):
            confidence = min((abs(trend_strength) * 900) + (abs(momentum_5) * 900) + (atr_proxy * 140) + 0.10, 1.0)
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.SELL,
                confidence,
                {"position_intent": "short_entry", "breakout_low": handoff_low, "session_handoff": -1.0},
            )

        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class EthRangeRotationAgent(Agent):
    name = "eth_range_rotation"

    def __init__(
        self,
        lookback: int = 24,
        z_score_entry: float = 1.2,
        min_relative_volume: float = 0.55,
        min_atr_proxy: float = 0.00055,
        max_trend_strength: float = 0.0009,
    ) -> None:
        self.highs: deque[float] = deque(maxlen=lookback)
        self.lows: deque[float] = deque(maxlen=lookback)
        self.z_score_entry = z_score_entry
        self.min_relative_volume = min_relative_volume
        self.min_atr_proxy = min_atr_proxy
        self.max_trend_strength = max_trend_strength

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        high = feature.values.get("high", feature.values["close"])
        low = feature.values.get("low", feature.values["close"])
        close = feature.values["close"]
        self.highs.append(high)
        self.lows.append(low)
        if len(self.highs) < self.highs.maxlen:
            return None

        z_score = feature.values.get("z_score_20", 0.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        session_position = feature.values.get("session_position", 0.5)

        if (
            relative_volume < self.min_relative_volume
            or atr_proxy < self.min_atr_proxy
            or abs(trend_strength) > self.max_trend_strength
        ):
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        range_high = max(self.highs)
        range_low = min(self.lows)
        if range_high <= range_low:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        range_width = (range_high - range_low) / close if close else 0.0
        near_low = close <= range_low * 1.0015
        near_high = close >= range_high * 0.9985

        if near_low and session_position <= 0.22 and z_score <= -self.z_score_entry and vwap_distance < -0.0025 and momentum_5 > -0.001:
            confidence = min((abs(z_score) * 0.18) + (range_width * 55) + 0.16, 1.0)
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                confidence,
                {"range_low": range_low, "range_high": range_high, "range_width": range_width},
            )

        if near_high and session_position >= 0.78 and z_score >= self.z_score_entry and vwap_distance > 0.0025 and momentum_5 < 0.001:
            confidence = min((abs(z_score) * 0.18) + (range_width * 55) + 0.16, 1.0)
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.SELL,
                confidence,
                {
                    "position_intent": "short_entry",
                    "range_low": range_low,
                    "range_high": range_high,
                    "range_width": range_width,
                },
            )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class EthLiquiditySweepReversalAgent(Agent):
    name = "eth_liquidity_sweep_reversal"

    def __init__(
        self,
        lookback: int = 18,
        sweep_margin: float = 0.0009,
        min_relative_volume: float = 0.60,
        min_atr_proxy: float = 0.0006,
        max_trend_strength: float = 0.0010,
    ) -> None:
        self.highs: deque[float] = deque(maxlen=lookback)
        self.lows: deque[float] = deque(maxlen=lookback)
        self.sweep_margin = sweep_margin
        self.min_relative_volume = min_relative_volume
        self.min_atr_proxy = min_atr_proxy
        self.max_trend_strength = max_trend_strength

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        high = feature.values.get("high", feature.values["close"])
        low = feature.values.get("low", feature.values["close"])
        close = feature.values["close"]
        self.highs.append(high)
        self.lows.append(low)
        if len(self.highs) < self.highs.maxlen:
            return None

        prior_high = max(list(self.highs)[:-1])
        prior_low = min(list(self.lows)[:-1])
        z_score = feature.values.get("z_score_20", 0.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        session_position = feature.values.get("session_position", 0.5)

        if (
            relative_volume < self.min_relative_volume
            or atr_proxy < self.min_atr_proxy
            or abs(trend_strength) > self.max_trend_strength
        ):
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        swept_low = low < prior_low * (1.0 - self.sweep_margin)
        swept_high = high > prior_high * (1.0 + self.sweep_margin)

        if (
            swept_low
            and close > prior_low * 1.0006
            and session_position <= 0.35
            and z_score < -0.9
            and -0.0015 <= vwap_distance <= 0.001
            and momentum_5 > 0.0
        ):
            confidence = min((abs(z_score) * 0.2) + (atr_proxy * 130) + 0.15, 1.0)
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                confidence,
                {"sweep_low": prior_low, "sweep_reclaim": 1.0},
            )

        if (
            swept_high
            and close < prior_high * 0.9994
            and session_position >= 0.65
            and z_score > 0.9
            and -0.001 <= vwap_distance <= 0.0015
            and momentum_5 < 0.0
        ):
            confidence = min((abs(z_score) * 0.2) + (atr_proxy * 130) + 0.15, 1.0)
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.SELL,
                confidence,
                {"position_intent": "short_entry", "sweep_high": prior_high, "sweep_reject": 1.0},
            )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
