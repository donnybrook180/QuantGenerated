from __future__ import annotations

from dataclasses import dataclass, field

@dataclass(slots=True)
class DeploymentStrategy:
    candidate_name: str
    code_path: str
    promotion_tier: str = "core"
    policy_summary: str = ""
    variant_label: str = ""
    regime_filter_label: str = ""
    execution_overrides: dict[str, float | int] = field(default_factory=dict)
    allocation_weight: float = 1.0
    allowed_regimes: tuple[str, ...] = ()
    blocked_regimes: tuple[str, ...] = ()
    min_vol_percentile: float = 0.0
    max_vol_percentile: float = 1.0
    base_allocation_weight: float = 1.0
    max_risk_multiplier: float = 1.0
    min_risk_multiplier: float = 0.0


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
    target_volatility: float = 0.0
    max_symbol_vol_percentile: float = 0.98
    block_new_entries_in_event_risk: bool = True
