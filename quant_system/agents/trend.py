from __future__ import annotations

from collections import deque

from quant_system.agents.base import Agent
from quant_system.models import FeatureVector, Side, SignalEvent


class TrendAgent(Agent):
    name = "trend"

    def __init__(self, fast_window: int, slow_window: int, min_trend_strength: float, min_relative_volume: float) -> None:
        self.fast_window = fast_window
        self.slow_window = slow_window
        self.min_trend_strength = min_trend_strength
        self.min_relative_volume = min_relative_volume
        self.fast_values: deque[float] = deque(maxlen=fast_window)
        self.slow_values: deque[float] = deque(maxlen=slow_window)

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        self.fast_values.append(close)
        self.slow_values.append(close)
        if len(self.fast_values) < self.fast_window or len(self.slow_values) < self.slow_window:
            return None

        fast = sum(self.fast_values) / len(self.fast_values)
        slow = sum(self.slow_values) / len(self.slow_values)
        delta = (fast / slow) - 1.0
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        opening_window = feature.values.get("opening_window", 0.0)
        closing_window = feature.values.get("closing_window", 0.0)
        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or closing_window > 0.0
            or relative_volume < self.min_relative_volume
            or abs(trend_strength) < self.min_trend_strength
            or (delta > 0 and momentum_20 <= 0)
            or (delta < 0 and momentum_20 >= 0)
        ):
            side = Side.FLAT
        else:
            side = Side.BUY if fast > slow else Side.SELL
        return SignalEvent(
            timestamp=feature.timestamp,
            agent_name=self.name,
            symbol=feature.symbol,
            side=side,
            confidence=min((abs(delta) + abs(momentum_20) + abs(trend_strength)) * 120, 1.0),
            metadata={"fast": fast, "slow": slow, "trend_strength": trend_strength},
        )


class MeanReversionAgent(Agent):
    name = "mean_reversion"

    def __init__(self, window: int, threshold: float) -> None:
        self.window = window
        self.threshold = threshold
        self.values: deque[float] = deque(maxlen=window)

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        self.values.append(close)
        if len(self.values) < self.window:
            return None
        mean = sum(self.values) / len(self.values)
        delta = (close / mean) - 1.0
        z_score = feature.values.get("z_score_20", 0.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        opening_window = feature.values.get("opening_window", 0.0)
        closing_window = feature.values.get("closing_window", 0.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or closing_window > 0.0
            or relative_volume < 0.9
            or abs(trend_strength) > self.threshold
        ):
            side = Side.FLAT
        elif delta <= -self.threshold and z_score <= -1.5:
            side = Side.BUY
        elif delta >= self.threshold and z_score >= 1.5:
            side = Side.SELL
        else:
            side = Side.FLAT
        return SignalEvent(
            timestamp=feature.timestamp,
            agent_name=self.name,
            symbol=feature.symbol,
            side=side,
            confidence=min((abs(delta) + abs(z_score) * 0.2) / max(self.threshold, 1e-6), 1.0),
            metadata={"mean": mean, "z_score_20": z_score},
        )


class MomentumConfirmationAgent(Agent):
    name = "momentum_confirmation"

    def __init__(self, threshold: float) -> None:
        self.threshold = threshold

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        if in_regular_session < 1.0 or relative_volume < 0.8:
            side = Side.FLAT
        elif momentum_5 > self.threshold and momentum_20 > 0 and trend_strength > 0:
            side = Side.BUY
        elif momentum_5 < -self.threshold and momentum_20 < 0 and trend_strength < 0:
            side = Side.SELL
        else:
            side = Side.FLAT
        confidence = min((abs(momentum_5) + abs(momentum_20) + abs(trend_strength)) * 150, 1.0)
        return SignalEvent(
            timestamp=feature.timestamp,
            agent_name=self.name,
            symbol=feature.symbol,
            side=side,
            confidence=confidence,
            metadata={"momentum_5": momentum_5, "momentum_20": momentum_20},
        )


class RiskSentinelAgent(Agent):
    name = "risk_sentinel"

    def __init__(self, max_volatility: float, min_relative_volume: float) -> None:
        self.max_volatility = max_volatility
        self.min_relative_volume = min_relative_volume

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        volatility = feature.values.get("volatility_14", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        if (
            volatility <= self.max_volatility
            and relative_volume >= self.min_relative_volume
        ):
            return None
        return SignalEvent(
            timestamp=feature.timestamp,
            agent_name=self.name,
            symbol=feature.symbol,
            side=Side.FLAT,
            confidence=1.0,
            metadata={
                "veto": "regime",
                "volatility_14": volatility,
                "relative_volume": relative_volume,
            },
        )
