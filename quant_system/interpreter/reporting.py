from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from quant_system.artifacts import live_symbol_dir, system_reports_dir
from quant_system.config import SystemConfig
from quant_system.interpreter.app import build_all_market_interpreter_states
from quant_system.interpreter.models import InterpreterState


def _write_symbol_artifact(state: InterpreterState) -> Path:
    path = live_symbol_dir(state.symbol) / "market_interpreter.json"
    path.write_text(json.dumps(asdict(state), indent=2, default=str), encoding="utf-8")
    return path


def generate_market_interpreter_report(config: SystemConfig | None = None) -> Path:
    config = config or SystemConfig()
    states = build_all_market_interpreter_states(config)
    report_path = system_reports_dir() / "market_interpreter_report.txt"
    json_path = report_path.with_suffix(".json")
    lines = ["Market interpreter report", f"generated_at: {datetime.now(UTC).isoformat()}", ""]
    if not states:
        lines.append("No live deployments found.")
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        json_path.write_text(json.dumps({"generated_at": datetime.now(UTC).isoformat(), "states": []}, indent=2), encoding="utf-8")
        return report_path
    for state in states:
        artifact_path = _write_symbol_artifact(state)
        lines.extend(
            [
                f"{state.symbol}: bias={state.directional_bias} confidence={state.confidence:.2f} risk={state.risk_posture}",
                (
                    f"  regimes: legacy={state.legacy_regime_label} unified={state.unified_regime_label} "
                    f"macro={state.macro_regime} session={state.session_regime} "
                    f"structure={state.structure_regime} vol={state.volatility_regime} execution={state.execution_regime}"
                )
                if state.regime_snapshot is not None
                else f"  regimes: legacy={state.legacy_regime_label} unified={state.unified_regime_label} macro={state.macro_regime} session={state.session_regime} structure={state.structure_regime} vol={state.volatility_regime} execution={state.execution_regime}",
                f"  quality: setup={state.setup_quality:.2f} execution={state.execution_quality:.2f}",
                f"  allowed_archetypes: {', '.join(state.allowed_archetypes) if state.allowed_archetypes else 'none'}",
                f"  blocked_archetypes: {', '.join(state.blocked_archetypes) if state.blocked_archetypes else 'none'}",
                f"  no_trade_reason: {state.no_trade_reason or 'none'}",
                f"  explanation: {state.explanation}",
                f"  artifact: {artifact_path}",
                "",
            ]
        )
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    json_path.write_text(json.dumps({"generated_at": datetime.now(UTC).isoformat(), "report_path": str(report_path), "states": [asdict(state) for state in states]}, indent=2, default=str), encoding="utf-8")
    return report_path
