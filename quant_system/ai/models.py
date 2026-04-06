from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ProfileArtifacts:
    trade_log: Path
    trade_analysis: Path
    signal_log: Path
    signal_analysis: Path
    shadow_log: Path | None
    shadow_analysis: Path | None


@dataclass(slots=True)
class AnalysisPackage:
    local_summary: str
    next_experiments: list[str]
    ai_summary: str | None = None


@dataclass(slots=True)
class ExperimentSnapshot:
    experiment_id: int
    created_at: str
    profile_name: str
    ending_equity: float
    realized_pnl: float
    closed_trades: int
    win_rate_pct: float
    profit_factor: float
    max_drawdown_pct: float
    ftmo_passed: bool
    local_summary: str
    ai_summary: str


@dataclass(slots=True)
class ComparisonPackage:
    history_summary: str
    comparison_summary: str


@dataclass(slots=True)
class AgentRegistryRecord:
    profile_name: str
    agent_name: str
    source_type: str
    realized_pnl: float
    closed_trades: int
    win_rate_pct: float
    profit_factor: float
    max_drawdown_pct: float
    data_source: str
    verdict: str
    recommended_action: str


@dataclass(slots=True)
class AgentDescriptor:
    profile_name: str
    agent_name: str
    lifecycle_scope: str
    class_name: str
    code_path: str
    description: str
    is_active: bool
