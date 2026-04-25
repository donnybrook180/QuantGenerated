from __future__ import annotations

import copy
import itertools

from quant_system.research.common import (
    component_names,
    component_set,
    direction_mode,
    direction_role,
    family_unused_for_single_selection,
    meets_monte_carlo_viability,
    metric_map_from_row,
    research_thresholds,
    row_value,
    strategy_family,
)
from quant_system.research.viability import (
    meets_regime_specialist_viability,
    meets_viability,
    promotion_tier_for_row,
    specialist_live_gate,
)
from quant_system.symbols import (
    is_crypto_symbol as symbol_is_crypto,
    is_forex_symbol as symbol_is_forex,
    is_metal_symbol as symbol_is_metal,
)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _blue_guardian_signal_quality_score(row: object | dict[str, object], symbol: str) -> float:
    thresholds = research_thresholds(symbol)
    profit_factor = float(row_value(row, "profit_factor", 0.0) or 0.0)
    validation_pnl = float(row_value(row, "validation_pnl", 0.0) or 0.0)
    test_pnl = float(row_value(row, "test_pnl", 0.0) or 0.0)
    walk_forward_pass_rate_pct = max(
        float(row_value(row, "walk_forward_pass_rate_pct", 0.0) or 0.0),
        float(row_value(row, "walk_forward_soft_pass_rate_pct", 0.0) or 0.0),
    )
    equity_quality_score = float(row_value(row, "equity_quality_score", 0.0) or 0.0)
    regime_stability_score = float(row_value(row, "regime_stability_score", 0.0) or 0.0)
    best_trade_share_pct = float(row_value(row, "best_trade_share_pct", 100.0) or 100.0)
    score = (
        (_clamp01((profit_factor - 1.0) / 1.0) * 0.24)
        + ((1.0 if validation_pnl > 0.0 else 0.0) * 0.14)
        + ((1.0 if test_pnl > 0.0 else 0.0) * 0.14)
        + (_clamp01(walk_forward_pass_rate_pct / max(float(thresholds["walk_forward_min_pass_rate_pct"]), 1.0)) * 0.16)
        + (_clamp01(equity_quality_score) * 0.18)
        + (_clamp01(regime_stability_score) * 0.09)
        + (_clamp01((80.0 - best_trade_share_pct) / 80.0) * 0.05)
    )
    if meets_monte_carlo_viability(row):
        score += 0.05
    return round(_clamp01(score), 4)


