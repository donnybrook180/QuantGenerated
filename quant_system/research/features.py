from __future__ import annotations

from collections import deque
from datetime import date
import math

from quant_system.integrations.polygon_events import DailyEventFlags
from quant_system.models import FeatureVector, MarketBar


def build_feature_library(bars: list[MarketBar], daily_event_flags: dict[date, DailyEventFlags] | None = None) -> list[FeatureVector]:
    closes = [bar.close for bar in bars]
    volumes = [bar.volume for bar in bars]
    features: list[FeatureVector] = []
    regular_open = 13 * 60 + 30
    regular_close = 20 * 60
    cumulative_session_pv = 0.0
    cumulative_session_volume = 0.0
    session_high = 0.0
    session_low = 0.0
    current_session_key: tuple[int, int, int] | None = None

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
        in_regular_session = 1.0 if regular_open <= session_minutes < regular_close else 0.0
        minutes_from_open = float(session_minutes - regular_open) if in_regular_session else -1.0
        opening_window = 1.0 if in_regular_session and 0 <= minutes_from_open < 30 else 0.0
        closing_window = 1.0 if in_regular_session and (regular_close - session_minutes) <= 30 else 0.0
        session_key = (bar.timestamp.year, bar.timestamp.month, bar.timestamp.day)

        if session_key != current_session_key:
            current_session_key = session_key
            cumulative_session_pv = 0.0
            cumulative_session_volume = 0.0
            session_high = bar.high
            session_low = bar.low

        if in_regular_session:
            typical_price = (bar.high + bar.low + bar.close) / 3.0
            cumulative_session_pv += typical_price * max(bar.volume, 1.0)
            cumulative_session_volume += max(bar.volume, 1.0)
            session_high = max(session_high, bar.high)
            session_low = min(session_low, bar.low)

        session_vwap = (cumulative_session_pv / cumulative_session_volume) if cumulative_session_volume > 0 else bar.close
        vwap_distance = ((bar.close / session_vwap) - 1.0) if session_vwap else 0.0
        session_range = max(session_high - session_low, bar.close * 0.0005)
        session_position = ((bar.close - session_low) / session_range) if session_range else 0.5
        event_flags = (daily_event_flags or {}).get(bar.timestamp.date(), DailyEventFlags())
        features.append(
            FeatureVector(
                timestamp=bar.timestamp,
                symbol=bar.symbol,
                values={
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volatility_14": volatility,
                    "momentum_5": momentum,
                    "momentum_20": momentum_20,
                    "trend_strength": trend_strength,
                    "z_score_20": z_score,
                    "atr_proxy": (bar.high - bar.low) / bar.close if bar.close else 0.0,
                    "hour_of_day": float(bar.timestamp.hour),
                    "minute_of_hour": float(bar.timestamp.minute),
                    "relative_volume": (bar.volume / volume_mean) if volume_mean else 1.0,
                    "in_regular_session": in_regular_session,
                    "minutes_from_open": minutes_from_open,
                    "opening_window": opening_window,
                    "closing_window": closing_window,
                    "session_vwap": session_vwap,
                    "vwap_distance": vwap_distance,
                    "session_high": session_high,
                    "session_low": session_low,
                    "session_position": session_position,
                    "news_count_1d": float(event_flags.news_count),
                    "high_impact_news_count_1d": float(event_flags.high_impact_count),
                    "earnings_news_count_1d": float(event_flags.earnings_like_count),
                    "high_impact_event_day": 1.0 if event_flags.high_impact_count > 0 else 0.0,
                    "earnings_event_day": 1.0 if event_flags.earnings_like_count > 0 else 0.0,
                    "event_blackout": 1.0 if event_flags.event_blackout else 0.0,
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
