from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from quant_system.artifacts import DEPLOY_DIR, live_symbol_dir, system_reports_dir
from quant_system.config import SystemConfig
from quant_system.live.adaptation import adapt_deployment_for_execution
from quant_system.live.deploy import load_symbol_deployment
from quant_system.live.tca_impact import StrategyImpactRow, build_tca_impact_rows
from quant_system.tca import generate_tca_report


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


@dataclass(slots=True)
class ResearchDirective:
    symbol: str
    broker_symbol: str
    candidate_name: str
    priority: int
    failure_labels: list[str]
    objective: str
    experiments: list[str]
    suggested_command: list[str]
    edge_retention_pct: float
    live_fill_count: int
    report_path: Path


def _research_reports_path(symbol: str) -> Path:
    return live_symbol_dir(symbol) / "research_trigger.json"


def _classify_failures(row: StrategyImpactRow) -> tuple[list[str], str, list[str], int]:
    min_live_fills = _env_int("LIVE_RESEARCH_TRIGGER_MIN_FILLS", 6)
    severe_edge_retention_pct = _env_float("LIVE_RESEARCH_TRIGGER_SEVERE_EDGE_RETENTION_PCT", 35.0)
    weak_edge_retention_pct = _env_float("LIVE_RESEARCH_TRIGGER_WEAK_EDGE_RETENTION_PCT", 60.0)
    severe_drag_share_pct = _env_float("LIVE_RESEARCH_TRIGGER_SEVERE_DRAG_SHARE_PCT", 80.0)
    weak_drag_share_pct = _env_float("LIVE_RESEARCH_TRIGGER_WEAK_DRAG_SHARE_PCT", 40.0)

    if row.live_fill_count < min_live_fills:
        return ([], "", [], 0)

    failure_labels: list[str] = []
    experiments: list[str] = []
    priority = 0

    if row.edge_retention_pct <= severe_edge_retention_pct or row.drag_share_pct >= severe_drag_share_pct:
        failure_labels.append("edge_too_small_after_costs")
        experiments.extend(
            [
                "increase setup selectivity so expected payoff per trade is larger",
                "research stricter confirmation filters before entry",
                "compare slower/patient variants against current fast entry logic",
            ]
        )
        priority += 3
    elif row.edge_retention_pct <= weak_edge_retention_pct or row.drag_share_pct >= weak_drag_share_pct:
        failure_labels.append("execution_fragility")
        experiments.extend(
            [
                "test patient entry timing and delayed confirmation",
                "evaluate session filters and exclude high-drag windows",
                "compare reduced-trade-frequency variants with higher average payoff",
            ]
        )
        priority += 2

    if row.execution_drag_bps > row.cost_bps * 2.0 and row.execution_drag_bps > 0.0:
        failure_labels.append("entry_timing_or_fill_quality_problem")
        experiments.extend(
            [
                "research less aggressive entry placement and breakout confirmation",
                "test variants with wider trigger threshold or reclaim confirmation",
                "compare alternate session timing around the same archetype",
            ]
        )
        priority += 2

    if row.cost_bps >= max(1.0, row.execution_drag_bps):
        failure_labels.append("broker_cost_drag")
        experiments.extend(
            [
                "favor wider-payoff setups that can absorb broker costs",
                "test lower-turnover exit logic with longer holding periods",
                "reduce churn by increasing min bars between trades",
            ]
        )
        priority += 1

    if not failure_labels:
        return ([], "", [], 0)

    objective = "Improve retained edge after live execution while preserving robustness."
    deduped_experiments = list(dict.fromkeys(experiments))
    return (failure_labels, objective, deduped_experiments[:6], priority)


