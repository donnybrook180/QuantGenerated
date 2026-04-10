from __future__ import annotations

from collections import deque
from datetime import date
import math

from quant_system.integrations.polygon_events import DailyEventFlags
from quant_system.models import FeatureVector, MarketBar
from quant_system.symbols import is_crypto_symbol, is_forex_symbol, is_index_symbol, is_metal_symbol


def _regular_session_bounds(symbol: str) -> tuple[int, int]:
    upper = symbol.upper()
    if upper in {"GER40", "DAX", "DE40", "SX5E", "EU50", "EU50.CASH", "ESTX50"}:
        return 8 * 60, 16 * 60 + 30
    if upper in {"JP225", "JP225.CASH", "JPN225", "NK225"}:
        return 0, 6 * 60
    if upper in {"HK50", "HK50.CASH", "HSI50", "HANGSENG"}:
        return 1 * 60 + 30, 8 * 60
    if upper in {"US500", "SPY", "SPX", "I:SPX", "US100", "NAS100", "QQQ", "NDX", "I:NDX", "US30", "DJ30", "DOW30", "DIA", "DJI", "I:DJI"}:
        return 13 * 60 + 30, 20 * 60
    return 13 * 60 + 30, 20 * 60


def build_feature_library(bars: list[MarketBar], daily_event_flags: dict[date, DailyEventFlags] | None = None) -> list[FeatureVector]:
    closes = [bar.close for bar in bars]
    volumes = [bar.volume for bar in bars]
    features: list[FeatureVector] = []
    symbol = bars[0].symbol if bars else ""
    is_twenty_four_hour_asset = is_crypto_symbol(symbol) or is_forex_symbol(symbol) or is_metal_symbol(symbol)
    if is_twenty_four_hour_asset:
        regular_open = 0
        regular_close = 24 * 60
    elif is_index_symbol(symbol):
        regular_open, regular_close = _regular_session_bounds(symbol)
    else:
        regular_open, regular_close = 13 * 60 + 30, 20 * 60
    cumulative_session_pv = 0.0
    cumulative_session_volume = 0.0
    session_high = 0.0
    session_low = 0.0
    current_session_key: tuple[int, int, int] | None = None
    previous_regular_high = 0.0
    previous_regular_low = 0.0
    previous_regular_close = 0.0
    current_regular_high = 0.0
    current_regular_low = 0.0
    current_regular_close = 0.0
    current_regular_open = 0.0
    current_overnight_high = 0.0
    current_overnight_low = 0.0
    current_overnight_open = 0.0
    current_opening_drive_high = 0.0
    current_opening_drive_low = 0.0
    current_opening_drive_close = 0.0
    saw_opening_drive_bar_today = False
    saw_regular_bar_today = False
    saw_overnight_bar_today = False
    session_reference_labels: tuple[str, ...] = ()
    if is_forex_symbol(symbol) or is_metal_symbol(symbol):
        session_reference_labels = ("london", "us", "overlap")
    session_reference_windows = {
        "london": (8 * 60, 13 * 60),
        "us": (13 * 60, 17 * 60),
        "overlap": (13 * 60, 16 * 60),
    }
    session_reference_state: dict[str, dict[str, float | bool]] = {
        label: {"open": 0.0, "high": 0.0, "low": 0.0, "ready": False}
        for label in session_reference_labels
    }

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
            if current_session_key is not None and saw_regular_bar_today:
                previous_regular_high = current_regular_high
                previous_regular_low = current_regular_low
                previous_regular_close = current_regular_close
            current_session_key = session_key
            cumulative_session_pv = 0.0
            cumulative_session_volume = 0.0
            session_high = bar.high
            session_low = bar.low
            current_regular_high = 0.0
            current_regular_low = 0.0
            current_regular_close = 0.0
            current_regular_open = 0.0
            current_overnight_high = 0.0
            current_overnight_low = 0.0
            current_overnight_open = 0.0
            current_opening_drive_high = 0.0
            current_opening_drive_low = 0.0
            current_opening_drive_close = 0.0
            saw_opening_drive_bar_today = False
            saw_regular_bar_today = False
            saw_overnight_bar_today = False
            session_reference_state = {
                label: {"open": 0.0, "high": 0.0, "low": 0.0, "ready": False}
                for label in session_reference_labels
            }

        if not is_twenty_four_hour_asset and session_minutes < regular_open:
            if not saw_overnight_bar_today:
                current_overnight_open = bar.open
                current_overnight_high = bar.high
                current_overnight_low = bar.low
                saw_overnight_bar_today = True
            else:
                current_overnight_high = max(current_overnight_high, bar.high)
                current_overnight_low = min(current_overnight_low, bar.low)

        if in_regular_session:
            typical_price = (bar.high + bar.low + bar.close) / 3.0
            cumulative_session_pv += typical_price * max(bar.volume, 1.0)
            cumulative_session_volume += max(bar.volume, 1.0)
            session_high = max(session_high, bar.high)
            session_low = min(session_low, bar.low)
            if not saw_regular_bar_today:
                current_regular_open = bar.open
                current_regular_high = bar.high
                current_regular_low = bar.low
                saw_regular_bar_today = True
            else:
                current_regular_high = max(current_regular_high, bar.high)
                current_regular_low = min(current_regular_low, bar.low)
            current_regular_close = bar.close
            if 0 <= minutes_from_open < 30:
                if not saw_opening_drive_bar_today:
                    current_opening_drive_high = bar.high
                    current_opening_drive_low = bar.low
                    current_opening_drive_close = bar.close
                    saw_opening_drive_bar_today = True
                else:
                    current_opening_drive_high = max(current_opening_drive_high, bar.high)
                    current_opening_drive_low = min(current_opening_drive_low, bar.low)
                    current_opening_drive_close = bar.close

        for label in session_reference_labels:
            window_open, window_close = session_reference_windows[label]
            state = session_reference_state[label]
            if window_open <= session_minutes < window_close:
                if not state["ready"]:
                    state["open"] = bar.open
                    state["high"] = bar.high
                    state["low"] = bar.low
                    state["ready"] = True
                else:
                    state["high"] = max(float(state["high"]), bar.high)
                    state["low"] = min(float(state["low"]), bar.low)

        session_vwap = (cumulative_session_pv / cumulative_session_volume) if cumulative_session_volume > 0 else bar.close
        vwap_distance = ((bar.close / session_vwap) - 1.0) if session_vwap else 0.0
        session_range = max(session_high - session_low, bar.close * 0.0005)
        session_position = ((bar.close - session_low) / session_range) if session_range else 0.5
        prior_day_range = max(previous_regular_high - previous_regular_low, bar.close * 0.0005) if previous_regular_close else 0.0
        overnight_range = max(current_overnight_high - current_overnight_low, bar.close * 0.0005) if saw_overnight_bar_today else 0.0
        opening_gap_pct = (
            ((current_regular_open / previous_regular_close) - 1.0)
            if previous_regular_close and current_regular_open
            else 0.0
        )
        distance_to_prior_day_high = ((bar.close / previous_regular_high) - 1.0) if previous_regular_high else 0.0
        distance_to_prior_day_low = ((bar.close / previous_regular_low) - 1.0) if previous_regular_low else 0.0
        distance_to_prior_day_close = ((bar.close / previous_regular_close) - 1.0) if previous_regular_close else 0.0
        distance_to_overnight_high = ((bar.close / current_overnight_high) - 1.0) if current_overnight_high else 0.0
        distance_to_overnight_low = ((bar.close / current_overnight_low) - 1.0) if current_overnight_low else 0.0
        prior_day_position = (
            ((bar.close - previous_regular_low) / prior_day_range)
            if prior_day_range > 0.0 and previous_regular_close
            else 0.5
        )
        overnight_position = (
            ((bar.close - current_overnight_low) / overnight_range)
            if overnight_range > 0.0 and saw_overnight_bar_today
            else 0.5
        )
        premarket_high = current_overnight_high if not is_twenty_four_hour_asset else 0.0
        premarket_low = current_overnight_low if not is_twenty_four_hour_asset else 0.0
        premarket_open = current_overnight_open if not is_twenty_four_hour_asset else 0.0
        premarket_range = max(premarket_high - premarket_low, bar.close * 0.0005) if premarket_high and premarket_low else 0.0
        distance_to_premarket_high = ((bar.close / premarket_high) - 1.0) if premarket_high else 0.0
        distance_to_premarket_low = ((bar.close / premarket_low) - 1.0) if premarket_low else 0.0
        reclaimed_premarket_high = 1.0 if premarket_high and bar.low <= premarket_high <= bar.close else 0.0
        reclaimed_premarket_low = 1.0 if premarket_low and bar.high >= premarket_low >= bar.close else 0.0
        broke_premarket_high = 1.0 if premarket_high and bar.close > premarket_high else 0.0
        broke_premarket_low = 1.0 if premarket_low and bar.close < premarket_low else 0.0
        opening_drive_high = current_opening_drive_high if saw_opening_drive_bar_today else 0.0
        opening_drive_low = current_opening_drive_low if saw_opening_drive_bar_today else 0.0
        opening_drive_range = (
            max(opening_drive_high - opening_drive_low, bar.close * 0.0005)
            if opening_drive_high and opening_drive_low
            else 0.0
        )
        opening_drive_return_pct = (
            ((current_opening_drive_close / current_regular_open) - 1.0)
            if saw_opening_drive_bar_today and current_regular_open
            else 0.0
        )
        distance_to_opening_drive_high = ((bar.close / opening_drive_high) - 1.0) if opening_drive_high else 0.0
        distance_to_opening_drive_low = ((bar.close / opening_drive_low) - 1.0) if opening_drive_low else 0.0
        opening_drive_break_up = 1.0 if opening_drive_high and bar.close > opening_drive_high else 0.0
        opening_drive_break_down = 1.0 if opening_drive_low and bar.close < opening_drive_low else 0.0
        first_pullback_long = (
            1.0
            if in_regular_session
            and minutes_from_open >= 30
            and opening_drive_return_pct > 0.0
            and bar.low <= session_vwap <= bar.close
            and bar.close > current_regular_open
            else 0.0
        )
        first_pullback_short = (
            1.0
            if in_regular_session
            and minutes_from_open >= 30
            and opening_drive_return_pct < 0.0
            and bar.high >= session_vwap >= bar.close
            and bar.close < current_regular_open
            else 0.0
        )
        morning_session = 1.0 if in_regular_session and 0 <= minutes_from_open < 90 else 0.0
        midday_session = 1.0 if in_regular_session and 90 <= minutes_from_open < 180 else 0.0
        afternoon_session = 1.0 if in_regular_session and 180 <= minutes_from_open < 330 else 0.0
        event_flags = (daily_event_flags or {}).get(bar.timestamp.date(), DailyEventFlags())
        session_reference_values: dict[str, float] = {}
        for label in session_reference_labels:
            state = session_reference_state[label]
            ready = bool(state["ready"])
            ref_high = float(state["high"]) if ready else 0.0
            ref_low = float(state["low"]) if ready else 0.0
            ref_open = float(state["open"]) if ready else 0.0
            ref_range = max(ref_high - ref_low, bar.close * 0.0005) if ready else 0.0
            distance_high = ((bar.close / ref_high) - 1.0) if ready and ref_high else 0.0
            distance_low = ((bar.close / ref_low) - 1.0) if ready and ref_low else 0.0
            reclaimed_high = 1.0 if ready and bar.low <= ref_high <= bar.close else 0.0
            reclaimed_low = 1.0 if ready and bar.high >= ref_low >= bar.close else 0.0
            broke_above = 1.0 if ready and bar.close > ref_high else 0.0
            broke_below = 1.0 if ready and bar.close < ref_low else 0.0
            reentered = 1.0 if ready and ref_low <= bar.close <= ref_high else 0.0
            session_reference_values.update(
                {
                    f"{label}_open": ref_open,
                    f"{label}_high": ref_high,
                    f"{label}_low": ref_low,
                    f"{label}_range_pct": (ref_range / bar.close) if ready and bar.close else 0.0,
                    f"distance_to_{label}_high": distance_high,
                    f"distance_to_{label}_low": distance_low,
                    f"reclaimed_{label}_high": reclaimed_high,
                    f"reclaimed_{label}_low": reclaimed_low,
                    f"broke_{label}_range_up": broke_above,
                    f"broke_{label}_range_down": broke_below,
                    f"reentered_{label}_range": reentered,
                }
            )
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
                    "prior_day_high": previous_regular_high,
                    "prior_day_low": previous_regular_low,
                    "prior_day_close": previous_regular_close,
                    "prior_day_range_pct": (prior_day_range / previous_regular_close) if previous_regular_close else 0.0,
                    "distance_to_prior_day_high": distance_to_prior_day_high,
                    "distance_to_prior_day_low": distance_to_prior_day_low,
                    "distance_to_prior_day_close": distance_to_prior_day_close,
                    "prior_day_position": prior_day_position,
                    "overnight_high": current_overnight_high,
                    "overnight_low": current_overnight_low,
                    "overnight_open": current_overnight_open,
                    "overnight_range_pct": (overnight_range / bar.close) if bar.close and saw_overnight_bar_today else 0.0,
                    "distance_to_overnight_high": distance_to_overnight_high,
                    "distance_to_overnight_low": distance_to_overnight_low,
                    "overnight_position": overnight_position,
                    "premarket_high": premarket_high,
                    "premarket_low": premarket_low,
                    "premarket_open": premarket_open,
                    "premarket_range_pct": (premarket_range / bar.close) if premarket_range and bar.close else 0.0,
                    "distance_to_premarket_high": distance_to_premarket_high,
                    "distance_to_premarket_low": distance_to_premarket_low,
                    "reclaimed_premarket_high": reclaimed_premarket_high,
                    "reclaimed_premarket_low": reclaimed_premarket_low,
                    "broke_premarket_high": broke_premarket_high,
                    "broke_premarket_low": broke_premarket_low,
                    "open_vs_premarket_high_pct": ((current_regular_open / premarket_high) - 1.0) if current_regular_open and premarket_high else 0.0,
                    "open_vs_premarket_low_pct": ((current_regular_open / premarket_low) - 1.0) if current_regular_open and premarket_low else 0.0,
                    "opening_gap_pct": opening_gap_pct,
                    "opening_drive_high": opening_drive_high,
                    "opening_drive_low": opening_drive_low,
                    "opening_drive_range_pct": (opening_drive_range / bar.close) if opening_drive_range and bar.close else 0.0,
                    "opening_drive_return_pct": opening_drive_return_pct,
                    "distance_to_opening_drive_high": distance_to_opening_drive_high,
                    "distance_to_opening_drive_low": distance_to_opening_drive_low,
                    "opening_drive_break_up": opening_drive_break_up,
                    "opening_drive_break_down": opening_drive_break_down,
                    "first_pullback_long": first_pullback_long,
                    "first_pullback_short": first_pullback_short,
                    "morning_session": morning_session,
                    "midday_session": midday_session,
                    "afternoon_session": afternoon_session,
                    "news_count_1d": float(event_flags.news_count),
                    "high_impact_news_count_1d": float(event_flags.high_impact_count),
                    "earnings_news_count_1d": float(event_flags.earnings_like_count),
                    "high_impact_event_day": 1.0 if event_flags.high_impact_count > 0 else 0.0,
                    "earnings_event_day": 1.0 if event_flags.earnings_like_count > 0 else 0.0,
                    "event_blackout": 1.0 if event_flags.event_blackout else 0.0,
                    **session_reference_values,
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