def _blue_guardian_prop_viability_profile(
    row: object | dict[str, object],
    symbol: str,
    *,
    specialist_live_approved: bool,
    specialist_live_rejection_reasons: list[str],
) -> tuple[float, str, bool, tuple[str, ...]]:
    reasons: list[str] = []
    signal_quality_score = _blue_guardian_signal_quality_score(row, symbol)
    validation_pnl = float(row_value(row, "validation_pnl", 0.0) or 0.0)
    test_pnl = float(row_value(row, "test_pnl", 0.0) or 0.0)
    profit_factor = float(row_value(row, "profit_factor", 0.0) or 0.0)
    walk_forward_pass_rate_pct = max(
        float(row_value(row, "walk_forward_pass_rate_pct", 0.0) or 0.0),
        float(row_value(row, "walk_forward_soft_pass_rate_pct", 0.0) or 0.0),
    )
    equity_quality_score = float(row_value(row, "equity_quality_score", 0.0) or 0.0)
    best_trade_share_pct = float(row_value(row, "best_trade_share_pct", 100.0) or 100.0)
    estimated_swap_drag_per_trade = float(row_value(row, "estimated_swap_drag_per_trade", 0.0) or 0.0)
    swap_adjusted_expectancy = float(row_value(row, "swap_adjusted_expectancy", 0.0) or 0.0)
    expectancy = float(row_value(row, "expectancy", 0.0) or 0.0)
    broker_swap_available = bool(row_value(row, "broker_swap_available", False))
    stress_expectancy_mild = float(row_value(row, "stress_expectancy_mild", 0.0) or 0.0)
    stress_expectancy_medium = float(row_value(row, "stress_expectancy_medium", 0.0) or 0.0)
    stress_expectancy_harsh = float(row_value(row, "stress_expectancy_harsh", 0.0) or 0.0)
    stress_pf_mild = float(row_value(row, "stress_pf_mild", 0.0) or 0.0)
    stress_pf_medium = float(row_value(row, "stress_pf_medium", 0.0) or 0.0)
    stress_pf_harsh = float(row_value(row, "stress_pf_harsh", 0.0) or 0.0)
    stress_survival_score = float(row_value(row, "stress_survival_score", 0.0) or 0.0)
    stress_metrics_present = any(
        abs(value) > 1e-12
        for value in (
            stress_expectancy_mild,
            stress_expectancy_medium,
            stress_expectancy_harsh,
            stress_pf_mild,
            stress_pf_medium,
            stress_pf_harsh,
            stress_survival_score,
        )
    )
    prop_fit_score = float(row_value(row, "prop_fit_score", 0.0) or 0.0)
    prop_fit_label = str(row_value(row, "prop_fit_label", "fail") or "fail")
    prop_fit_reasons = tuple(str(item) for item in row_value(row, "prop_fit_reasons", ()) or ())
    interpreter_fit_score = float(row_value(row, "interpreter_fit_score", 0.0) or 0.0)
    common_live_regime_fit = float(row_value(row, "common_live_regime_fit", 0.0) or 0.0)
    blocked_by_interpreter_risk = float(row_value(row, "blocked_by_interpreter_risk", 0.0) or 0.0)
    interpreter_fit_reasons = tuple(str(item) for item in row_value(row, "interpreter_fit_reasons", ()) or ())

    if broker_swap_available and estimated_swap_drag_per_trade > 0.0:
        if swap_adjusted_expectancy <= 0.0:
            reasons.append("swap_adjusted_expectancy_non_positive")
        elif expectancy > 0.0 and estimated_swap_drag_per_trade >= (expectancy * 0.5):
            reasons.append("swap_drag_material_to_expectancy")
    if stress_metrics_present:
        if stress_expectancy_mild <= 0.0 or stress_pf_mild < 1.0:
            reasons.append("stress_mild_breaks_viability")
        elif stress_expectancy_medium <= 0.0 or stress_pf_medium < 1.0:
            reasons.append("stress_medium_breaks_viability")
        elif stress_expectancy_harsh <= 0.0 or stress_pf_harsh < 1.0 or stress_survival_score < 0.67:
            reasons.append("stress_harsh_breaks_viability")
    for reason in prop_fit_reasons:
        if reason not in reasons:
            reasons.append(reason)
    for reason in interpreter_fit_reasons:
        if reason not in reasons:
            reasons.append(reason)

    if meets_viability(row, symbol):
        if "swap_adjusted_expectancy_non_positive" in reasons:
            return min(0.49, signal_quality_score), "fail", False, tuple(reasons)
        if "stress_mild_breaks_viability" in reasons or "stress_medium_breaks_viability" in reasons:
            return min(0.49, signal_quality_score), "fail", False, tuple(reasons)
        if prop_fit_label == "fail":
            return min(0.49, min(signal_quality_score, prop_fit_score or signal_quality_score)), "fail", False, tuple(reasons)
        if blocked_by_interpreter_risk >= 0.70 or common_live_regime_fit <= 0.20:
            return min(0.49, min(signal_quality_score, interpreter_fit_score or signal_quality_score)), "fail", False, tuple(reasons)
        if "swap_drag_material_to_expectancy" in reasons:
            return max(0.55, min(0.74, signal_quality_score)), "caution", True, tuple(reasons)
        if "stress_harsh_breaks_viability" in reasons or prop_fit_label == "caution" or blocked_by_interpreter_risk >= 0.45:
            return max(0.55, min(0.74, signal_quality_score)), "caution", True, tuple(reasons)
        return max(0.75, signal_quality_score), "pass", True, ()

    if validation_pnl <= 0.0 or test_pnl <= 0.0:
        reasons.append("out_of_sample_confirmation_weak")
    if profit_factor < 1.0:
        reasons.append("profit_factor_below_live_floor")
    if walk_forward_pass_rate_pct <= 0.0:
        reasons.append("walk_forward_confirmation_missing")
    if equity_quality_score < 0.45:
        reasons.append("equity_quality_too_low")
    if best_trade_share_pct > 70.0:
        reasons.append("regime_concentration_too_high")
    if not meets_monte_carlo_viability(row):
        reasons.append("monte_carlo_tail_risk")

    if meets_regime_specialist_viability(row, symbol) and specialist_live_approved:
        reasons.insert(0, "specialist_only_candidate")
        return max(0.55, min(0.74, signal_quality_score)), "caution", True, tuple(reasons)

    for reason in specialist_live_rejection_reasons:
        if reason not in reasons:
            reasons.append(reason)
    if not reasons:
        reasons.append("core_viability_not_met")
    return min(0.49, signal_quality_score), "fail", False, tuple(reasons)


