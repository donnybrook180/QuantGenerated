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
from quant_system.live.activity import record_research_directives, record_research_run
from quant_system.live.deploy import load_symbol_deployment
from quant_system.live.tca_impact import StrategyImpactRow, build_tca_impact_rows
from quant_system.tca import generate_tca_report


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


@dataclass(slots=True)
class ResearchExperiment:
    experiment_type: str
    rationale: str
    candidate_prefixes: list[str]
    execution_overrides: dict[str, float | int]
    priority: int


@dataclass(slots=True)
class ResearchEscalationPlan:
    mode: str
    rationale: str
    experiments: list[ResearchExperiment]


@dataclass(slots=True)
class ResearchDirective:
    symbol: str
    broker_symbol: str
    candidate_name: str
    priority: int
    escalation_mode: str
    escalation_rationale: str
    failure_labels: list[str]
    objective: str
    experiments: list[str]
    structured_experiments: list[ResearchExperiment]
    suggested_command: list[str]
    edge_retention_pct: float
    live_fill_count: int
    report_path: Path


def _research_reports_path(symbol: str) -> Path:
    return live_symbol_dir(symbol) / "research_trigger.json"


def _autopsy_state_path(symbol: str) -> Path:
    return live_symbol_dir(symbol) / "autopsy_state.json"


def _load_autopsy_state(symbol: str) -> dict[str, object]:
    path = _autopsy_state_path(symbol)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_autopsy_state(symbol: str, state: dict[str, object]) -> None:
    _autopsy_state_path(symbol).write_text(json.dumps(state, indent=2), encoding="utf-8")


def _build_structured_experiments(
    candidate_name: str,
    failure_labels: list[str],
    live_fill_count: int,
) -> list[ResearchExperiment]:
    experiments: list[ResearchExperiment] = []
    base_prefix = candidate_name.split("__")[0]
    if "entry_timing_or_fill_quality_problem" in failure_labels:
        experiments.append(
            ResearchExperiment(
                experiment_type="entry_timing_variant",
                rationale="Execution drag suggests entries are too aggressive or too early.",
                candidate_prefixes=[base_prefix],
                execution_overrides={"min_bars_between_trades": 12},
                priority=4,
            )
        )
        experiments.append(
            ResearchExperiment(
                experiment_type="session_filter_variant",
                rationale="Bad fills may be concentrated in specific sessions.",
                candidate_prefixes=[base_prefix],
                execution_overrides={"min_bars_between_trades": 10},
                priority=3,
            )
        )
    if "broker_cost_drag" in failure_labels:
        experiments.append(
            ResearchExperiment(
                experiment_type="exit_variant",
                rationale="Cost drag suggests turnover is too high for this broker.",
                candidate_prefixes=[base_prefix],
                execution_overrides={"max_holding_bars": 36, "min_bars_between_trades": 14},
                priority=3,
            )
        )
    if "edge_too_small_after_costs" in failure_labels or "execution_fragility" in failure_labels:
        experiments.append(
            ResearchExperiment(
                experiment_type="regime_filter_variant",
                rationale="Need stronger selectivity so only higher-payoff regimes are traded.",
                candidate_prefixes=[base_prefix],
                execution_overrides={"min_bars_between_trades": 10},
                priority=4,
            )
        )
    if "severe_demotion_requires_research" in failure_labels or "blocked_requires_replacement_research" in failure_labels:
        experiments.append(
            ResearchExperiment(
                experiment_type="replacement_archetype_search",
                rationale="Current live variant is no longer acceptable; search alternative archetypes.",
                candidate_prefixes=[],
                execution_overrides={},
                priority=5,
            )
        )
    if "repeated_demotion_requires_research" in failure_labels and live_fill_count >= 10:
        experiments.append(
            ResearchExperiment(
                experiment_type="full_symbol_rerun",
                rationale="Repeated degradation suggests structural breakdown, not a one-off issue.",
                candidate_prefixes=[],
                execution_overrides={},
                priority=5,
            )
        )
    deduped: list[ResearchExperiment] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for item in sorted(experiments, key=lambda row: (-row.priority, row.experiment_type)):
        key = (item.experiment_type, tuple(item.candidate_prefixes))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:5]


