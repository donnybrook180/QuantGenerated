from __future__ import annotations

from quant_system.interpreter.models import InterpreterFeatureSnapshot, InterpreterState
from quant_system.regime import map_regime_label_to_unified


def classify_macro_regime(values: dict[str, float]) -> str:
    if values.get("macro_pre_event_window", 0.0) >= 1.0:
        return "event_risk_high"
    if values.get("macro_post_event_window", 0.0) >= 1.0:
        return "post_event_repricing"
    if values.get("macro_high_impact_event_day", 0.0) >= 1.0:
        return "event_day"
    return "neutral"


def classify_session_regime(values: dict[str, float]) -> str:
    bucket = str(values.get("session_bucket", "unknown"))
    if values.get("macro_pre_event_window", 0.0) >= 1.0:
        return "pre_event"
    if values.get("macro_post_event_window", 0.0) >= 1.0:
        return "post_event"
    if bucket == "us_open":
        return "us_open_expansion" if abs(values.get("fast_trend_return_pct", 0.0)) > 0.20 else "us_open_balance"
    if bucket == "europe":
        return "europe_trend" if abs(values.get("slow_trend_return_pct", 0.0)) > 0.25 else "europe_balance"
    if bucket == "asia":
        return "asia_balance"
    return "midday_chop"


def classify_structure_regime(values: dict[str, float]) -> str:
    if values.get("range_compression_score", 0.0) >= 0.55:
        return "compression"
    if values.get("breakout_distance_atr", 0.0) > 0.25 and values.get("close_location_in_range", 0.0) > 0.70:
        return "clean_breakout"
    if values.get("breakout_distance_atr", 0.0) < -0.25 and values.get("close_location_in_range", 0.0) < 0.30:
        return "failed_breakout"
    if abs(values.get("slow_trend_return_pct", 0.0)) > 0.25:
        return "trend_pullback"
    return "range_rotation"


def classify_volatility_regime(values: dict[str, float]) -> str:
    atr_pct = values.get("atr_pct", 0.0)
    if atr_pct >= 0.015:
        return "high_dislocated"
    if atr_pct >= 0.008:
        return "high_orderly"
    if atr_pct <= 0.003:
        return "low"
    return "normal"


def classify_execution_regime(values: dict[str, float]) -> str:
    fills = int(values.get("execution_fill_count", 0))
    if fills < 4:
        return "unknown"
    if values.get("shortfall_regime_bps", 0.0) >= 6.0 or values.get("cost_regime_bps", 0.0) >= 3.0 or values.get("adverse_fill_rate_pct", 0.0) >= 80.0:
        return "toxic"
    if values.get("shortfall_regime_bps", 0.0) >= 3.0 or values.get("cost_regime_bps", 0.0) >= 1.5 or values.get("adverse_fill_rate_pct", 0.0) >= 65.0:
        return "fragile"
    if values.get("shortfall_regime_bps", 0.0) >= 1.5 or values.get("cost_regime_bps", 0.0) >= 0.75 or values.get("adverse_fill_rate_pct", 0.0) >= 55.0:
        return "acceptable"
    return "clean"


def derive_directional_bias(values: dict[str, float], structure_regime: str) -> str:
    if structure_regime == "clean_breakout":
        return "long" if values.get("breakout_distance_atr", 0.0) >= 0.0 else "short"
    if values.get("slow_trend_return_pct", 0.0) > 0.0:
        return "long"
    if values.get("slow_trend_return_pct", 0.0) < 0.0:
        return "short"
    return "neutral"


def score_setup_quality(values: dict[str, float], structure_regime: str, session_regime: str) -> float:
    score = 0.50
    if structure_regime in {"trend_pullback", "clean_breakout"}:
        score += 0.15
    if structure_regime == "compression":
        score -= 0.10
    if session_regime in {"us_open_expansion", "europe_trend"}:
        score += 0.10
    if session_regime in {"midday_chop", "pre_event"}:
        score -= 0.15
    score += min(0.10, abs(values.get("slow_trend_return_pct", 0.0)) / 2.0)
    return max(0.0, min(1.0, score))


def score_execution_quality(values: dict[str, float], execution_regime: str) -> float:
    base = {"clean": 0.85, "acceptable": 0.65, "fragile": 0.40, "toxic": 0.15}.get(execution_regime, 0.50)
    base -= min(0.20, max(0.0, values.get("spread_regime_zscore", 0.0)) * 0.05)
    return max(0.0, min(1.0, base))


