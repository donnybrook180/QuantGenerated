from __future__ import annotations

import copy
from datetime import datetime

from quant_system.catalog_runtime import build_agents_from_catalog_paths
from quant_system.config import SystemConfig
from quant_system.execution.engine import AgentCoordinator
from quant_system.integrations.mt5 import MT5Client
from quant_system.live.models import DeploymentStrategy, SymbolDeployment
from quant_system.models import Side
from quant_system.regime import RegimeSnapshot, classify_regime


def feature_regime_label(feature) -> str:
    trend_strength = feature.values.get("trend_strength", 0.0)
    atr_proxy = feature.values.get("atr_proxy", 0.0)
    if trend_strength >= 0.001:
        trend_label = "trend_up"
    elif trend_strength <= -0.001:
        trend_label = "trend_down"
    else:
        trend_label = "trend_flat"

    if atr_proxy >= 0.003:
        vol_label = "vol_high"
    elif atr_proxy <= 0.0012:
        vol_label = "vol_low"
    else:
        vol_label = "vol_mid"
    return f"{trend_label}_{vol_label}"


def matches_regime(feature, regime_filter_label: str) -> bool:
    if not regime_filter_label:
        return True
    label = feature_regime_label(feature)
    if regime_filter_label.startswith("exclude:"):
        excluded = regime_filter_label.removeprefix("exclude:")
        if excluded.startswith("trend_") and excluded.count("_") == 1:
            return not label.startswith(excluded + "_")
        if excluded.startswith("vol_") and excluded.count("_") == 1:
            return not label.endswith("_" + excluded)
        return label != excluded
    if regime_filter_label.startswith("trend_") and regime_filter_label.count("_") == 1:
        return label.startswith(regime_filter_label + "_")
    if regime_filter_label.startswith("vol_") and regime_filter_label.count("_") == 1:
        return label.endswith("_" + regime_filter_label)
    return label == regime_filter_label


def session_name_from_variant(variant_label: str) -> str:
    _, _, session_label = variant_label.partition("_")
    return session_label or "all"


def matches_session(feature, session_name: str) -> bool:
    hour = int(feature.values.get("hour_of_day", feature.timestamp.hour))
    if session_name == "all":
        return True
    if session_name == "europe":
        return hour in set(range(7, 13))
    if session_name == "us":
        return hour in set(range(13, 21))
    if session_name == "overlap":
        return hour in set(range(12, 17))
    if session_name == "open":
        return feature.values.get("in_regular_session", 0.0) >= 1.0 and 0 <= feature.values.get("minutes_from_open", -1.0) < 90
    if session_name == "power":
        return hour in {18, 19}
    if session_name == "midday":
        return hour in {15, 16, 17}
    return True


def build_strategy_config(
    base_config: SystemConfig,
    deployment: SymbolDeployment,
    strategy: DeploymentStrategy,
    mt5_timeframe_from_variant_fn,
) -> SystemConfig:
    from quant_system.execution_tuning import apply_execution_mode_overrides
    from quant_system.live_support import configure_symbol_execution

    strategy_config = copy.deepcopy(base_config)
    strategy_config.mt5.symbol = deployment.broker_symbol
    strategy_config.mt5.timeframe = mt5_timeframe_from_variant_fn(strategy.variant_label, strategy_config.mt5.timeframe)
    configure_symbol_execution(strategy_config, deployment.symbol)
    for key, value in strategy.execution_overrides.items():
        setattr(strategy_config.execution, key, value)
    apply_execution_mode_overrides(strategy_config)
    return strategy_config


def evaluate_strategy(
    client: MT5Client,
    strategy: DeploymentStrategy,
    strategy_config: SystemConfig,
    symbol: str,
) -> tuple[Side, float, datetime | None, RegimeSnapshot, str, object | None]:
    from quant_system.live_support import build_features_with_events

    bars = client.fetch_bars(bar_count=strategy_config.mt5.history_bars)
    features = build_features_with_events(strategy_config, symbol, bars)
    latest_feature = features[-1] if features else None
    snapshot = classify_regime(symbol, bars, latest_feature)
    session_name = session_name_from_variant(strategy.variant_label)
    agents = build_agents_from_catalog_paths([strategy.code_path], strategy_config)
    coordinator = AgentCoordinator(agents, consensus_min_confidence=strategy_config.agents.consensus_min_confidence)
    last_side = Side.FLAT
    last_confidence = 0.0
    last_timestamp: datetime | None = None
    last_veto_reason = ""
    for feature in features:
        if not matches_session(feature, session_name):
            continue
        if not matches_regime(feature, strategy.regime_filter_label):
            continue
        context = coordinator.evaluate(feature)
        if context is None:
            if coordinator.last_veto_reason:
                last_veto_reason = coordinator.last_veto_reason
            continue
        last_side = context.side
        last_confidence = context.confidence
        last_timestamp = feature.timestamp
        last_veto_reason = ""
    return last_side, last_confidence, last_timestamp, snapshot, last_veto_reason, latest_feature