def execution_candidate_row(symbol: str, row: object | dict[str, object]) -> dict[str, object]:
    specialist_live_approved, specialist_live_rejection_reasons = specialist_live_gate(row, symbol)
    signal_quality_score = _blue_guardian_signal_quality_score(row, symbol)
    prop_viability_score, prop_viability_label, prop_viability_pass, prop_viability_reasons = _blue_guardian_prop_viability_profile(
        row,
        symbol,
        specialist_live_approved=specialist_live_approved,
        specialist_live_rejection_reasons=specialist_live_rejection_reasons,
    )
    return {
        "candidate_name": str(row_value(row, "name", row_value(row, "candidate_name", "")) or ""),
        "symbol": symbol,
        "code_path": str(row_value(row, "code_path", "") or ""),
        "description": str(row_value(row, "description", "") or ""),
        "archetype": str(row_value(row, "archetype", "") or ""),
        "realized_pnl": float(row_value(row, "realized_pnl", 0.0) or 0.0),
        "profit_factor": float(row_value(row, "profit_factor", 0.0) or 0.0),
        "closed_trades": int(row_value(row, "closed_trades", 0) or 0),
        "sharpe_ratio": float(row_value(row, "sharpe_ratio", 0.0) or 0.0),
        "sortino_ratio": float(row_value(row, "sortino_ratio", 0.0) or 0.0),
        "calmar_ratio": float(row_value(row, "calmar_ratio", 0.0) or 0.0),
        "payoff_ratio": float(row_value(row, "payoff_ratio", 0.0) or 0.0),
        "validation_pnl": float(row_value(row, "validation_pnl", 0.0) or 0.0),
        "validation_profit_factor": float(row_value(row, "validation_profit_factor", 0.0) or 0.0),
        "validation_closed_trades": int(row_value(row, "validation_closed_trades", 0) or 0),
        "test_pnl": float(row_value(row, "test_pnl", 0.0) or 0.0),
        "test_profit_factor": float(row_value(row, "test_profit_factor", 0.0) or 0.0),
        "test_closed_trades": int(row_value(row, "test_closed_trades", 0) or 0),
        "walk_forward_windows": int(row_value(row, "walk_forward_windows", 0) or 0),
        "walk_forward_pass_rate_pct": float(row_value(row, "walk_forward_pass_rate_pct", 0.0) or 0.0),
        "walk_forward_soft_pass_rate_pct": float(row_value(row, "walk_forward_soft_pass_rate_pct", 0.0) or 0.0),
        "walk_forward_avg_validation_pnl": float(row_value(row, "walk_forward_avg_validation_pnl", 0.0) or 0.0),
        "walk_forward_avg_test_pnl": float(row_value(row, "walk_forward_avg_test_pnl", 0.0) or 0.0),
        "best_trade_share_pct": float(row_value(row, "best_trade_share_pct", 0.0) or 0.0),
        "expectancy": float(row_value(row, "expectancy", 0.0) or 0.0),
        "equity_new_high_share_pct": float(row_value(row, "equity_new_high_share_pct", 0.0) or 0.0),
        "max_consecutive_losses": int(row_value(row, "max_consecutive_losses", 0) or 0),
        "equity_quality_score": float(row_value(row, "equity_quality_score", 0.0) or 0.0),
        "mc_simulations": int(row_value(row, "mc_simulations", 0) or 0),
        "mc_pnl_median": float(row_value(row, "mc_pnl_median", 0.0) or 0.0),
        "mc_pnl_p05": float(row_value(row, "mc_pnl_p05", 0.0) or 0.0),
        "mc_pnl_p95": float(row_value(row, "mc_pnl_p95", 0.0) or 0.0),
        "mc_max_drawdown_pct_median": float(row_value(row, "mc_max_drawdown_pct_median", 0.0) or 0.0),
        "mc_max_drawdown_pct_p95": float(row_value(row, "mc_max_drawdown_pct_p95", 0.0) or 0.0),
        "mc_loss_probability_pct": float(row_value(row, "mc_loss_probability_pct", 0.0) or 0.0),
        "sparse_strategy": bool(row_value(row, "sparse_strategy", False)),
        "component_count": int(row_value(row, "component_count", 1) or 1),
        "combo_outperformance_score": float(row_value(row, "combo_outperformance_score", 0.0) or 0.0),
        "combo_trade_overlap_pct": float(row_value(row, "combo_trade_overlap_pct", 0.0) or 0.0),
        "signal_quality_score": signal_quality_score,
        "prop_viability_score": prop_viability_score,
        "prop_viability_label": prop_viability_label,
        "prop_viability_pass": prop_viability_pass,
        "prop_viability_reasons": prop_viability_reasons,
        "recommended": False,
        "promotion_tier": promotion_tier_for_row(row, symbol),
        "strategy_family": strategy_family(row),
        "direction_mode": direction_mode(row),
        "direction_role": direction_role(row),
        "variant_label": str(row_value(row, "variant_label", "") or ""),
        "timeframe_label": str(row_value(row, "timeframe_label", "") or ""),
        "session_label": str(row_value(row, "session_label", "") or ""),
        "regime_filter_label": str(row_value(row, "regime_filter_label", "") or ""),
        "cross_filter_label": str(row_value(row, "cross_filter_label", "") or ""),
        "execution_overrides": copy.deepcopy(row_value(row, "execution_overrides", {}) or {}),
        "best_regime": str(row_value(row, "best_regime", "") or ""),
        "best_unified_regime": str(row_value(row, "best_unified_regime", "") or ""),
        "best_regime_pnl": float(row_value(row, "best_regime_pnl", 0.0) or 0.0),
        "worst_regime": str(row_value(row, "worst_regime", "") or ""),
        "worst_unified_regime": str(row_value(row, "worst_unified_regime", "") or ""),
        "worst_regime_pnl": float(row_value(row, "worst_regime_pnl", 0.0) or 0.0),
        "dominant_regime_share_pct": float(row_value(row, "dominant_regime_share_pct", 0.0) or 0.0),
        "regime_stability_score": float(row_value(row, "regime_stability_score", 0.0) or 0.0),
        "regime_loss_ratio": (
            999.0
            if row_value(row, "regime_loss_ratio", 999.0) is None
            else float(row_value(row, "regime_loss_ratio", 999.0))
        ),
        "regime_trade_count_by_label": row_value(row, "regime_trade_count_by_label", "{}"),
        "regime_pf_by_label": row_value(row, "regime_pf_by_label", "{}"),
        "broker_swap_available": bool(row_value(row, "broker_swap_available", False)),
        "broker_swap_long": float(row_value(row, "broker_swap_long", 0.0) or 0.0),
        "broker_swap_short": float(row_value(row, "broker_swap_short", 0.0) or 0.0),
        "broker_carry_spread": float(row_value(row, "broker_carry_spread", 0.0) or 0.0),
        "broker_preferred_carry_side": str(row_value(row, "broker_preferred_carry_side", "") or ""),
        "avg_hold_hours": float(row_value(row, "avg_hold_hours", 0.0) or 0.0),
        "estimated_swap_drag_total": float(row_value(row, "estimated_swap_drag_total", 0.0) or 0.0),
        "estimated_swap_drag_per_trade": float(row_value(row, "estimated_swap_drag_per_trade", 0.0) or 0.0),
        "swap_adjusted_expectancy": float(row_value(row, "swap_adjusted_expectancy", 0.0) or 0.0),
        "carry_preferred_side": str(row_value(row, "carry_preferred_side", "") or ""),
        "stress_expectancy_mild": float(row_value(row, "stress_expectancy_mild", 0.0) or 0.0),
        "stress_expectancy_medium": float(row_value(row, "stress_expectancy_medium", 0.0) or 0.0),
        "stress_expectancy_harsh": float(row_value(row, "stress_expectancy_harsh", 0.0) or 0.0),
        "stress_pf_mild": float(row_value(row, "stress_pf_mild", 0.0) or 0.0),
        "stress_pf_medium": float(row_value(row, "stress_pf_medium", 0.0) or 0.0),
        "stress_pf_harsh": float(row_value(row, "stress_pf_harsh", 0.0) or 0.0),
        "stress_survival_score": float(row_value(row, "stress_survival_score", 0.0) or 0.0),
        "prop_fit_score": float(row_value(row, "prop_fit_score", 0.0) or 0.0),
        "prop_fit_label": str(row_value(row, "prop_fit_label", "fail") or "fail"),
        "prop_fit_reasons": tuple(str(item) for item in row_value(row, "prop_fit_reasons", ()) or ()),
        "news_window_trade_share": float(row_value(row, "news_window_trade_share", 0.0) or 0.0),
        "sub_short_hold_share": float(row_value(row, "sub_short_hold_share", 0.0) or 0.0),
        "micro_target_risk_flag": bool(row_value(row, "micro_target_risk_flag", False)),
        "execution_dependency_flag": bool(row_value(row, "execution_dependency_flag", False)),
        "interpreter_fit_score": float(row_value(row, "interpreter_fit_score", 0.0) or 0.0),
        "common_live_regime_fit": float(row_value(row, "common_live_regime_fit", 0.0) or 0.0),
        "blocked_by_interpreter_risk": float(row_value(row, "blocked_by_interpreter_risk", 0.0) or 0.0),
        "interpreter_fit_reasons": tuple(str(item) for item in row_value(row, "interpreter_fit_reasons", ()) or ()),
        "regime_specialist_viable": meets_regime_specialist_viability(row, symbol),
        "specialist_live_approved": specialist_live_approved,
        "specialist_live_rejection_reason": "; ".join(specialist_live_rejection_reasons),
    }


