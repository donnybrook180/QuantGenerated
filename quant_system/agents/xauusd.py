from __future__ import annotations

from collections import deque

from quant_system.agents.base import Agent
from quant_system.models import FeatureVector, Side, SignalEvent


class XAUUSDVolatilityBreakoutAgent(Agent):
    name = "volatility_breakout"

    def __init__(self, lookback: int = 12) -> None:
        self.highs: deque[float] = deque(maxlen=lookback)
        self.lows: deque[float] = deque(maxlen=lookback)
        self.breakout_side: Side = Side.FLAT
        self.entry_anchor: float | None = None
        self.allowed_hours = {13, 14, 16}

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        high = feature.values.get("high", feature.values["close"])
        low = feature.values.get("low", feature.values["close"])
        close = feature.values["close"]
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        hour = int(feature.values.get("hour_of_day", 0))
        trend_strength = feature.values.get("trend_strength", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        z_score_20 = feature.values.get("z_score_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)

        self.highs.append(high)
        self.lows.append(low)
        if len(self.highs) < self.highs.maxlen:
            return None

        breakout_high = max(list(self.highs)[:-1])
        breakout_low = min(list(self.lows)[:-1])

        if hour not in self.allowed_hours:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        if (
            self.breakout_side == Side.FLAT
            and close > breakout_high
            and atr_proxy > 0.0005
            and trend_strength > 0.0003
            and momentum_20 > 0.0
            and relative_volume >= 1.0
        ):
            self.breakout_side = Side.BUY
            self.entry_anchor = breakout_high
            confidence = min(((close / breakout_high) - 1.0) * 300 + abs(trend_strength) * 100 + 0.35, 1.0)
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.BUY, confidence, {"breakout_high": breakout_high})
        if (
            close < breakout_low
            and atr_proxy > 0.0005
            and trend_strength < -0.0003
            and momentum_20 < 0
            and relative_volume >= 1.0
        ):
            self.breakout_side = Side.FLAT
            self.entry_anchor = None
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.75, {"breakout_low": breakout_low})
        if self.breakout_side == Side.BUY and (
            (
                trend_strength < -0.00035
                and momentum_20 < -0.00015
            )
            or (
                self.entry_anchor is not None
                and close < self.entry_anchor * 0.9998
                and momentum_5 < -0.0005
            )
        ):
            self.breakout_side = Side.FLAT
            self.entry_anchor = None
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.SELL, 0.7, {"trend_flip": 1.0})
        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