def build_live_research_directives(config: SystemConfig | None = None) -> list[ResearchDirective]:
    config = config or SystemConfig()
    impact_rows = build_tca_impact_rows(config)
    directives: list[ResearchDirective] = []
    for impact_row in impact_rows:
        failure_labels, objective, experiments, priority = _classify_failures(impact_row)
        if not failure_labels:
            continue
        deployment_path = DEPLOY_DIR / impact_row.symbol.lower() / "live.json"
        if not deployment_path.exists():
            # Fallback to scanning deployments to preserve current artifact layout behavior.
            deployment = next(
                (
                    item
                    for item in (load_symbol_deployment(path) for path in sorted(DEPLOY_DIR.glob("*/live.json")))
                    if item.symbol == impact_row.symbol
                ),
                None,
            )
        else:
            deployment = load_symbol_deployment(deployment_path)
        if deployment is None:
            continue
        report_path = _research_reports_path(impact_row.symbol)
        directives.append(
            ResearchDirective(
                symbol=impact_row.symbol,
                broker_symbol=impact_row.broker_symbol,
                candidate_name=impact_row.candidate_name,
                priority=priority,
                failure_labels=failure_labels,
                objective=objective,
                experiments=experiments,
                suggested_command=[
                    sys.executable,
                    "main_symbol_research.py",
                    deployment.data_symbol,
                    deployment.broker_symbol,
                ],
                edge_retention_pct=impact_row.edge_retention_pct,
                live_fill_count=impact_row.live_fill_count,
                report_path=report_path,
            )
        )
    directives.sort(key=lambda item: (-item.priority, item.edge_retention_pct, -item.live_fill_count, item.symbol, item.candidate_name))
    return directives


def generate_live_research_queue(config: SystemConfig | None = None) -> Path:
    config = config or SystemConfig()
    directives = build_live_research_directives(config)
    report_path = system_reports_dir() / "live_research_queue.txt"
    lines = [
        "Live research queue",
        f"generated_at: {datetime.now(UTC).isoformat()}",
        "",
        "This queue is built from live TCA impact and execution adaptation diagnostics.",
        "",
    ]
    if not directives:
        lines.append("No research triggers. Current live data does not justify a research rerun.")
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        _write_queue_json([])
        return report_path
    for item in directives:
        lines.extend(
            [
                f"{item.symbol} | {item.candidate_name}",
                f"  priority: {item.priority}",
                f"  broker_symbol: {item.broker_symbol}",
                f"  live_fill_count: {item.live_fill_count}",
                f"  edge_retention_pct: {item.edge_retention_pct:.2f}",
                f"  failure_labels: {', '.join(item.failure_labels)}",
                f"  objective: {item.objective}",
                "  experiments:",
            ]
        )
        lines.extend(f"    - {experiment}" for experiment in item.experiments)
        lines.append(f"  command: {' '.join(item.suggested_command)}")
        lines.append("")
        item.report_path.write_text(json.dumps(asdict(item), indent=2, default=str), encoding="utf-8")
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    _write_queue_json(directives)
    return report_path


def _write_queue_json(directives: list[ResearchDirective]) -> None:
    path = system_reports_dir() / "live_research_queue.json"
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "items": [asdict(item) for item in directives],
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def maybe_run_auto_research(config: SystemConfig | None = None) -> list[str]:
    config = config or SystemConfig()
    if os.getenv("LIVE_AUTO_RESEARCH_ENABLED", "false").lower() != "true":
        return []
    directives = build_live_research_directives(config)
    if not directives:
        return ["Auto research: no queued directives."]
    max_runs = _env_int("LIVE_AUTO_RESEARCH_MAX_RUNS", 1)
    lines: list[str] = []
    for directive in directives[:max_runs]:
        try:
            completed = subprocess.run(
                directive.suggested_command,
                cwd=str(Path.cwd()),
                capture_output=True,
                text=True,
                timeout=_env_int("LIVE_AUTO_RESEARCH_TIMEOUT_SECONDS", 1800),
                check=False,
            )
            lines.append(
                f"Auto research: {directive.symbol}/{directive.candidate_name} rc={completed.returncode}"
            )
        except Exception as exc:
            lines.append(f"Auto research failed for {directive.symbol}/{directive.candidate_name}: {exc}")
    return lines
