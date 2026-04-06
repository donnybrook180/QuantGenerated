from __future__ import annotations

from quant_system.agents.base import Agent
from quant_system.agents.ger40 import OpeningRangeBreakoutAgent, RangeRetestContinuationAgent
from quant_system.agents.us500 import US500OpeningDriveReclaimAgent, US500TrendPullbackAgent, US500VWAPContinuationAgent
from quant_system.agents.us100 import (
    LateSessionBreakoutAgent,
    OpeningDriveReclaimAgent,
    PostPullbackContinuationAgent,
    TrendContinuationBreakoutAgent,
    TrendPullbackAgent,
    VWAPReclaimContinuationAgent,
)
from quant_system.agents.xauusd import XAUUSDVolatilityBreakoutAgent
from quant_system.agents.trend import MomentumConfirmationAgent, RiskSentinelAgent, TrendAgent
from quant_system.config import AgentConfig, RiskConfig


def build_alpha_agents(agent_config: AgentConfig, risk_config: RiskConfig, profile_name: str) -> list[Agent]:
    risk_agent = RiskSentinelAgent(
        max_volatility=risk_config.max_volatility,
        min_relative_volume=agent_config.min_relative_volume,
    )

    if profile_name == "ger40_orb":
        return [OpeningRangeBreakoutAgent(), risk_agent]
    if profile_name == "us500_trend":
        return [
            US500TrendPullbackAgent(agent_config.min_trend_strength),
            US500OpeningDriveReclaimAgent(agent_config.min_trend_strength),
            risk_agent,
        ]
    if profile_name == "xauusd_volatility":
        return [XAUUSDVolatilityBreakoutAgent(lookback=max(6, agent_config.mean_reversion_window)), risk_agent]
    if profile_name == "us100_trend":
        return [TrendPullbackAgent(agent_config.min_trend_strength), risk_agent]
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
        risk_agent,
    ]


def build_shadow_candidate_agents(agent_config: AgentConfig, risk_config: RiskConfig, profile_name: str) -> dict[str, list[Agent]]:
    risk_agent = lambda: RiskSentinelAgent(
        max_volatility=risk_config.max_volatility,
        min_relative_volume=agent_config.min_relative_volume,
    )

    if profile_name == "us100_trend":
        return {
            "trend_pullback": [TrendPullbackAgent(agent_config.min_trend_strength), risk_agent()],
            "opening_drive_reclaim": [
                OpeningDriveReclaimAgent(
                    min_trend_strength=agent_config.min_trend_strength,
                    reclaim_buffer=max(agent_config.mean_reversion_threshold * 0.35, 0.0008),
                ),
                risk_agent(),
            ],
            "trend_continuation_breakout": [
                TrendContinuationBreakoutAgent(
                    min_trend_strength=agent_config.min_trend_strength,
                    breakout_lookback=max(5, agent_config.mean_reversion_window),
                ),
                risk_agent(),
            ],
            "post_pullback_continuation": [
                PostPullbackContinuationAgent(
                    min_trend_strength=agent_config.min_trend_strength,
                    pullback_lookback=max(6, agent_config.mean_reversion_window),
                ),
                risk_agent(),
            ],
            "late_session_breakout": [
                LateSessionBreakoutAgent(
                    min_trend_strength=agent_config.min_trend_strength,
                    lookback=max(6, agent_config.mean_reversion_window),
                ),
                risk_agent(),
            ],
            "vwap_reclaim_continuation": [
                VWAPReclaimContinuationAgent(
                    min_trend_strength=agent_config.min_trend_strength,
                ),
                risk_agent(),
            ],
        }
    if profile_name == "us500_trend":
        return {
            "us500_trend_pullback": [US500TrendPullbackAgent(agent_config.min_trend_strength), risk_agent()],
            "us500_vwap_continuation": [US500VWAPContinuationAgent(agent_config.min_trend_strength), risk_agent()],
            "us500_opening_drive_reclaim": [US500OpeningDriveReclaimAgent(agent_config.min_trend_strength), risk_agent()],
        }
    if profile_name == "ger40_orb":
        return {
            "opening_range_breakout": [OpeningRangeBreakoutAgent(), risk_agent()],
            "range_retest_continuation": [RangeRetestContinuationAgent(), risk_agent()],
            "combined_orb_retest": [OpeningRangeBreakoutAgent(), RangeRetestContinuationAgent(), risk_agent()],
        }
    return {}
