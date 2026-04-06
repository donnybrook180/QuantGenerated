from __future__ import annotations

import importlib
from typing import cast

from quant_system.agents.base import Agent
from quant_system.agents.crypto import (
    CryptoBreakoutReclaimAgent,
    CryptoShortBreakdownAgent,
    CryptoShortReversionAgent,
    CryptoTrendPullbackAgent,
    CryptoVolatilityExpansionAgent,
)
from quant_system.agents.forex import ForexBreakoutMomentumAgent, ForexRangeReversionAgent, ForexTrendContinuationAgent
from quant_system.agents.forex import ForexShortBreakdownMomentumAgent, ForexShortTrendContinuationAgent
from quant_system.agents.ger40 import GER40FailedBreakoutShortAgent, GER40RangeRejectShortAgent
from quant_system.agents.strategies import OpeningRangeShortBreakdownAgent, VolatilityShortBreakdownAgent
from quant_system.agents.us500 import US500OpeningDriveShortReclaimAgent, US500ShortTrendRejectionAgent
from quant_system.agents.xauusd import XAUUSDShortBreakdownAgent
from quant_system.agents.trend import MeanReversionAgent, MomentumConfirmationAgent, RiskSentinelAgent, TrendAgent
from quant_system.config import SystemConfig


def _instantiate_single(code_path: str, config: SystemConfig) -> Agent:
    module_name, _, class_name = code_path.rpartition(".")
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)

    if cls is TrendAgent:
        return TrendAgent(
            fast_window=config.agents.trend_fast_window,
            slow_window=config.agents.trend_slow_window,
            min_trend_strength=config.agents.min_trend_strength,
            min_relative_volume=config.agents.min_relative_volume,
        )
    if cls is MeanReversionAgent:
        return MeanReversionAgent(
            window=config.agents.mean_reversion_window,
            threshold=config.agents.mean_reversion_threshold,
        )
    if cls is MomentumConfirmationAgent:
        return MomentumConfirmationAgent(config.agents.mean_reversion_threshold)
    if cls is RiskSentinelAgent:
        return RiskSentinelAgent(
            max_volatility=config.risk.max_volatility,
            min_relative_volume=config.agents.min_relative_volume,
        )
    if cls is CryptoTrendPullbackAgent:
        return CryptoTrendPullbackAgent()
    if cls is CryptoBreakoutReclaimAgent:
        return CryptoBreakoutReclaimAgent()
    if cls is CryptoVolatilityExpansionAgent:
        return CryptoVolatilityExpansionAgent()
    if cls is CryptoShortBreakdownAgent:
        return CryptoShortBreakdownAgent()
    if cls is CryptoShortReversionAgent:
        return CryptoShortReversionAgent()
    if cls is ForexTrendContinuationAgent:
        return ForexTrendContinuationAgent()
    if cls is ForexShortTrendContinuationAgent:
        return ForexShortTrendContinuationAgent()
    if cls is ForexRangeReversionAgent:
        return ForexRangeReversionAgent()
    if cls is ForexBreakoutMomentumAgent:
        return ForexBreakoutMomentumAgent()
    if cls is ForexShortBreakdownMomentumAgent:
        return ForexShortBreakdownMomentumAgent()
    if cls is US500ShortTrendRejectionAgent:
        return US500ShortTrendRejectionAgent(config.agents.min_trend_strength)
    if cls is US500OpeningDriveShortReclaimAgent:
        return US500OpeningDriveShortReclaimAgent(config.agents.min_trend_strength)
    if cls is GER40RangeRejectShortAgent:
        return GER40RangeRejectShortAgent()
    if cls is GER40FailedBreakoutShortAgent:
        return GER40FailedBreakoutShortAgent()
    if cls is OpeningRangeShortBreakdownAgent:
        return OpeningRangeShortBreakdownAgent()
    if cls is VolatilityShortBreakdownAgent:
        return VolatilityShortBreakdownAgent()
    if cls is XAUUSDShortBreakdownAgent:
        return XAUUSDShortBreakdownAgent()

    try:
        return cast(Agent, cls())
    except TypeError:
        if "min_trend_strength" in getattr(cls.__init__, "__code__", object()).co_varnames:
            return cast(Agent, cls(config.agents.min_trend_strength))
        if "lookback" in getattr(cls.__init__, "__code__", object()).co_varnames:
            return cast(Agent, cls(lookback=max(6, config.agents.mean_reversion_window)))
        raise


def build_agents_from_catalog_paths(code_paths: list[str], config: SystemConfig) -> list[Agent]:
    agents: list[Agent] = []
    seen_names: set[str] = set()
    for code_path_group in code_paths:
        for code_path in (part.strip() for part in code_path_group.split(";") if part.strip()):
            agent = _instantiate_single(code_path, config)
            if agent.name in seen_names:
                continue
            seen_names.add(agent.name)
            agents.append(agent)
    if "risk_sentinel" not in seen_names:
        agents.append(
            RiskSentinelAgent(
                max_volatility=config.risk.max_volatility,
                min_relative_volume=config.agents.min_relative_volume,
            )
        )
    return agents
