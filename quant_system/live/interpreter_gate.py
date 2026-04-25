from __future__ import annotations

from quant_system.live.models import DeploymentStrategy, SymbolDeployment
from quant_system.models import Side
from quant_system.regime import RegimeSnapshot, map_regime_label_to_unified, regime_allows_strategy


def candidate_archetype(strategy: DeploymentStrategy) -> str:
    name = strategy.candidate_name.lower()
    if "reclaim" in name:
        return "reclaim"
    if "reversion" in name:
        return "mean_reversion"
    if "breakout" in name:
        return "breakout"
    if "pullback" in name or "trend" in name:
        return "trend_pullback"
    return "unknown"


def is_strategy_regime_blocked(
    deployment: SymbolDeployment,
    strategy: DeploymentStrategy,
    snapshot: RegimeSnapshot,
    *,
    relax_for_mini_trades: bool = False,
) -> bool:
    if relax_for_mini_trades:
        return bool(int(strategy.execution_overrides.get("tca_block_new_entries", 0) or 0))
    return (
        bool(int(strategy.execution_overrides.get("tca_block_new_entries", 0) or 0))
        or (deployment.block_new_entries_in_event_risk and snapshot.regime_label == "event_risk")
        or snapshot.block_new_entries
        or snapshot.vol_percentile > deployment.max_symbol_vol_percentile
        or not regime_allows_strategy(
            snapshot,
            allowed_regimes=strategy.allowed_regimes,
            blocked_regimes=strategy.blocked_regimes,
            min_vol_percentile=strategy.min_vol_percentile,
            max_vol_percentile=strategy.max_vol_percentile,
        )
    )


def interpreter_block_reason(strategy: DeploymentStrategy, interpreter_state, *, relax_for_mini_trades: bool = False) -> str:
    if relax_for_mini_trades:
        return ""
    if interpreter_state is None:
        return ""
    archetype = candidate_archetype(strategy)
    blocked = set(interpreter_state.blocked_archetypes or [])
    allowed = set(interpreter_state.allowed_archetypes or [])
    if interpreter_state.risk_posture == "defensive" and not allowed:
        return f"interpreter_defensive::{interpreter_state.no_trade_reason or interpreter_state.session_regime}"
    if archetype != "unknown" and archetype in blocked:
        return f"interpreter_blocked::{archetype}"
    if allowed and archetype != "unknown" and archetype not in allowed:
        return f"interpreter_not_allowed::{archetype}"
    return ""


def effective_risk_multiplier(snapshot: RegimeSnapshot, strategy: DeploymentStrategy) -> float:
    multiplier = snapshot.risk_multiplier
    if multiplier < strategy.min_risk_multiplier:
        multiplier = strategy.min_risk_multiplier
    if multiplier > strategy.max_risk_multiplier:
        multiplier = strategy.max_risk_multiplier
    return multiplier


def allocator_score(strategy: DeploymentStrategy, signal_side, confidence: float, snapshot: RegimeSnapshot) -> float:
    if signal_side == Side.FLAT:
        return 0.0
    unified_regime = map_regime_label_to_unified(snapshot.regime_label, snapshot.volatility_label, snapshot.structure_label)
    raw = confidence * max(effective_risk_multiplier(snapshot, strategy), 0.0) * max(strategy.base_allocation_weight, 0.0)
    if strategy.allowed_regimes and (snapshot.regime_label in strategy.allowed_regimes or unified_regime in strategy.allowed_regimes):
        raw *= 1.15
    if strategy.regime_filter_label and strategy.regime_filter_label in {snapshot.regime_label, unified_regime}:
        raw *= 1.10
    return max(raw, 0.0)