def _build_escalation_plan(
    candidate_name: str,
    failure_labels: list[str],
    live_fill_count: int,
) -> ResearchEscalationPlan:
    structured = _build_structured_experiments(candidate_name, failure_labels, live_fill_count)
    if "blocked_requires_replacement_research" in failure_labels:
        full = [item for item in structured if item.experiment_type in {"replacement_archetype_search", "full_symbol_rerun"}]
        experiments = full or structured
        return ResearchEscalationPlan(
            mode="full_rerun_only",
            rationale="Live blocking means the current strategy slot needs a replacement, not just a small repair.",
            experiments=experiments,
        )
    if "severe_demotion_requires_research" in failure_labels or "repeated_demotion_requires_research" in failure_labels:
        targeted = [
            item
            for item in structured
            if item.experiment_type not in {"full_symbol_rerun"}
        ]
        replacement = [
            item
            for item in structured
            if item.experiment_type in {"replacement_archetype_search", "full_symbol_rerun"}
        ]
        experiments = (targeted[:2] + replacement[:2]) or structured
        return ResearchEscalationPlan(
            mode="targeted_plus_replacement",
            rationale="Degradation is severe or persistent; try local repairs but search replacements in parallel.",
            experiments=experiments,
        )
    if any(label in failure_labels for label in {"moderate_demotion_requires_research", "execution_fragility", "entry_timing_or_fill_quality_problem", "broker_cost_drag"}):
        targeted = [
            item
            for item in structured
            if item.experiment_type not in {"replacement_archetype_search", "full_symbol_rerun"}
        ]
        return ResearchEscalationPlan(
            mode="targeted_only",
            rationale="The live issue looks repairable inside the current archetype, so start with a focused experiment.",
            experiments=(targeted or structured)[:3],
        )
    return ResearchEscalationPlan(
        mode="none",
        rationale="No escalation required.",
        experiments=[],
    )


def _build_structured_command(
    directive_symbol: str,
    broker_symbol: str,
    experiment: ResearchExperiment | None,
) -> list[str]:
    if experiment is None:
        return [sys.executable, "main_symbol_research.py", directive_symbol, broker_symbol]
    return [
        sys.executable,
        "tools/main_live_research_runner.py",
        directive_symbol,
        broker_symbol,
        experiment.experiment_type,
        json.dumps(experiment.candidate_prefixes),
        json.dumps(experiment.execution_overrides),
    ]


def _classify_failures(
    row: StrategyImpactRow,
    *,
    adaptation_action: str,
    repeated_demotions: int,
    blocked_now: bool,
) -> tuple[list[str], str, list[str], int]:
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

    if adaptation_action == "demote_moderate" and row.live_fill_count >= min_live_fills:
        failure_labels.append("moderate_demotion_requires_research")
        experiments.extend(
            [
                "rerun targeted research on the current archetype with stricter selectivity",
                "compare lower-turnover variants with higher payoff per trade",
            ]
        )
        priority += 2

    if adaptation_action in {"demote_severe", "guardrail_capped_severe_demotion"} and row.live_fill_count >= min_live_fills:
        failure_labels.append("severe_demotion_requires_research")
        experiments.extend(
            [
                "launch high-priority replacement research for this strategy slot",
                "compare alternate entry and exit archetypes, not only parameter tweaks",
            ]
        )
        priority += 3

    if blocked_now and row.live_fill_count >= min_live_fills:
        failure_labels.append("blocked_requires_replacement_research")
        experiments.extend(
            [
                "mandatory replacement search because live entry blocking is active",
                "search alternative strategy families for the same symbol and session",
            ]
        )
        priority += 4

    repeat_trigger = _env_int("LIVE_RESEARCH_TRIGGER_REPEAT_DEMOTION_CYCLES", 3)
    if repeated_demotions >= repeat_trigger and row.live_fill_count >= min_live_fills:
        failure_labels.append("repeated_demotion_requires_research")
        experiments.extend(
            [
                "treat degradation as structural and rerun broader symbol research",
                "compare current deployed variant against fresh candidate generation",
            ]
        )
        priority += 3

    if not failure_labels:
        return ([], "", [], 0)

    objective = "Improve retained edge after live execution while preserving robustness."
    deduped_experiments = list(dict.fromkeys(experiments))
    return (failure_labels, objective, deduped_experiments[:6], priority)