def execution_candidate_row_from_result(symbol: str, row: object) -> dict[str, object]:
    return execution_candidate_row(symbol, row)


def selection_component_keys(row: dict[str, object]) -> set[str]:
    candidate_name = str(row.get("candidate_name", "")).strip()
    variant_label = str(row.get("variant_label", "")).strip()
    regime_filter_label = str(row.get("regime_filter_label", "")).strip()
    strategy_family_value = str(row.get("strategy_family", "")).strip()
    direction_mode_value = str(row.get("direction_mode", "")).strip()
    if strategy_family_value:
        return {f"{strategy_family_value}|{direction_mode_value}|{variant_label}|{regime_filter_label}"}
    parts = component_names(candidate_name)
    if parts:
        return {f"{part}|{variant_label}|{regime_filter_label}" for part in parts}
    code_paths = component_set(str(row.get("code_path", "")))
    if code_paths:
        return {f"{path}|{variant_label}|{regime_filter_label}" for path in code_paths}
    return {f"{candidate_name}|{variant_label}|{regime_filter_label}"}


def _candidate_selection_score(row: dict[str, object]) -> tuple[float, ...]:
    return (
        float(row.get("equity_quality_score", 0.0)),
        float(row.get("regime_stability_score", 0.0)),
        -float(row.get("best_trade_share_pct", 100.0)),
        float(row.get("equity_new_high_share_pct", 0.0)),
        -float(row.get("regime_loss_ratio", 999.0)),
        float(row.get("validation_pnl", 0.0)) + float(row.get("test_pnl", 0.0)),
        float(row.get("test_pnl", 0.0)),
        float(row.get("validation_pnl", 0.0)),
        float(row.get("realized_pnl", 0.0)),
    )


