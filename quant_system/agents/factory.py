from __future__ import annotations

from quant_system.agents.base import Agent
from quant_system.agents.trend import MomentumConfirmationAgent, RiskSentinelAgent, TrendAgent
from quant_system.config import AgentConfig, RiskConfig


def build_alpha_agents(agent_config: AgentConfig, risk_config: RiskConfig) -> list[Agent]:
    return [
        TrendAgent(
            fast_window=agent_config.trend_fast_window,
            slow_window=agent_config.trend_slow_window,
            min_trend_strength=agent_config.min_trend_strength,
            min_relative_volume=agent_config.min_relative_volume,
        ),
        MomentumConfirmationAgent(
            threshold=agent_config.mean_reversion_threshold,
        ),
        RiskSentinelAgent(
            max_volatility=risk_config.max_volatility,
            min_relative_volume=agent_config.min_relative_volume,
        ),
    ]
