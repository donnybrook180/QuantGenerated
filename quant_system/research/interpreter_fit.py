from __future__ import annotations

from quant_system.interpreter.engines import (
    classify_execution_regime,
    classify_session_regime,
    classify_structure_regime,
    classify_volatility_regime,
    derive_allowed_archetypes,
    derive_directional_bias,
    derive_risk_posture,
)
from quant_system.models import FeatureVector


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _candidate_archetype(candidate_name: str, strategy_family: str, code_path: str) -> str:
    text = " ".join((candidate_name, strategy_family, code_path)).lower()
    if "reclaim" in text:
        return "reclaim"
    if "reversion" in text:
        return "mean_reversion"
    if "breakout" in text:
        return "breakout"
    if "pullback" in text or "trend" in text:
        return "trend_pullback"
    return "unknown"


def _session_bucket(values: dict[str, float]) -> str:
    hour = int(float(values.get("hour_of_day", -1.0) or -1.0))
    if 0 <= hour < 7:
        return "asia"
    if 7 <= hour < 13:
        return "europe"
    if 13 <= hour < 17:
        return "us_open"
    if 17 <= hour < 24:
        return "us_late"
    return "unknown"


def estimate_interpreter_fit(
    *,
    candidate_name: str,
    strategy_family: str,
    code_path: str,
    features: list[FeatureVector],
) -> dict[str, object]:
    archetype = _candidate_archetype(candidate_name, strategy_family, code_path)
    if archetype == "unknown" or not features:
        return {
            "interpreter_fit_score": 0.5 if features else 0.0,
            "common_live_regime_fit": 0.0,
            "blocked_by_interpreter_risk": 1.0 if not features else 0.5,
            "interpreter_fit_reasons": ("interpreter_archetype_unknown",) if archetype == "unknown" else ("interpreter_features_missing",),
        }

    sampled = features[-min(len(features), 240):]
    allowed_matches = 0
    blocked_matches = 0
    no_trade_count = 0
    for feature in sampled:
        values = dict(feature.values)
        values.setdefault("session_bucket", _session_bucket(values))
        structure_regime = classify_structure_regime(values)
        session_regime = classify_session_regime(values)
        execution_regime = classify_execution_regime(values)
        volatility_regime = classify_volatility_regime(values)
        directional_bias = derive_directional_bias(values, structure_regime)
        confidence = max(
            0.0,
            min(
                1.0,
                0.6 + min(0.2, abs(float(values.get("slow_trend_return_pct", 0.0) or 0.0))),
            ),
        )
        _risk_posture, no_trade_reason = derive_risk_posture(session_regime, volatility_regime, execution_regime, confidence)
        allowed, blocked = derive_allowed_archetypes(structure_regime, session_regime, execution_regime, directional_bias)
        if no_trade_reason:
            no_trade_count += 1
            blocked_matches += 1
            continue
        if archetype in blocked:
            blocked_matches += 1
        elif not allowed or archetype in allowed:
            allowed_matches += 1
        else:
            blocked_matches += 1

    total = float(len(sampled))
    common_live_regime_fit = allowed_matches / total if total > 0.0 else 0.0
    blocked_by_interpreter_risk = blocked_matches / total if total > 0.0 else 1.0
    no_trade_share = no_trade_count / total if total > 0.0 else 1.0
    interpreter_fit_score = round(
        _clamp01((common_live_regime_fit * 0.7) + ((1.0 - blocked_by_interpreter_risk) * 0.3)),
        4,
    )
    reasons: list[str] = []
    if blocked_by_interpreter_risk >= 0.70:
        reasons.append("blocked_by_interpreter_risk_high")
    elif blocked_by_interpreter_risk >= 0.45:
        reasons.append("blocked_by_interpreter_risk_elevated")
    if common_live_regime_fit <= 0.20:
        reasons.append("common_live_regime_fit_low")
    elif common_live_regime_fit <= 0.40:
        reasons.append("common_live_regime_fit_limited")
    if no_trade_share >= 0.50:
        reasons.append("interpreter_no_trade_share_high")
    return {
        "interpreter_fit_score": interpreter_fit_score,
        "common_live_regime_fit": round(common_live_regime_fit, 4),
        "blocked_by_interpreter_risk": round(blocked_by_interpreter_risk, 4),
        "interpreter_fit_reasons": tuple(reasons),
    }
