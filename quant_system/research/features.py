from __future__ import annotations

from collections import deque
import math

from quant_system.models import FeatureVector, MarketBar


def build_feature_library(bars: list[MarketBar]) -> list[FeatureVector]:
    closes = [bar.close for bar in bars]
    volumes = [bar.volume for bar in bars]
    features: list[FeatureVector] = []

    for index, bar in enumerate(bars):
        lookback = closes[max(0, index - 14) : index + 1]
        mean_price = sum(lookback) / len(lookback)
        variance = sum((value - mean_price) ** 2 for value in lookback) / len(lookback)
        volatility = math.sqrt(variance) / mean_price if mean_price else 0.0
        momentum = (bar.close / closes[index - 5] - 1.0) if index >= 5 else 0.0
        momentum_20 = (bar.close / closes[index - 20] - 1.0) if index >= 20 else 0.0
        fast_mean = sum(closes[max(0, index - 9) : index + 1]) / min(index + 1, 10)
        slow_mean = sum(closes[max(0, index - 29) : index + 1]) / min(index + 1, 30)
        trend_strength = (fast_mean / slow_mean) - 1.0 if slow_mean else 0.0
        z_window = closes[max(0, index - 19) : index + 1]
        z_mean = sum(z_window) / len(z_window)
        z_var = sum((value - z_mean) ** 2 for value in z_window) / len(z_window)
        z_std = math.sqrt(z_var)
        z_score = ((bar.close - z_mean) / z_std) if z_std else 0.0
        volume_mean = sum(volumes[max(0, index - 10) : index + 1]) / min(index + 1, 11)
        session_minutes = (bar.timestamp.hour * 60) + bar.timestamp.minute
        # Approximate US regular session in UTC for DST months, matching the current trading setup.
        regular_open = 13 * 60 + 30
        regular_close = 20 * 60
        in_regular_session = 1.0 if regular_open <= session_minutes < regular_close else 0.0
        minutes_from_open = float(session_minutes - regular_open) if in_regular_session else -1.0
        opening_window = 1.0 if in_regular_session and 0 <= minutes_from_open < 30 else 0.0
        closing_window = 1.0 if in_regular_session and (regular_close - session_minutes) <= 30 else 0.0
        features.append(
            FeatureVector(
                timestamp=bar.timestamp,
                symbol=bar.symbol,
                values={
                    "close": bar.close,
                    "volatility_14": volatility,
                    "momentum_5": momentum,
                    "momentum_20": momentum_20,
                    "trend_strength": trend_strength,
                    "z_score_20": z_score,
                    "hour_of_day": float(bar.timestamp.hour),
                    "relative_volume": (bar.volume / volume_mean) if volume_mean else 1.0,
                    "in_regular_session": in_regular_session,
                    "minutes_from_open": minutes_from_open,
                    "opening_window": opening_window,
                    "closing_window": closing_window,
                },
            )
        )
    return features


class RollingWindow:
    def __init__(self, size: int) -> None:
        self.size = size
        self.values: deque[float] = deque(maxlen=size)

    def update(self, value: float) -> float:
        self.values.append(value)
        return self.mean

    @property
    def mean(self) -> float:
        return sum(self.values) / len(self.values) if self.values else 0.0
