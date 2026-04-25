from __future__ import annotations

from dataclasses import dataclass, field

@dataclass(slots=True)
class DeploymentStrategy:
    candidate_name: str
    code_path: str
    strategy_family: str = ""
    direction_mode: str = ""
    direction_role: str = ""
    promotion_tier: str = "core"
    specialist_live_approved: bool = False
    specialist_live_rejection_reason: str = ""
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
    signal_quality_score: float = 0.0
    prop_viability_score: float = 0.0
    prop_viability_label: str = "fail"
    prop_viability_pass: bool = False
    prop_viability_reasons: tuple[str, ...] = ()
    stress_expectancy_mild: float = 0.0
    stress_expectancy_medium: float = 0.0
    stress_expectancy_harsh: float = 0.0
    stress_pf_mild: float = 0.0
    stress_pf_medium: float = 0.0
    stress_pf_harsh: float = 0.0
    stress_survival_score: float = 0.0
    prop_fit_score: float = 0.0
    prop_fit_label: str = "fail"
    prop_fit_reasons: tuple[str, ...] = ()
    news_window_trade_share: float = 0.0
    sub_short_hold_share: float = 0.0
    micro_target_risk_flag: bool = False
    execution_dependency_flag: bool = False
    interpreter_fit_score: float = 0.0
    common_live_regime_fit: float = 0.0
    blocked_by_interpreter_risk: float = 0.0
    interpreter_fit_reasons: tuple[str, ...] = ()


@dataclass(slots=True)
class SymbolDeployment:
    profile_name: str
    symbol: str
    data_symbol: str
    broker_symbol: str
    research_run_id: int
    execution_set_id: int | None
    execution_validation_summary: str
    symbol_status: str = "research_only"
    strategies: list[DeploymentStrategy] = field(default_factory=list)
    venue_key: str = "generic"
    venue_basis: str = "generic_mt5"
    prop_viability_label: str = "fail"
    prop_viability_reasons: tuple[str, ...] = ()
    top_caution_reasons: tuple[str, ...] = ()
    top_rejection_reasons: tuple[str, ...] = ()
    stress_survival_score: float = 0.0
    prop_fit_label: str = "fail"
    prop_fit_reasons: tuple[str, ...] = ()
    interpreter_fit_score: float = 0.0
    interpreter_fit_reasons: tuple[str, ...] = ()
    target_volatility: float = 0.0
    max_symbol_vol_percentile: float = 0.98
    block_new_entries_in_event_risk: bool = True
