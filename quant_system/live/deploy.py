from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from quant_system.artifacts import DEPLOY_DIR, deployment_path, resolve_deployment_path
from quant_system.live.models import DeploymentStrategy, SymbolDeployment


def _top_reason_list(rows: list[dict[str, object]], labels: set[str], *, limit: int = 5) -> tuple[str, ...]:
    counts: dict[str, int] = {}
    for row in rows:
        if str(row.get("prop_viability_label", "fail") or "fail") not in labels:
            continue
        for reason in row.get("prop_viability_reasons", ()) or ():
            normalized = str(reason).strip()
            if not normalized:
                continue
            counts[normalized] = counts.get(normalized, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return tuple(reason for reason, _count in ranked[:limit])


def build_symbol_deployment(
    *,
    profile_name: str,
    symbol: str,
    data_symbol: str,
    broker_symbol: str,
    research_run_id: int,
    execution_set_id: int | None,
    execution_validation_summary: str,
    symbol_status: str,
    selected_candidates: list[dict[str, object]],
    venue_key: str = "generic",
) -> SymbolDeployment:
    strategy_labels = [str(row.get("prop_viability_label", "fail") or "fail") for row in selected_candidates]
    strategy_reasons = [
        str(reason)
        for row in selected_candidates
        for reason in (row.get("prop_viability_reasons", ()) or ())
        if str(reason)
    ]
    strategy_prop_fit_labels = [str(row.get("prop_fit_label", "fail") or "fail") for row in selected_candidates]
    strategy_prop_fit_reasons = [
        str(reason)
        for row in selected_candidates
        for reason in (row.get("prop_fit_reasons", ()) or ())
        if str(reason)
    ]
    strategy_stress_scores = [float(row.get("stress_survival_score", 0.0) or 0.0) for row in selected_candidates]
    strategy_interpreter_reasons = [
        str(reason)
        for row in selected_candidates
        for reason in (row.get("interpreter_fit_reasons", ()) or ())
        if str(reason)
    ]
    strategy_interpreter_scores = [float(row.get("interpreter_fit_score", 0.0) or 0.0) for row in selected_candidates]
    if any(label == "pass" for label in strategy_labels):
        prop_viability_label = "pass"
    elif any(label == "caution" for label in strategy_labels):
        prop_viability_label = "caution"
    else:
        prop_viability_label = "fail"
    if any(label == "pass" for label in strategy_prop_fit_labels):
        prop_fit_label = "pass"
    elif any(label == "caution" for label in strategy_prop_fit_labels):
        prop_fit_label = "caution"
    else:
        prop_fit_label = "fail"
    if not strategy_reasons and not selected_candidates:
        strategy_reasons = ["no_selected_candidates"]
    if not strategy_prop_fit_reasons and not selected_candidates:
        strategy_prop_fit_reasons = ["no_selected_candidates"]
    strategies = [
        DeploymentStrategy(
            candidate_name=str(row["candidate_name"]),
            code_path=str(row["code_path"]),
            strategy_family=str(row.get("strategy_family", "") or ""),
            direction_mode=str(row.get("direction_mode", "") or ""),
            direction_role=str(row.get("direction_role", "") or ""),
            promotion_tier=str(row.get("promotion_tier", "core") or "core"),
            specialist_live_approved=bool(row.get("specialist_live_approved", False)),
            specialist_live_rejection_reason=str(row.get("specialist_live_rejection_reason", "") or ""),
            policy_summary=str(row.get("policy_summary", "") or ""),
            variant_label=str(row.get("variant_label", "") or ""),
            regime_filter_label=str(row.get("regime_filter_label", "") or ""),
            execution_overrides=dict(row.get("execution_overrides", {}) or {}),
            allocation_weight=1.0,
            allowed_regimes=tuple(str(item) for item in row.get("allowed_regimes", ()) or ()),
            blocked_regimes=tuple(str(item) for item in row.get("blocked_regimes", ()) or ()),
            min_vol_percentile=float(row.get("min_vol_percentile", 0.0) or 0.0),
            max_vol_percentile=float(row.get("max_vol_percentile", 1.0) or 1.0),
            base_allocation_weight=float(row.get("base_allocation_weight", 1.0) or 1.0),
            max_risk_multiplier=float(row.get("max_risk_multiplier", 1.0) or 1.0),
            min_risk_multiplier=float(row.get("min_risk_multiplier", 0.0) or 0.0),
            signal_quality_score=float(row.get("signal_quality_score", 0.0) or 0.0),
            prop_viability_score=float(row.get("prop_viability_score", 0.0) or 0.0),
            prop_viability_label=str(row.get("prop_viability_label", "fail") or "fail"),
            prop_viability_pass=bool(row.get("prop_viability_pass", False)),
            prop_viability_reasons=tuple(str(item) for item in row.get("prop_viability_reasons", ()) or ()),
            stress_expectancy_mild=float(row.get("stress_expectancy_mild", 0.0) or 0.0),
            stress_expectancy_medium=float(row.get("stress_expectancy_medium", 0.0) or 0.0),
            stress_expectancy_harsh=float(row.get("stress_expectancy_harsh", 0.0) or 0.0),
            stress_pf_mild=float(row.get("stress_pf_mild", 0.0) or 0.0),
            stress_pf_medium=float(row.get("stress_pf_medium", 0.0) or 0.0),
            stress_pf_harsh=float(row.get("stress_pf_harsh", 0.0) or 0.0),
            stress_survival_score=float(row.get("stress_survival_score", 0.0) or 0.0),
            prop_fit_score=float(row.get("prop_fit_score", 0.0) or 0.0),
            prop_fit_label=str(row.get("prop_fit_label", "fail") or "fail"),
            prop_fit_reasons=tuple(str(item) for item in row.get("prop_fit_reasons", ()) or ()),
            news_window_trade_share=float(row.get("news_window_trade_share", 0.0) or 0.0),
            sub_short_hold_share=float(row.get("sub_short_hold_share", 0.0) or 0.0),
            micro_target_risk_flag=bool(row.get("micro_target_risk_flag", False)),
            execution_dependency_flag=bool(row.get("execution_dependency_flag", False)),
            interpreter_fit_score=float(row.get("interpreter_fit_score", 0.0) or 0.0),
            common_live_regime_fit=float(row.get("common_live_regime_fit", 0.0) or 0.0),
            blocked_by_interpreter_risk=float(row.get("blocked_by_interpreter_risk", 0.0) or 0.0),
            interpreter_fit_reasons=tuple(str(item) for item in row.get("interpreter_fit_reasons", ()) or ()),
        )
        for row in selected_candidates
    ]
    return SymbolDeployment(
        profile_name=profile_name,
        symbol=symbol,
        data_symbol=data_symbol,
        broker_symbol=broker_symbol,
        research_run_id=research_run_id,
        execution_set_id=execution_set_id,
        execution_validation_summary=execution_validation_summary,
        symbol_status=symbol_status,
        strategies=strategies,
        venue_key=venue_key,
        venue_basis=f"{venue_key}_mt5",
        prop_viability_label=prop_viability_label,
        prop_viability_reasons=tuple(strategy_reasons),
        top_caution_reasons=_top_reason_list(selected_candidates, {"caution"}),
        top_rejection_reasons=_top_reason_list(selected_candidates, {"fail"}),
        stress_survival_score=max(strategy_stress_scores) if strategy_stress_scores else 0.0,
        prop_fit_label=prop_fit_label,
        prop_fit_reasons=tuple(strategy_prop_fit_reasons),
        interpreter_fit_score=max(strategy_interpreter_scores) if strategy_interpreter_scores else 0.0,
        interpreter_fit_reasons=tuple(strategy_interpreter_reasons),
        target_volatility=0.0,
        max_symbol_vol_percentile=0.98,
        block_new_entries_in_event_risk=True,
    )


def export_symbol_deployment(deployment: SymbolDeployment) -> Path:
    path = deployment_path(deployment.symbol, deployment.venue_key)
    path.write_text(json.dumps(asdict(deployment), indent=2), encoding="utf-8")
    return path


def load_symbol_deployment(path: Path) -> SymbolDeployment:
    payload = json.loads(path.read_text(encoding="utf-8"))
    strategies = [DeploymentStrategy(**row) for row in payload.pop("strategies", [])]
    execution_validation = str(payload.get("execution_validation_summary", "") or "")
    stored_status = str(payload.get("symbol_status", "") or "")
    inferred_status = "research_only"
    if strategies:
        specialist_only = {strategy.promotion_tier for strategy in strategies} <= {"specialist"}
        approved_specialists = [strategy for strategy in strategies if strategy.promotion_tier == "specialist" and strategy.specialist_live_approved]
        if "accepted_with_reduced_risk" in execution_validation:
            if any(strategy.promotion_tier == "core" for strategy in strategies) or approved_specialists:
                inferred_status = "reduced_risk_only"
        elif specialist_only and approved_specialists:
            inferred_status = "reduced_risk_only"
        elif any(strategy.promotion_tier == "core" for strategy in strategies):
            inferred_status = "live_ready"
    if not stored_status or (stored_status == "research_only" and strategies):
        payload["symbol_status"] = inferred_status
    return SymbolDeployment(strategies=strategies, **payload)


def deployment_path_for_symbol(symbol: str, venue_key: str = "generic") -> Path:
    return resolve_deployment_path(symbol, venue_key)