def derive_risk_posture(session_regime: str, volatility_regime: str, execution_regime: str, confidence: float) -> tuple[str, str]:
    if session_regime == "pre_event":
        return "defensive", "pre_event_window"
    if execution_regime == "toxic":
        return "defensive", "execution_toxic"
    if confidence < 0.35:
        return "defensive", "low_confidence"
    if execution_regime == "fragile" or volatility_regime == "high_dislocated":
        return "reduced", "fragile_execution_or_dislocated_vol"
    return "normal", ""


def derive_allowed_archetypes(structure_regime: str, session_regime: str, execution_regime: str, directional_bias: str) -> tuple[list[str], list[str]]:
    if execution_regime == "toxic" or session_regime == "pre_event":
        return ([], ["breakout", "trend_pullback", "mean_reversion", "reclaim"])
    allowed: list[str] = []
    blocked: list[str] = []
    if structure_regime == "trend_pullback":
        allowed.extend(["trend_pullback", "reclaim"])
        blocked.append("mean_reversion")
    elif structure_regime == "clean_breakout":
        allowed.extend(["breakout", "reclaim"])
        blocked.append("mean_reversion")
    elif structure_regime == "range_rotation":
        allowed.append("mean_reversion")
        blocked.append("breakout")
    elif structure_regime == "compression":
        allowed.append("breakout")
        blocked.append("mean_reversion")
    else:
        blocked.append("breakout")
    if directional_bias == "neutral":
        blocked.append("trend_pullback")
    return (sorted(set(allowed)), sorted(set(blocked)))


def build_explanation(state: InterpreterState) -> str:
    if state.no_trade_reason:
        return f"{state.unified_regime_label} / {state.session_regime} with {state.execution_regime} execution; no trade because {state.no_trade_reason}."
    archetypes = ", ".join(state.allowed_archetypes) if state.allowed_archetypes else "none"
    return f"{state.unified_regime_label} with {state.session_regime} and {state.structure_regime} favors {state.directional_bias}; execution is {state.execution_regime}; allowed archetypes: {archetypes}."


def build_feature_snapshot(values: dict[str, float], timeframe: str, bar_count: int) -> InterpreterFeatureSnapshot:
    return InterpreterFeatureSnapshot(
        timeframe=timeframe,
        bar_count=bar_count,
        latest_close=float(values.get("latest_close", 0.0)),
        latest_volume=float(values.get("latest_volume", 0.0)),
        fast_trend_return_pct=float(values.get("fast_trend_return_pct", 0.0)),
        slow_trend_return_pct=float(values.get("slow_trend_return_pct", 0.0)),
        atr_pct=float(values.get("atr_pct", 0.0)),
        range_compression_score=float(values.get("range_compression_score", 0.0)),
        breakout_distance_atr=float(values.get("breakout_distance_atr", 0.0)),
        distance_to_prev_day_high_atr=float(values.get("distance_to_prev_day_high_atr", 0.0)),
        distance_to_prev_day_low_atr=float(values.get("distance_to_prev_day_low_atr", 0.0)),
        close_location_in_range=float(values.get("close_location_in_range", 0.0)),
        wick_asymmetry=float(values.get("wick_asymmetry", 0.0)),
        session_bucket=str(values.get("session_bucket", "unknown")),
        minutes_since_session_open=float(values.get("minutes_since_session_open", 0.0)),
        minutes_to_session_close=float(values.get("minutes_to_session_close", 0.0)),
        macro_high_impact_day=float(values.get("macro_high_impact_event_day", 0.0)),
        macro_pre_event_window=float(values.get("macro_pre_event_window", 0.0)),
        macro_post_event_window=float(values.get("macro_post_event_window", 0.0)),
        macro_minutes_to_next_event=float(values.get("macro_minutes_to_next_event", -1.0)),
        spread_regime_zscore=float(values.get("spread_regime_zscore", 0.0)),
        shortfall_regime_bps=float(values.get("shortfall_regime_bps", 0.0)),
        cost_regime_bps=float(values.get("cost_regime_bps", 0.0)),
        adverse_fill_rate_pct=float(values.get("adverse_fill_rate_pct", 0.0)),
        execution_fill_count=int(values.get("execution_fill_count", 0)),
    )
