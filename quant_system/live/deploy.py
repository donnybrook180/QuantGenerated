from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from quant_system.artifacts import DEPLOY_DIR, deploy_symbol_dir
from quant_system.live.models import DeploymentStrategy, SymbolDeployment


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
) -> SymbolDeployment:
    strategies = [
        DeploymentStrategy(
            candidate_name=str(row["candidate_name"]),
            code_path=str(row["code_path"]),
            promotion_tier=str(row.get("promotion_tier", "core") or "core"),
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
        target_volatility=0.0,
        max_symbol_vol_percentile=0.98,
        block_new_entries_in_event_risk=True,
    )


def export_symbol_deployment(deployment: SymbolDeployment) -> Path:
    path = deploy_symbol_dir(deployment.symbol) / "live.json"
    path.write_text(json.dumps(asdict(deployment), indent=2), encoding="utf-8")
    return path


def load_symbol_deployment(path: Path) -> SymbolDeployment:
    payload = json.loads(path.read_text(encoding="utf-8"))
    strategies = [DeploymentStrategy(**row) for row in payload.pop("strategies", [])]
    execution_validation = str(payload.get("execution_validation_summary", "") or "")
    stored_status = str(payload.get("symbol_status", "") or "")
    inferred_status = "research_only"
    if strategies:
        if "accepted_with_reduced_risk" in execution_validation or {strategy.promotion_tier for strategy in strategies} <= {"specialist"}:
            inferred_status = "reduced_risk_only"
        else:
            inferred_status = "live_ready"
    if not stored_status or (stored_status == "research_only" and strategies):
        payload["symbol_status"] = inferred_status
    return SymbolDeployment(strategies=strategies, **payload)


def deployment_path_for_symbol(symbol: str) -> Path:
    return deploy_symbol_dir(symbol) / "live.json"
