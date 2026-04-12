from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from quant_system.regime import RegimeSnapshot


@dataclass(slots=True)
class InterpreterFeatureSnapshot:
    timeframe: str
    bar_count: int
    latest_close: float
    latest_volume: float
    fast_trend_return_pct: float
    slow_trend_return_pct: float
    atr_pct: float
    range_compression_score: float
    breakout_distance_atr: float
    distance_to_prev_day_high_atr: float
    distance_to_prev_day_low_atr: float
    close_location_in_range: float
    wick_asymmetry: float
    session_bucket: str
    minutes_since_session_open: float
    minutes_to_session_close: float
    macro_high_impact_day: float
    macro_pre_event_window: float
    macro_post_event_window: float
    macro_minutes_to_next_event: float
    spread_regime_zscore: float
    shortfall_regime_bps: float
    cost_regime_bps: float
    adverse_fill_rate_pct: float
    execution_fill_count: int


@dataclass(slots=True)
class InterpreterState:
    symbol: str
    broker_symbol: str
    generated_at: datetime
    legacy_regime_label: str
    unified_regime_label: str
    macro_regime: str
    session_regime: str
    structure_regime: str
    volatility_regime: str
    execution_regime: str
    crowding_regime: str
    directional_bias: str
    setup_quality: float
    execution_quality: float
    confidence: float
    risk_posture: str
    allowed_archetypes: list[str] = field(default_factory=list)
    blocked_archetypes: list[str] = field(default_factory=list)
    no_trade_reason: str = ""
    explanation: str = ""
    feature_snapshot: InterpreterFeatureSnapshot | None = None
    regime_snapshot: RegimeSnapshot | None = None
