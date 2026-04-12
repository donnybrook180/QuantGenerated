from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from quant_system.models import FeatureVector, MarketBar


@dataclass(slots=True)
class RegimeSnapshot:
    timestamp: datetime
    symbol: str
    regime_label: str
    volatility_label: str
    structure_label: str
    realized_vol_20: float
    realized_vol_100: float
    vol_ratio: float
    vol_percentile: float
    atr_percent: float
    trend_strength: float
    range_efficiency: float
    risk_multiplier: float
    block_new_entries: bool = False
    metadata: dict[str, float | str] = field(default_factory=dict)


def map_regime_label_to_unified(regime_label: str, volatility_label: str, structure_label: str) -> str:
    if regime_label == "event_risk":
        return "event_dislocation"
    if regime_label == "volatile_trend":
        return "trend_expansion"
    if regime_label == "volatile_chop":
        return "dislocated_chop"
    if regime_label == "calm_trend":
        return "orderly_trend"
    if regime_label == "calm_range":
        if structure_label == "trend":
            return "orderly_trend"
        if volatility_label == "low":
            return "compressed_range"
        return "orderly_range"
    if volatility_label == "high" and structure_label == "trend":
        return "trend_expansion"
    if volatility_label == "high":
        return "dislocated_chop"
    if structure_label == "trend":
        return "orderly_trend"
    return "orderly_range"


def _sample_std(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(max(variance, 0.0))


def _close_returns(bars: list[MarketBar]) -> list[float]:
    returns: list[float] = []
    previous_close: float | None = None
    for bar in bars:
        close = float(bar.close)
        if previous_close is not None and previous_close > 0.0 and close > 0.0:
            returns.append(math.log(close / previous_close))
        previous_close = close
    return returns


def _realized_vol(returns: list[float], window: int) -> float:
    if not returns:
        return 0.0
    sample = returns[-window:] if len(returns) >= window else returns
    return _sample_std(sample) * math.sqrt(252.0)


def _vol_percentile(returns: list[float], window: int = 20, history_window: int = 120) -> float:
    if len(returns) < window:
        return 0.5
    rolling: list[float] = []
    start_index = max(window, len(returns) - history_window)
    for index in range(start_index, len(returns) + 1):
        sample = returns[index - window : index]
        rolling.append(_sample_std(sample) * math.sqrt(252.0))
    if not rolling:
        return 0.5
    current = rolling[-1]
    rank = sum(1 for value in rolling if value <= current)
    return rank / len(rolling)


def _atr_percent(bars: list[MarketBar], window: int = 14) -> float:
    if not bars:
        return 0.0
    sample = bars[-window:] if len(bars) >= window else bars
    total_range = 0.0
    valid = 0
    for bar in sample:
        if bar.close <= 0.0:
            continue
        total_range += max(bar.high - bar.low, 0.0) / bar.close
        valid += 1
    return total_range / valid if valid else 0.0


def _range_efficiency(bars: list[MarketBar], window: int = 20) -> float:
    if len(bars) < 2:
        return 0.0
    sample = bars[-window:] if len(bars) >= window else bars
    path = 0.0
    for previous, current in zip(sample, sample[1:]):
        path += abs(current.close - previous.close)
    if path <= 0.0:
        return 0.0
    net = abs(sample[-1].close - sample[0].close)
    return net / path


def classify_regime(symbol: str, bars: list[MarketBar], latest_feature: FeatureVector | None) -> RegimeSnapshot:
    if bars:
        timestamp = bars[-1].timestamp
    elif latest_feature is not None:
        timestamp = latest_feature.timestamp
    else:
        timestamp = datetime.utcnow()

    returns = _close_returns(bars)
    realized_vol_20 = _realized_vol(returns, 20)
    realized_vol_100 = _realized_vol(returns, 100)
    vol_ratio = realized_vol_20 / realized_vol_100 if realized_vol_100 > 0.0 else 1.0
    vol_percentile = _vol_percentile(returns)
    atr_percent = _atr_percent(bars)
    trend_strength = float(latest_feature.values.get("trend_strength", 0.0)) if latest_feature is not None else 0.0
    range_efficiency = _range_efficiency(bars)

    strong_trend = abs(trend_strength) >= 0.001 or range_efficiency >= 0.35
    very_high_vol = vol_percentile >= 0.98 or atr_percent >= 0.025 or vol_ratio >= 2.2
    high_vol = vol_percentile >= 0.75 or atr_percent >= 0.010 or vol_ratio >= 1.35
    low_vol = vol_percentile <= 0.25 and atr_percent <= 0.004 and vol_ratio <= 0.90

    if strong_trend:
        structure_label = "trend"
    else:
        structure_label = "range"

    if very_high_vol:
        volatility_label = "event_risk"
        regime_label = "event_risk"
        risk_multiplier = 0.0
        block_new_entries = True
    elif high_vol and strong_trend:
        volatility_label = "high"
        regime_label = "volatile_trend"
        risk_multiplier = 0.5
        block_new_entries = False
    elif high_vol:
        volatility_label = "high"
        regime_label = "volatile_chop"
        risk_multiplier = 0.15
        block_new_entries = True
    elif low_vol and strong_trend:
        volatility_label = "low"
        regime_label = "calm_trend"
        risk_multiplier = 1.0
        block_new_entries = False
    else:
        volatility_label = "normal" if not low_vol else "low"
        regime_label = "calm_range"
        risk_multiplier = 0.8
        block_new_entries = False

    return RegimeSnapshot(
        timestamp=timestamp,
        symbol=symbol,
        regime_label=regime_label,
        volatility_label=volatility_label,
        structure_label=structure_label,
        realized_vol_20=realized_vol_20,
        realized_vol_100=realized_vol_100,
        vol_ratio=vol_ratio,
        vol_percentile=vol_percentile,
        atr_percent=atr_percent,
        trend_strength=trend_strength,
        range_efficiency=range_efficiency,
        risk_multiplier=risk_multiplier,
        block_new_entries=block_new_entries,
        metadata={
            "strong_trend": "yes" if strong_trend else "no",
            "bar_count": float(len(bars)),
        },
    )


def regime_allows_strategy(
    snapshot: RegimeSnapshot,
    *,
    allowed_regimes: tuple[str, ...] = (),
    blocked_regimes: tuple[str, ...] = (),
    min_vol_percentile: float = 0.0,
    max_vol_percentile: float = 1.0,
) -> bool:
    unified_label = map_regime_label_to_unified(
        snapshot.regime_label,
        snapshot.volatility_label,
        snapshot.structure_label,
    )
    if snapshot.vol_percentile < min_vol_percentile or snapshot.vol_percentile > max_vol_percentile:
        return False
    if allowed_regimes and snapshot.regime_label not in allowed_regimes and unified_label not in allowed_regimes:
        return False
    if blocked_regimes and (snapshot.regime_label in blocked_regimes or unified_label in blocked_regimes):
        return False
    return True
