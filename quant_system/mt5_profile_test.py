from __future__ import annotations

import copy
import logging
import os

from quant_system.agents.factory import build_alpha_agents
from quant_system.app import configure_profile_execution
from quant_system.config import SystemConfig
from quant_system.execution.engine import AgentCoordinator
from quant_system.integrations.mt5 import MT5Client
from quant_system.logging_utils import configure_logging
from quant_system.models import DecisionContext, Side
from quant_system.profiles import resolve_profiles
from quant_system.research.features import build_feature_library


LOGGER = logging.getLogger(__name__)


def _resolve_test_profiles(config: SystemConfig):
    raw = os.getenv("MT5_TEST_PROFILES", "xauusd_volatility,us500_trend,ger40_orb")
    requested = tuple(part.strip() for part in raw.split(",") if part.strip())
    return resolve_profiles(requested)


def _latest_decision_for_profile(config: SystemConfig, profile) -> tuple[DecisionContext | None, int, float, str]:
    local_config = copy.deepcopy(config)
    local_config.instrument.profile_name = profile.name
    local_config.instrument.broker_symbol = profile.broker_symbol
    local_config.mt5.symbol = profile.broker_symbol
    configure_profile_execution(local_config, profile)

    client = MT5Client(local_config.mt5)
    client.initialize()
    try:
        bars = client.fetch_bars(bar_count=max(local_config.mt5.history_bars, 300))
        if not bars:
            raise RuntimeError(f"No MT5 bars returned for {profile.broker_symbol}")
        features = build_feature_library(bars)
        agents = build_alpha_agents(local_config.agents, local_config.risk, profile.name)
        coordinator = AgentCoordinator(agents, consensus_min_confidence=local_config.agents.consensus_min_confidence)

        latest_context: DecisionContext | None = None
        for feature in features:
            context = coordinator.evaluate(feature)
            if context is not None:
                latest_context = context

        latest_price = bars[-1].close
        resolved_symbol = client.resolved_symbol or profile.broker_symbol
        return latest_context, len(bars), latest_price, resolved_symbol
    finally:
        client.shutdown()


def main() -> int:
    configure_logging()
    config = SystemConfig()
    profiles = _resolve_test_profiles(config)
    if not profiles:
        print("No MT5 test profiles resolved.")
        return 1

    lines = ["MT5 profile test complete"]
    for profile in profiles:
        lines.append("")
        try:
            context, bar_count, latest_price, resolved_symbol = _latest_decision_for_profile(config, profile)
            side = context.side.value if context is not None else "none"
            confidence = f"{context.confidence:.2f}" if context is not None else "0.00"
            reasons = ", ".join(context.reasons) if context is not None and context.reasons else "none"
            lines.extend(
                [
                    f"Profile: {profile.name}",
                    f"Broker symbol: {profile.broker_symbol}",
                    f"Resolved MT5 symbol: {resolved_symbol}",
                    f"Bars fetched: {bar_count}",
                    f"Latest price: {latest_price:.5f}",
                    f"Latest decision: {side}",
                    f"Decision confidence: {confidence}",
                    f"Decision reasons: {reasons}",
                ]
            )
        except Exception as exc:
            LOGGER.exception("mt5 profile test failed for %s", profile.name)
            lines.extend(
                [
                    f"Profile: {profile.name}",
                    f"Broker symbol: {profile.broker_symbol}",
                    "Status: failed",
                    f"Reason: {exc}",
                ]
            )

    print("\n".join(lines))
    return 0
