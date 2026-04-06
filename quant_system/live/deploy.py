from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from quant_system.live.models import DeploymentStrategy, SymbolDeployment


DEPLOY_DIR = Path("artifacts") / "deploy"


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def build_symbol_deployment(
    *,
    profile_name: str,
    symbol: str,
    data_symbol: str,
    broker_symbol: str,
    research_run_id: int,
    execution_set_id: int | None,
    execution_validation_summary: str,
    selected_candidates: list[dict[str, object]],
) -> SymbolDeployment:
    strategy_count = max(len(selected_candidates), 1)
    weight = 1.0 / strategy_count
    strategies = [
        DeploymentStrategy(
            candidate_name=str(row["candidate_name"]),
            code_path=str(row["code_path"]),
            variant_label=str(row.get("variant_label", "") or ""),
            regime_filter_label=str(row.get("regime_filter_label", "") or ""),
            execution_overrides=dict(row.get("execution_overrides", {}) or {}),
            allocation_weight=weight,
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
        strategies=strategies,
    )


def export_symbol_deployment(deployment: SymbolDeployment) -> Path:
    DEPLOY_DIR.mkdir(parents=True, exist_ok=True)
    path = DEPLOY_DIR / f"{_slug(deployment.symbol)}.live.json"
    path.write_text(json.dumps(asdict(deployment), indent=2), encoding="utf-8")
    return path


def load_symbol_deployment(path: Path) -> SymbolDeployment:
    payload = json.loads(path.read_text(encoding="utf-8"))
    strategies = [DeploymentStrategy(**row) for row in payload.pop("strategies", [])]
    return SymbolDeployment(strategies=strategies, **payload)


def deployment_path_for_symbol(symbol: str) -> Path:
    return DEPLOY_DIR / f"{_slug(symbol)}.live.json"