def build_live_research_directives(config: SystemConfig | None = None) -> list[ResearchDirective]:
    config = config or SystemConfig()
    impact_rows = build_tca_impact_rows(config)
    directives: list[ResearchDirective] = []
    state_by_symbol: dict[str, dict[str, object]] = {}
    for impact_row in impact_rows:
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
        _, adaptation = adapt_deployment_for_execution(deployment, config)
        action_row = next((item for item in adaptation.strategy_actions if item.candidate_name == impact_row.candidate_name), None)
        adaptation_action = action_row.action if action_row is not None else "unchanged"
        blocked_now = action_row is not None and action_row.local_rank_label == "blocked_local"

        symbol_state = state_by_symbol.get(impact_row.symbol)
        if symbol_state is None:
            symbol_state = _load_autopsy_state(impact_row.symbol)
            state_by_symbol[impact_row.symbol] = symbol_state
        previous_state = dict(symbol_state.get(impact_row.candidate_name, {}))
        previous_demotions = int(previous_state.get("consecutive_demotions", 0) or 0)
        if adaptation_action in {
            "demote_moderate",
            "demote_severe",
            "guardrail_capped_severe_demotion",
            "guardrail_block_removed",
            "guardrail_kept_one_live",
        }:
            repeated_demotions = previous_demotions + 1
        else:
            repeated_demotions = 0

        failure_labels, objective, experiments, priority = _classify_failures(
            impact_row,
            adaptation_action=adaptation_action,
            repeated_demotions=repeated_demotions,
            blocked_now=blocked_now,
        )
        symbol_state[impact_row.candidate_name] = {
            "consecutive_demotions": repeated_demotions,
            "last_action": adaptation_action,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        if not failure_labels:
            continue
        report_path = _research_reports_path(impact_row.symbol)
        directives.append(
            # The first structured experiment acts as the default auto-research plan.
            ResearchDirective(
                symbol=impact_row.symbol,
                broker_symbol=impact_row.broker_symbol,
                candidate_name=impact_row.candidate_name,
                priority=priority,
                escalation_mode=(plan := _build_escalation_plan(
                    impact_row.candidate_name,
                    failure_labels,
                    impact_row.live_fill_count,
                )).mode,
                escalation_rationale=plan.rationale,
                failure_labels=failure_labels,
                objective=objective,
                experiments=experiments,
                structured_experiments=plan.experiments,
                suggested_command=_build_structured_command(
                    deployment.data_symbol,
                    deployment.broker_symbol,
                    plan.experiments[0] if plan.experiments else None,
                ),
                edge_retention_pct=impact_row.edge_retention_pct,
                live_fill_count=impact_row.live_fill_count,
                report_path=report_path,
            )
        )
    for symbol, state in state_by_symbol.items():
        _save_autopsy_state(symbol, state)
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
    record_research_directives(directives)
    for item in directives:
        lines.extend(
            [
                f"{item.symbol} | {item.candidate_name}",
                f"  priority: {item.priority}",
                f"  broker_symbol: {item.broker_symbol}",
                f"  live_fill_count: {item.live_fill_count}",
                f"  edge_retention_pct: {item.edge_retention_pct:.2f}",
                f"  escalation_mode: {item.escalation_mode}",
                f"  escalation_rationale: {item.escalation_rationale}",
                f"  failure_labels: {', '.join(item.failure_labels)}",
                f"  objective: {item.objective}",
                "  experiments:",
            ]
        )
        lines.extend(f"    - {experiment}" for experiment in item.experiments)
        if item.structured_experiments:
            lines.append("  structured_experiments:")
            lines.extend(
                f"    - {experiment.experiment_type} priority={experiment.priority} prefixes={','.join(experiment.candidate_prefixes) or 'all'} rationale={experiment.rationale}"
                for experiment in item.structured_experiments
            )
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
            selected_experiment = directive.structured_experiments[0] if directive.structured_experiments else None
            completed = subprocess.run(
                directive.suggested_command,
                cwd=str(Path.cwd()),
                capture_output=True,
                text=True,
                timeout=_env_int("LIVE_AUTO_RESEARCH_TIMEOUT_SECONDS", 1800),
                check=False,
            )
            lines.append(
                f"Auto research: {directive.symbol}/{directive.candidate_name} "
                f"experiment={selected_experiment.experiment_type if selected_experiment is not None else 'full_symbol_rerun'} "
                f"rc={completed.returncode}"
            )
            record_research_run(
                symbol=directive.symbol,
                broker_symbol=directive.broker_symbol,
                candidate_name=directive.candidate_name,
                experiment_type=selected_experiment.experiment_type if selected_experiment is not None else "full_symbol_rerun",
                command=directive.suggested_command,
                return_code=completed.returncode,
            )
        except Exception as exc:
            lines.append(f"Auto research failed for {directive.symbol}/{directive.candidate_name}: {exc}")
    return lines