def _regime_share_map(row: dict[str, object]) -> dict[str, float]:
    regime_trade_counts = metric_map_from_row(row, "regime_trade_count_by_label")
    if regime_trade_counts:
        total = sum(max(value, 0.0) for value in regime_trade_counts.values())
        if total > 0.0:
            return {str(label): max(value, 0.0) / total for label, value in regime_trade_counts.items() if max(value, 0.0) > 0.0}
    best_regime = str(row.get("best_regime", "") or "").strip()
    return {best_regime: 1.0} if best_regime else {}


def _pairwise_regime_overlap_score(left: dict[str, object], right: dict[str, object]) -> float:
    left_map = _regime_share_map(left)
    right_map = _regime_share_map(right)
    if not left_map or not right_map:
        return 1.0
    labels = set(left_map) | set(right_map)
    return sum(min(left_map.get(label, 0.0), right_map.get(label, 0.0)) for label in labels)


def max_regime_overlap_score(candidate: dict[str, object], selected: list[dict[str, object]]) -> float:
    if not selected:
        return 0.0
    return max(_pairwise_regime_overlap_score(candidate, row) for row in selected)


def _specialist_has_low_regime_overlap(candidate: dict[str, object], selected: list[dict[str, object]], max_overlap: float = 0.25) -> bool:
    if not selected:
        return True
    candidate_best_regime = str(candidate.get("best_regime", "") or "").strip()
    if candidate_best_regime and any(candidate_best_regime == str(row.get("best_regime", "") or "").strip() for row in selected):
        return False
    return max_regime_overlap_score(candidate, selected) <= max_overlap


def regime_overlap_diagnostics(candidate_set: list[dict[str, object]]) -> tuple[float, list[str]]:
    if len(candidate_set) < 2:
        return 0.0, []
    max_overlap = 0.0
    diagnostics: list[str] = []
    for index, left in enumerate(candidate_set):
        for right in candidate_set[index + 1 :]:
            overlap = _pairwise_regime_overlap_score(left, right)
            max_overlap = max(max_overlap, overlap)
            diagnostics.append(
                f"{left.get('candidate_name', 'unknown')} vs {right.get('candidate_name', 'unknown')}={overlap:.2f}"
            )
    return max_overlap, diagnostics


def _regime_overlap_conflict(candidate: dict[str, object], selected: list[dict[str, object]]) -> tuple[float, str]:
    if not selected:
        return 0.0, ""
    best_overlap = -1.0
    best_name = ""
    for row in selected:
        overlap = _pairwise_regime_overlap_score(candidate, row)
        if overlap > best_overlap:
            best_overlap = overlap
            best_name = str(row.get("candidate_name", "") or "")
    return max(best_overlap, 0.0), best_name


def candidate_selection_score(row: dict[str, object]) -> tuple[float, ...]:
    return _candidate_selection_score(row)


def specialist_has_low_regime_overlap(
    candidate: dict[str, object],
    selected: list[dict[str, object]],
    max_overlap: float = 0.25,
) -> bool:
    return _specialist_has_low_regime_overlap(candidate, selected, max_overlap=max_overlap)


def specialist_regime_overlap_rejections(rows: list[dict[str, object]], selected: list[dict[str, object]], *, max_overlap: float = 0.25) -> list[str]:
    if not selected:
        return []
    selected_names = {str(row.get("candidate_name", "") or "") for row in selected}
    reasons: list[str] = []
    for row in rows:
        if str(row.get("candidate_name", "") or "") in selected_names:
            continue
        if not bool(row.get("regime_specialist_viable")):
            continue
        if meets_viability(row, str(row.get("symbol", ""))):
            continue
        candidate_best_regime = str(row.get("best_regime", "") or "").strip()
        conflicting_regime_match = next(
            (
                str(selected_row.get("candidate_name", "") or "")
                for selected_row in selected
                if candidate_best_regime and candidate_best_regime == str(selected_row.get("best_regime", "") or "").strip()
            ),
            "",
        )
        overlap, overlap_name = _regime_overlap_conflict(row, selected)
        if conflicting_regime_match:
            reasons.append(
                f"{row.get('candidate_name', 'unknown')} rejected_due_to_regime_overlap same_best_regime={candidate_best_regime} conflicts_with={conflicting_regime_match}"
            )
        elif overlap > max_overlap:
            reasons.append(
                f"{row.get('candidate_name', 'unknown')} rejected_due_to_regime_overlap overlap={overlap:.2f} threshold={max_overlap:.2f} conflicts_with={overlap_name or 'unknown'}"
            )
    return reasons


