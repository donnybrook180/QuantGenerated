from __future__ import annotations

from datetime import UTC, datetime

from quant_system.artifacts import list_deployment_paths
from quant_system.config import SystemConfig
from quant_system.interpreter.engines import (
    build_explanation,
    build_feature_snapshot,
    classify_execution_regime,
    classify_macro_regime,
    classify_session_regime,
    classify_structure_regime,
    classify_volatility_regime,
    derive_allowed_archetypes,
    derive_directional_bias,
    derive_risk_posture,
    score_execution_quality,
    score_setup_quality,
)
from quant_system.interpreter.features import build_feature_context
from quant_system.interpreter.models import InterpreterState
from quant_system.live.deploy import load_symbol_deployment
from quant_system.live.models import SymbolDeployment
from quant_system.regime import classify_regime, map_regime_label_to_unified
from quant_system.venues import normalize_venue_key


def build_market_interpreter_state(deployment: SymbolDeployment, config: SystemConfig | None = None) -> InterpreterState:
    config = config or SystemConfig()
    context = build_feature_context(config, deployment)
    generated_at = datetime.now(UTC)
    if context is None:
        return InterpreterState(
            symbol=deployment.symbol,
            broker_symbol=deployment.broker_symbol,
            venue_key=deployment.venue_key,
            generated_at=generated_at,
            legacy_regime_label="unknown",
            unified_regime_label="unknown",
            macro_regime="unknown",
            session_regime="unknown",
            structure_regime="unknown",
            volatility_regime="unknown",
            execution_regime="unknown",
            crowding_regime="neutral",
            directional_bias="neutral",
            setup_quality=0.0,
            execution_quality=0.0,
            confidence=0.0,
            risk_posture="defensive",
            blocked_archetypes=["breakout", "trend_pullback", "mean_reversion", "reclaim"],
            no_trade_reason="insufficient_market_data",
            explanation="No recent cached bars available for the interpreter.",
            feature_snapshot=None,
        )
    values = context.feature_values
    regime_snapshot = classify_regime(deployment.symbol, context.bars, context.latest_feature)
    legacy_regime_label = regime_snapshot.regime_label if regime_snapshot is not None else "unknown"
    unified_regime_label = map_regime_label_to_unified(
        legacy_regime_label,
        regime_snapshot.volatility_label if regime_snapshot is not None else "unknown",
        regime_snapshot.structure_label if regime_snapshot is not None else "unknown",
    )
    macro_regime = classify_macro_regime(values)
    session_regime = classify_session_regime(values)
    structure_regime = classify_structure_regime(values)
    volatility_regime = regime_snapshot.volatility_label if regime_snapshot is not None else classify_volatility_regime(values)
    execution_regime = classify_execution_regime(values)
    directional_bias = derive_directional_bias(values, structure_regime)
    setup_quality = score_setup_quality(values, structure_regime, session_regime)
    execution_quality = score_execution_quality(values, execution_regime)
    confidence = max(0.0, min(1.0, setup_quality * 0.6 + execution_quality * 0.4))
    risk_posture, no_trade_reason = derive_risk_posture(session_regime, volatility_regime, execution_regime, confidence)
    if regime_snapshot is not None and regime_snapshot.block_new_entries and not no_trade_reason:
        risk_posture = "defensive"
        no_trade_reason = f"regime_block::{regime_snapshot.regime_label}"
    allowed_archetypes, blocked_archetypes = derive_allowed_archetypes(structure_regime, session_regime, execution_regime, directional_bias)
    if no_trade_reason:
        allowed_archetypes = []
    state = InterpreterState(
        symbol=deployment.symbol,
        broker_symbol=deployment.broker_symbol,
        venue_key=deployment.venue_key,
        generated_at=generated_at,
        legacy_regime_label=legacy_regime_label,
        unified_regime_label=unified_regime_label,
        macro_regime=macro_regime,
        session_regime=session_regime,
        structure_regime=structure_regime,
        volatility_regime=volatility_regime,
        execution_regime=execution_regime,
        crowding_regime="neutral",
        directional_bias=directional_bias,
        setup_quality=setup_quality,
        execution_quality=execution_quality,
        confidence=confidence,
        risk_posture=risk_posture,
        allowed_archetypes=allowed_archetypes,
        blocked_archetypes=blocked_archetypes,
        no_trade_reason=no_trade_reason,
        feature_snapshot=build_feature_snapshot(values, context.timeframe, len(context.bars)),
        regime_snapshot=regime_snapshot,
    )
    state.explanation = build_explanation(state)
    return state


def build_all_market_interpreter_states(config: SystemConfig | None = None) -> list[InterpreterState]:
    config = config or SystemConfig()
    states: list[InterpreterState] = []
    for path in list_deployment_paths():
        deployment = load_symbol_deployment(path)
        if normalize_venue_key(deployment.venue_key) != normalize_venue_key(str(config.mt5.prop_broker)):
            continue
        states.append(build_market_interpreter_state(deployment, config))
    states.sort(key=lambda item: (item.risk_posture, item.execution_regime, item.symbol))
    return states
