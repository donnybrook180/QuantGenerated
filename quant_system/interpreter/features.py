from __future__ import annotations

from dataclasses import dataclass
import math

from quant_system.config import SystemConfig
from quant_system.data.market_data import DuckDBMarketDataStore
from quant_system.integrations.macro_events import apply_macro_event_context
from quant_system.live.models import SymbolDeployment
from quant_system.models import FeatureVector, MarketBar
from quant_system.regime import RegimeSnapshot
from quant_system.tca import TCAReport, generate_tca_report


def _safe_div(numerator: float, denominator: float) -> float:
    if abs(denominator) <= 1e-12:
        return 0.0
    return numerator / denominator


def _mean(values: list[float]) -> float:
    return sum(values) / float(len(values)) if values else 0.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = _mean(values)
    variance = sum((value - avg) ** 2 for value in values) / float(len(values))
    return math.sqrt(max(variance, 0.0))


def _session_window(hour: int) -> tuple[str, int, int]:
    if 0 <= hour < 7:
        return ("asia", 0, 7)
    if 7 <= hour < 13:
        return ("europe", 7, 13)
    if 13 <= hour < 17:
        return ("us_open", 13, 17)
    return ("us_late", 17, 24)


def _bars_timeframe_label(config: SystemConfig) -> str:
    configured = (config.instrument.timeframe_label or "").strip()
    if configured:
        return configured
    return f"{config.market_data.multiplier}_{config.market_data.timespan}"


def _timeframe_candidates(config: SystemConfig, deployment: SymbolDeployment, store: DuckDBMarketDataStore) -> list[str]:
    configured = _bars_timeframe_label(config)
    fallback = "5_minute"
    available = store.list_timeframes(deployment.data_symbol)
    exact_candidates: list[str] = []
    suffix_candidates: list[str] = []
    seen: set[str] = set()
    for label in (configured, fallback):
        if label and label not in seen:
            exact_candidates.append(label)
            seen.add(label)
    for label in available:
        if label in seen:
            continue
        if label.endswith(configured) or label.endswith(fallback):
            suffix_candidates.append(label)
            seen.add(label)
    return exact_candidates + suffix_candidates


def _load_bars(config: SystemConfig, deployment: SymbolDeployment, limit: int = 320) -> tuple[str, list[MarketBar]]:
    store = DuckDBMarketDataStore(config.ai.experiment_database_path, read_only=True)
    candidates = _timeframe_candidates(config, deployment, store)
    for timeframe in candidates:
        bars = store.load_bars(deployment.data_symbol, timeframe, limit)
        if bars:
            return timeframe, bars
    fallback = _bars_timeframe_label(config)
    return fallback, []


@dataclass(slots=True)
class FeatureContext:
    timeframe: str
    bars: list[MarketBar]
    feature_values: dict[str, float]
    tca_report: TCAReport
    latest_feature: FeatureVector
    regime_snapshot: RegimeSnapshot | None = None


def build_feature_context(config: SystemConfig, deployment: SymbolDeployment) -> FeatureContext | None:
    timeframe, bars = _load_bars(config, deployment)
    if len(bars) < 30:
        return None
    tca_report = generate_tca_report(config, broker_symbol=deployment.broker_symbol)
    latest = bars[-1]
    closes = [bar.close for bar in bars]
    highs = [bar.high for bar in bars]
    lows = [bar.low for bar in bars]
    true_ranges: list[float] = []
    for index, bar in enumerate(bars[1:], start=1):
        prev_close = bars[index - 1].close
        true_ranges.append(max(bar.high - bar.low, abs(bar.high - prev_close), abs(bar.low - prev_close)))
    atr = _mean(true_ranges[-14:]) if true_ranges else max(latest.high - latest.low, 0.0)
    atr_pct = _safe_div(atr, latest.close)
    recent_high = max(highs[-20:])
    recent_low = min(lows[-20:])
    prior_window_high = max(highs[-40:-20]) if len(highs) >= 40 else recent_high
    prior_window_low = min(lows[-40:-20]) if len(lows) >= 40 else recent_low
    range_20 = recent_high - recent_low
    range_80 = (max(highs[-80:]) - min(lows[-80:])) if len(highs) >= 80 else range_20
    fast_return = _safe_div(latest.close - closes[-10], closes[-10]) * 100.0 if len(closes) >= 10 else 0.0
    slow_return = _safe_div(latest.close - closes[-30], closes[-30]) * 100.0 if len(closes) >= 30 else fast_return
    session_bucket, session_open_hour, session_close_hour = _session_window(latest.timestamp.hour)
    hour_fraction = latest.timestamp.hour + latest.timestamp.minute / 60.0
    feature = FeatureVector(timestamp=latest.timestamp, symbol=deployment.symbol, values={})
    apply_macro_event_context(
        [feature],
        deployment.symbol,
        config.macro_calendar.calendar_path if config.macro_calendar.enabled else None,
        pre_event_minutes=config.macro_calendar.pre_event_minutes,
        post_event_minutes=config.macro_calendar.post_event_minutes,
    )
    spreads = [row.avg_spread_points for row in tca_report.by_hour] if tca_report.by_hour else []
    current_spread = tca_report.overview.avg_spread_points if tca_report.overview is not None else 0.0
    spread_z = _safe_div(current_spread - _mean(spreads), _std(spreads)) if spreads else 0.0
    feature_values: dict[str, float] = {
        "latest_close": latest.close,
        "latest_volume": latest.volume,
        "fast_trend_return_pct": fast_return,
        "slow_trend_return_pct": slow_return,
        "atr_pct": atr_pct,
        "range_compression_score": 1.0 - min(1.0, _safe_div(range_20, range_80 if range_80 > 0.0 else 1.0)),
        "breakout_distance_atr": _safe_div(latest.close - prior_window_high, atr if atr > 0.0 else latest.close),
        "distance_to_prev_day_high_atr": _safe_div(prior_window_high - latest.close, atr if atr > 0.0 else latest.close),
        "distance_to_prev_day_low_atr": _safe_div(latest.close - prior_window_low, atr if atr > 0.0 else latest.close),
        "close_location_in_range": _safe_div(latest.close - recent_low, range_20 if range_20 > 0.0 else 1.0),
        "wick_asymmetry": _safe_div((latest.high - max(latest.open, latest.close)) - (min(latest.open, latest.close) - latest.low), atr if atr > 0.0 else 1.0),
        "minutes_since_session_open": max(0.0, (hour_fraction - session_open_hour) * 60.0),
        "minutes_to_session_close": max(0.0, (session_close_hour - hour_fraction) * 60.0),
        "spread_regime_zscore": spread_z,
        "shortfall_regime_bps": tca_report.overview.weighted_shortfall_bps if tca_report.overview is not None else 0.0,
        "cost_regime_bps": tca_report.overview.weighted_cost_bps if tca_report.overview is not None else 0.0,
        "adverse_fill_rate_pct": tca_report.overview.adverse_touch_fill_rate_pct if tca_report.overview is not None else 0.0,
        "execution_fill_count": float(tca_report.overview.fill_count if tca_report.overview is not None else 0),
    }
    feature_values.update(feature.values)
    feature_values["session_bucket"] = session_bucket  # kept as string-like value in engine access via str()
    return FeatureContext(
        timeframe=timeframe,
        bars=bars,
        feature_values=feature_values,
        tca_report=tca_report,
        latest_feature=feature,
        regime_snapshot=None,
    )