def is_valid_execution_combo(combo: tuple[dict[str, object], ...], symbol: str, max_candidates: int = 3) -> bool:
    used_components: set[str] = set()
    used_signatures: set[tuple[str, str, str]] = set()
    used_code_paths: set[str] = set()
    used_regimes: set[str] = set()
    used_families: dict[str, set[str]] = {}
    allow_multi_core = symbol_is_forex(symbol) or symbol_is_crypto(symbol) or symbol_is_metal(symbol)
    specialist_count = 0
    core_count = 0
    accepted_rows: list[dict[str, object]] = []
    for row in combo:
        components = selection_component_keys(row)
        if components & used_components:
            return False
        used_components.update(components)
        code_path = str(row.get("code_path", "") or "").strip()
        variant_label = str(row.get("variant_label", "") or "").strip()
        best_regime = str(row.get("best_regime", "") or "").strip()
        signature = (code_path, variant_label, best_regime)
        if signature in used_signatures:
            return False
        used_signatures.add(signature)
        if code_path and code_path in used_code_paths:
            return False
        if code_path:
            used_code_paths.add(code_path)
        if best_regime:
            if best_regime in used_regimes:
                return False
            used_regimes.add(best_regime)
        family = str(row.get("strategy_family", "") or "").strip()
        direction_mode_value = str(row.get("direction_mode", "") or "").strip()
        if family:
            directions = used_families.setdefault(family, set())
            if direction_mode_value == "both" and directions:
                return False
            if "both" in directions:
                return False
            if direction_mode_value in directions:
                return False
            directions.add(direction_mode_value)
        is_specialist = str(row.get("promotion_tier", "reject")) == "specialist" or (
            bool(row.get("regime_specialist_viable")) and not meets_viability(row, str(row.get("symbol", "")))
        )
        max_allowed_overlap = 0.25 if is_specialist else 0.60
        if accepted_rows and max_regime_overlap_score(row, accepted_rows) > max_allowed_overlap:
            return False
        accepted_rows.append(row)
        tier = str(row.get("promotion_tier", "reject"))
        if tier == "specialist":
            specialist_count += 1
        if tier == "core":
            core_count += 1
    specialist_limit = max(1, max_candidates) if allow_multi_core else 1
    if specialist_count > specialist_limit:
        return False
    if core_count == 0 and any(str(row.get("promotion_tier", "")) == "core" for row in combo):
        return False
    if not allow_multi_core and len(combo) > 1:
        return False
    return True


def build_execution_candidate_sets(rows: list[dict[str, object]], symbol: str, max_candidates: int = 3) -> list[tuple[str, list[dict[str, object]]]]:
    candidate_sets: list[tuple[str, list[dict[str, object]]]] = []
    seen_names: set[tuple[str, ...]] = set()

    def _append_set(label: str, candidate_set: list[dict[str, object]]) -> None:
        if not candidate_set:
            return
        key = tuple(sorted(str(row.get("candidate_name", "")) for row in candidate_set))
        if key in seen_names:
            return
        seen_names.add(key)
        candidate_sets.append((label, candidate_set))

    standard_candidates = select_execution_candidates(rows, max_candidates=max_candidates)
    _append_set("standard", standard_candidates)

    sparse_candidates = select_sparse_execution_candidates(rows, symbol, max_candidates=max_candidates)
    _append_set("sparse", sparse_candidates)

    rows_by_family: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        family = str(row.get("strategy_family", "") or "").strip()
        if family:
            rows_by_family.setdefault(family, []).append(row)
    for family, family_rows in rows_by_family.items():
        sorted_family_rows = sorted(family_rows, key=_candidate_selection_score, reverse=True)
        best_long = next((row for row in sorted_family_rows if str(row.get("direction_mode", "")) == "long_only"), None)
        best_short = next((row for row in sorted_family_rows if str(row.get("direction_mode", "")) == "short_only"), None)
        if best_long is not None and best_short is not None:
            _append_set(f"family_both_{family}", [best_long, best_short])

    pool = sorted(
        [row for row in rows if str(row.get("promotion_tier", "reject")) in {"core", "specialist"}],
        key=_candidate_selection_score,
        reverse=True,
    )[:6]
    for size in range(1, min(max_candidates, len(pool)) + 1):
        for combo in itertools.combinations(pool, size):
            if not is_valid_execution_combo(combo, symbol, max_candidates=max_candidates):
                continue
            _append_set(f"combo_{size}", list(combo))
    return candidate_sets


