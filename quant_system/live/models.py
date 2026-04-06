from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DeploymentStrategy:
    candidate_name: str
    code_path: str
    variant_label: str = ""
    regime_filter_label: str = ""
    execution_overrides: dict[str, float | int] = field(default_factory=dict)
    allocation_weight: float = 1.0


@dataclass(slots=True)
class SymbolDeployment:
    profile_name: str
    symbol: str
    data_symbol: str
    broker_symbol: str
    research_run_id: int
    execution_set_id: int | None
    execution_validation_summary: str
    strategies: list[DeploymentStrategy] = field(default_factory=list)
