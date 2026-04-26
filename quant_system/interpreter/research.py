from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from quant_system.artifacts import live_symbol_dir, system_reports_dir
from quant_system.config import SystemConfig
from quant_system.interpreter.app import build_all_market_interpreter_states
from quant_system.interpreter.models import InterpreterState


@dataclass(slots=True)
class InterpreterResearchDirective:
    symbol: str
    broker_symbol: str
    priority: int
    labels: list[str]
    objective: str
    suggested_experiments: list[str]
    report_path: Path


def _build_directive(state: InterpreterState) -> InterpreterResearchDirective | None:
    labels: list[str] = []
    experiments: list[str] = []
    priority = 0
    if state.execution_regime == "toxic":
        labels.append("execution_toxic")
        experiments.extend(
            [
                "test slower entry timing and stronger confirmation before breakout entries",
                "compare lower-turnover exit logic to reduce broker cost drag",
            ]
        )
        priority += 4
    elif state.execution_regime == "fragile":
        labels.append("execution_fragile")
        experiments.extend(
            [
                "test patient entry timing around current archetype",
                "compare session-filtered variants that avoid weak execution windows",
            ]
        )
        priority += 2

    if state.session_regime == "midday_chop":
        labels.append("midday_chop")
        experiments.append("test midday exclusion filters or mean-reversion-only variants")
        priority += 1
    if state.session_regime == "pre_event":
        labels.append("pre_event_risk")
        experiments.append("test macro-event blackout windows and post-event-only entries")
        priority += 2
    if state.structure_regime == "compression":
        labels.append("compression_regime")
        experiments.append("compare breakout-only variants against current mixed archetypes")
        priority += 1
    if state.structure_regime == "range_rotation":
        labels.append("range_rotation")
        experiments.append("test mean-reversion-biased variants and avoid trend breakout logic")
        priority += 1
    if state.no_trade_reason:
        labels.append(f"no_trade::{state.no_trade_reason}")
        priority += 1

    if not labels:
        return None
    objective = "Improve archetype selection using market interpreter state and execution context."
    report_path = live_symbol_dir(state.symbol, state.venue_key) / "interpreter_research_trigger.json"
    return InterpreterResearchDirective(
        symbol=state.symbol,
        broker_symbol=state.broker_symbol,
        priority=priority,
        labels=labels,
        objective=objective,
        suggested_experiments=list(dict.fromkeys(experiments))[:6],
        report_path=report_path,
    )


def generate_interpreter_research_report(config: SystemConfig | None = None) -> Path:
    config = config or SystemConfig()
    states = build_all_market_interpreter_states(config)
    directives = [item for item in (_build_directive(state) for state in states) if item is not None]
    directives.sort(key=lambda item: (-item.priority, item.symbol))
    report_path = system_reports_dir() / "market_interpreter_research_queue.txt"
    json_path = report_path.with_suffix(".json")
    lines = ["Market interpreter research queue", f"generated_at: {datetime.now(UTC).isoformat()}", ""]
    if not directives:
        lines.append("No interpreter-driven research directives.")
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        json_path.write_text(json.dumps({"generated_at": datetime.now(UTC).isoformat(), "items": []}, indent=2), encoding="utf-8")
        return report_path
    for item in directives:
        item.report_path.write_text(json.dumps(asdict(item), indent=2, default=str), encoding="utf-8")
        lines.extend(
            [
                f"{item.symbol}",
                f"  broker_symbol: {item.broker_symbol}",
                f"  priority: {item.priority}",
                f"  labels: {', '.join(item.labels)}",
                f"  objective: {item.objective}",
                "  suggested_experiments:",
                *[f"    - {experiment}" for experiment in item.suggested_experiments],
                f"  artifact: {item.report_path}",
                "",
            ]
        )
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    json_path.write_text(json.dumps({"generated_at": datetime.now(UTC).isoformat(), "items": [asdict(item) for item in directives]}, indent=2, default=str), encoding="utf-8")
    return report_path