def select_execution_candidates(rows: list[dict[str, object]], max_candidates: int = 3) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    used_components: set[str] = set()
    used_code_paths: set[str] = set()
    used_variant_regimes: set[tuple[str, str, str]] = set()
    used_families: set[str] = set()
    viable_rows = [row for row in rows if meets_viability(row, str(row.get("symbol", "")))]
    specialist_rows = [row for row in rows if bool(row.get("regime_specialist_viable")) and not meets_viability(row, str(row.get("symbol", "")))]
    ranked = sorted(
        viable_rows,
        key=lambda row: (
            bool(row.get("recommended")),
            float(row.get("regime_stability_score", 0.0)),
            -float(row.get("regime_loss_ratio", 999.0)),
            float(row.get("combo_outperformance_score", 0.0)),
            max(float(row.get("walk_forward_pass_rate_pct", 0.0)), float(row.get("walk_forward_soft_pass_rate_pct", 0.0))),
            float(row.get("walk_forward_avg_test_pnl", 0.0)),
            float(row.get("test_pnl", 0.0)),
            float(row.get("validation_pnl", 0.0)),
            float(row.get("test_profit_factor", 0.0)),
            int(row.get("test_closed_trades", 0)),
        ),
        reverse=True,
    )
    specialist_ranked = sorted(
        specialist_rows,
        key=lambda row: (
            float(row.get("best_regime_pnl", 0.0)),
            float(row.get("regime_stability_score", 0.0)),
            -float(row.get("regime_loss_ratio", 999.0)),
            int(metric_map_from_row(row, "regime_trade_count_by_label").get(str(row.get("best_regime", "") or ""), 0.0)),
            float(row.get("test_pnl", 0.0)),
            float(row.get("validation_pnl", 0.0)),
        ),
        reverse=True,
    )
    if ranked:
        lead = ranked[0]
        selected.append(lead)
        used_components.update(selection_component_keys(lead))
        if str(lead.get("strategy_family", "") or "").strip():
            used_families.add(str(lead.get("strategy_family", "") or "").strip())
        lead_code_path = str(lead.get("code_path", "") or "").strip()
        if lead_code_path:
            used_code_paths.add(lead_code_path)
        used_variant_regimes.add((lead_code_path, str(lead.get("variant_label", "") or "").strip(), str(lead.get("best_regime", "") or "").strip()))
    if selected and len(selected) < max_candidates:
        lead_regime = str(selected[0].get("best_regime", "") or "")
        for row in specialist_ranked:
            if len(selected) >= max_candidates:
                break
            components = selection_component_keys(row)
            if components & used_components:
                continue
            if not family_unused_for_single_selection(row, used_families):
                continue
            candidate_code_path = str(row.get("code_path", "") or "").strip()
            candidate_signature = (candidate_code_path, str(row.get("variant_label", "") or "").strip(), str(row.get("best_regime", "") or "").strip())
            if candidate_signature in used_variant_regimes:
                continue
            if candidate_code_path and candidate_code_path in used_code_paths:
                continue
            if lead_regime and str(row.get("best_regime", "") or "") == lead_regime:
                continue
            if not _specialist_has_low_regime_overlap(row, selected):
                continue
            selected.append(row)
            used_components.update(components)
            if str(row.get("strategy_family", "") or "").strip():
                used_families.add(str(row.get("strategy_family", "") or "").strip())
            if candidate_code_path:
                used_code_paths.add(candidate_code_path)
            used_variant_regimes.add(candidate_signature)
    fallback_ranked = [row for row in ranked[1:] if row not in selected] + [row for row in specialist_ranked if row not in selected]
    for row in fallback_ranked:
        components = selection_component_keys(row)
        if selected and components & used_components:
            continue
        if not family_unused_for_single_selection(row, used_families):
            continue
        if bool(row.get("regime_specialist_viable")) and not meets_viability(row, str(row.get("symbol", ""))) and not _specialist_has_low_regime_overlap(row, selected):
            continue
        candidate_code_path = str(row.get("code_path", "") or "").strip()
        candidate_signature = (candidate_code_path, str(row.get("variant_label", "") or "").strip(), str(row.get("best_regime", "") or "").strip())
        if candidate_signature in used_variant_regimes:
            continue
        if candidate_code_path and candidate_code_path in used_code_paths and selected:
            continue
        selected.append(row)
        used_components.update(components)
        if str(row.get("strategy_family", "") or "").strip():
            used_families.add(str(row.get("strategy_family", "") or "").strip())
        if candidate_code_path:
            used_code_paths.add(candidate_code_path)
        used_variant_regimes.add(candidate_signature)
        if len(selected) >= max_candidates:
            break
    return selected


def select_sparse_execution_candidates(rows: list[dict[str, object]], symbol: str, max_candidates: int = 3) -> list[dict[str, object]]:
    thresholds = research_thresholds(symbol)
    selected: list[dict[str, object]] = []
    used_components: set[str] = set()
    used_variants: set[str] = set()
    used_families: set[str] = set()
    sparse_rows = [
        row
        for row in rows
        if bool(row.get("sparse_strategy"))
        and float(row.get("realized_pnl", 0.0)) > 0.0
        and float(row.get("profit_factor", 0.0)) >= float(thresholds["min_profit_factor"])
        and (float(row.get("validation_pnl", 0.0)) + float(row.get("test_pnl", 0.0))) > 0.0
        and (int(row.get("validation_closed_trades", 0)) + int(row.get("test_closed_trades", 0))) > 0
        and (meets_viability(row, symbol) or bool(row.get("regime_specialist_viable")))
    ]
    ranked = sorted(
        sparse_rows,
        key=lambda row: (
            float(row.get("validation_pnl", 0.0)) + float(row.get("test_pnl", 0.0)),
            int(row.get("validation_closed_trades", 0)) + int(row.get("test_closed_trades", 0)),
            max(float(row.get("walk_forward_pass_rate_pct", 0.0)), float(row.get("walk_forward_soft_pass_rate_pct", 0.0))),
            float(row.get("test_pnl", 0.0)),
            float(row.get("validation_pnl", 0.0)),
            float(row.get("realized_pnl", 0.0)),
        ),
        reverse=True,
    )
    while len(selected) < max_candidates:
        current_validation_pnl = sum(float(item.get("validation_pnl", 0.0)) for item in selected)
        current_test_pnl = sum(float(item.get("test_pnl", 0.0)) for item in selected)
        best_row: dict[str, object] | None = None
        best_score: tuple[float, ...] | None = None
        for row in ranked:
            if row in selected:
                continue
            components = selection_component_keys(row)
            if selected and components & used_components:
                continue
            if not family_unused_for_single_selection(row, used_families):
                continue
            variant_label = str(row.get("variant_label", "")).strip()
            if selected and variant_label and variant_label in used_variants:
                continue
            validation_closed = int(row.get("validation_closed_trades", 0))
            test_closed = int(row.get("test_closed_trades", 0))
            validation_pnl = float(row.get("validation_pnl", 0.0))
            test_pnl = float(row.get("test_pnl", 0.0))
            coverage_gain = 0
            if current_validation_pnl <= 0.0 and validation_closed > 0 and validation_pnl > 0.0:
                coverage_gain += 1
            if current_test_pnl <= 0.0 and test_closed > 0 and test_pnl > 0.0:
                coverage_gain += 1
            score = (
                float(coverage_gain),
                float(validation_pnl > 0.0 and test_pnl > 0.0),
                validation_pnl + test_pnl,
                test_pnl,
                validation_pnl,
                float(row.get("realized_pnl", 0.0)),
            )
            if best_score is None or score > best_score:
                best_score = score
                best_row = row
        if best_row is None:
            break
        selected.append(best_row)
        used_components.update(selection_component_keys(best_row))
        if str(best_row.get("strategy_family", "") or "").strip():
            used_families.add(str(best_row.get("strategy_family", "") or "").strip())
        variant_label = str(best_row.get("variant_label", "")).strip()
        if variant_label:
            used_variants.add(variant_label)
        combined_validation_closed = sum(int(item.get("validation_closed_trades", 0)) for item in selected)
        combined_test_closed = sum(int(item.get("test_closed_trades", 0)) for item in selected)
        combined_validation_pnl = sum(float(item.get("validation_pnl", 0.0)) for item in selected)
        combined_test_pnl = sum(float(item.get("test_pnl", 0.0)) for item in selected)
        combined_closed = combined_validation_closed + combined_test_closed
        combined_pnl = sum(float(item.get("validation_pnl", 0.0)) + float(item.get("test_pnl", 0.0)) for item in selected)
        if (
            combined_closed >= int(thresholds["sparse_combined_closed_trades"])
            and combined_pnl > 0.0
            and combined_validation_closed > 0
            and combined_test_closed > 0
            and combined_validation_pnl > 0.0
            and combined_test_pnl > 0.0
        ):
            break
    combined_closed = sum(int(item.get("validation_closed_trades", 0)) + int(item.get("test_closed_trades", 0)) for item in selected)
    combined_validation_closed = sum(int(item.get("validation_closed_trades", 0)) for item in selected)
    combined_test_closed = sum(int(item.get("test_closed_trades", 0)) for item in selected)
    combined_validation_pnl = sum(float(item.get("validation_pnl", 0.0)) for item in selected)
    combined_test_pnl = sum(float(item.get("test_pnl", 0.0)) for item in selected)
    combined_pnl = sum(float(item.get("validation_pnl", 0.0)) + float(item.get("test_pnl", 0.0)) for item in selected)
    if (
        combined_closed < int(thresholds["sparse_combined_closed_trades"])
        or combined_pnl <= 0.0
        or combined_validation_closed <= 0
        or combined_test_closed <= 0
        or combined_validation_pnl <= 0.0
        or combined_test_pnl <= 0.0
    ):
        return []
    return selected
