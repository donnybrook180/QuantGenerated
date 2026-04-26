from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from quant_system.ai.storage import ExperimentStore
from quant_system.artifacts import list_deployment_paths, resolve_live_symbol_dir, system_reports_dir
from quant_system.config import SystemConfig
from quant_system.interpreter.app import build_all_market_interpreter_states
from quant_system.interpreter.research import generate_interpreter_research_report
from quant_system.interpreter.reporting import generate_market_interpreter_report
from quant_system.live.adaptation import adapt_deployment_for_execution, summarize_execution_adaptation
from quant_system.live.activity import generate_improvement_activity_report
from quant_system.live.autopsy import build_live_research_directives, generate_live_research_queue
from quant_system.live.deploy import load_symbol_deployment
from quant_system.live.tca_adaptation_impact import generate_tca_adaptation_impact_report
from quant_system.live.tca_impact import build_tca_impact_rows, generate_tca_impact_report
from quant_system.tca import generate_tca_report, summarize_tca_overview
from quant_system.venues import normalize_venue_key


def generate_live_health_report(config: SystemConfig | None = None) -> Path:
    config = config or SystemConfig()
    report_path = system_reports_dir() / "live_health_report.txt"
    snapshot = build_live_health_snapshot(config)
    report_path.write_text(snapshot["text"], encoding="utf-8")
    report_path.with_suffix(".json").write_text(json.dumps(snapshot["json"], indent=2, default=str), encoding="utf-8")
    return report_path


def build_live_health_report_text(config: SystemConfig) -> str:
    return build_live_health_snapshot(config)["text"]


def build_live_health_snapshot(config: SystemConfig) -> dict[str, object]:
    store = ExperimentStore(config.ai.experiment_database_path, read_only=True)
    deployment_paths = [
        path
        for path in list_deployment_paths()
        if normalize_venue_key(load_symbol_deployment(path).venue_key) == normalize_venue_key(str(config.mt5.prop_broker))
    ]
    tca_report = generate_tca_report(config)
    impact_rows = build_tca_impact_rows(config)
    impact_report = generate_tca_impact_report(config)
    adaptation_impact_report = generate_tca_adaptation_impact_report(config)
    interpreter_report = generate_market_interpreter_report(config)
    interpreter_research_report = generate_interpreter_research_report(config)
    interpreter_states = {item.symbol: item for item in build_all_market_interpreter_states(config)}
    research_directives = build_live_research_directives(config)
    research_queue_report = generate_live_research_queue(config)
    improvement_activity_report = generate_improvement_activity_report()
    timestamp = datetime.now(UTC).isoformat()
    statuses = {"live_ready": 0, "reduced_risk_only": 0, "research_only": 0}
    incident_count = 0
    total_fills = 0
    symbol_rows: list[list[str]] = []
    symbol_json_rows: list[dict[str, object]] = []
    tradeable_now: list[str] = []
    blocked_now: list[str] = []
    recent_incidents: list[str] = []

    for path in deployment_paths:
        deployment = load_symbol_deployment(path)
        adapted_deployment, adaptation = adapt_deployment_for_execution(deployment, config)
        symbol = deployment.symbol
        symbol_live_dir = resolve_live_symbol_dir(symbol, deployment.venue_key)
        latest_journal = _latest_file(symbol_live_dir / "journals", ".json")
        latest_incident = _latest_file(symbol_live_dir / "incidents", ".txt")
        fill_summary = store.load_mt5_fill_summary(deployment.broker_symbol)
        symbol_tca = generate_tca_report(config, broker_symbol=deployment.broker_symbol)
        latest_journal_summary = _latest_journal_summary(latest_journal)
        latest_actions = latest_journal_summary["display"]
        statuses[adapted_deployment.symbol_status] = statuses.get(adapted_deployment.symbol_status, 0) + 1
        if latest_incident is not None:
            incident_count += 1
            recent_incidents.append(f"{symbol} ({latest_incident.name})")
        total_fills += int(fill_summary.get("fill_count", 0) or 0) if fill_summary else 0
        if adapted_deployment.symbol_status != "research_only":
            if latest_journal_summary["tradeable"]:
                tradeable_now.append(symbol)
            elif latest_journal_summary["blocked"]:
                blocked_now.append(symbol)

        symbol_rows.append(
            [
                f"Symbol: {symbol}",
                f"  status: {adapted_deployment.symbol_status}",
                f"  broker_symbol: {deployment.broker_symbol}",
                f"  strategies: {len(deployment.strategies)}",
                f"  tiers: {', '.join(sorted({strategy.promotion_tier for strategy in deployment.strategies})) or 'none'}",
                f"  execution_validation: {deployment.execution_validation_summary}",
                f"  execution_adaptation: {summarize_execution_adaptation(adaptation)}",
                f"  execution_guardrail: {adaptation.guardrail_reason}",
                f"  deployment: {path}",
                f"  latest_journal: {latest_journal if latest_journal is not None else 'none'}",
                f"  latest_incident: {latest_incident if latest_incident is not None else 'none'}",
                f"  fills: {_format_fill_summary(fill_summary)}",
                f"  tca: {summarize_tca_overview(symbol_tca)}",
                (
                    f"  interpreter: legacy_regime={interpreter_states[symbol].legacy_regime_label} "
                    f"unified_regime={interpreter_states[symbol].unified_regime_label} "
                    f"bias={interpreter_states[symbol].directional_bias} "
                    f"session={interpreter_states[symbol].session_regime} "
                    f"structure={interpreter_states[symbol].structure_regime} "
                    f"execution={interpreter_states[symbol].execution_regime} "
                    f"risk={interpreter_states[symbol].risk_posture} "
                    f"confidence={interpreter_states[symbol].confidence:.2f}"
                )
                if symbol in interpreter_states
                else "  interpreter: none",
                f"  latest_actions: {latest_actions}" if latest_actions else "",
                "",
            ]
        )
        symbol_json_rows.append(
            {
                "symbol": symbol,
                "status": adapted_deployment.symbol_status,
                "broker_symbol": deployment.broker_symbol,
                "strategy_count": len(deployment.strategies),
                "tiers": sorted({strategy.promotion_tier for strategy in deployment.strategies}),
                "execution_validation": deployment.execution_validation_summary,
                "execution_adaptation": summarize_execution_adaptation(adaptation),
                "execution_guardrail": adaptation.guardrail_reason,
                "deployment_path": str(path),
                "latest_journal": str(latest_journal) if latest_journal is not None else None,
                "latest_incident": str(latest_incident) if latest_incident is not None else None,
                "fill_summary": fill_summary,
                "tca_overview": asdict(symbol_tca.overview) if symbol_tca.overview is not None else None,
                "latest_actions": latest_actions or None,
            }
        )

    lines = [
        f"Live health report generated at: {timestamp}",
        f"Deployments scanned: {len(deployment_paths)}",
        (
            "Summary: "
            f"live_ready={statuses.get('live_ready', 0)} "
            f"reduced_risk_only={statuses.get('reduced_risk_only', 0)} "
            f"research_only={statuses.get('research_only', 0)} "
            f"symbols_with_incidents={incident_count} "
            f"total_fills={total_fills}"
        ),
        f"TCA overview: {summarize_tca_overview(tca_report)}",
        f"TCA report: {tca_report.report_path}",
        f"TCA impact report: {impact_report}",
        f"TCA adaptation impact report: {adaptation_impact_report}",
        f"Market interpreter report: {interpreter_report}",
        f"Market interpreter research queue: {interpreter_research_report}",
        f"Live research queue: {research_queue_report}",
        f"Live improvement activity report: {improvement_activity_report}",
        f"Live research triggers: {len(research_directives)}",
        f"TCA worst edge retention: {impact_rows[0].symbol}/{impact_rows[0].candidate_name}={impact_rows[0].edge_retention_pct:.1f}%"
        if impact_rows
        else "TCA worst edge retention: none",
        f"Tradeable now: {', '.join(tradeable_now) if tradeable_now else 'none'}",
        f"Blocked now: {', '.join(blocked_now) if blocked_now else 'none'}",
        f"Recent incidents: {', '.join(recent_incidents[:5]) if recent_incidents else 'none'}",
        "",
    ]
    if not deployment_paths:
        lines.append("No deployments found.")
        return {
            "text": "\n".join(lines),
            "json": {
                "generated_at": timestamp,
                "summary": {
                    "deployments_scanned": 0,
                    "statuses": statuses,
                    "symbols_with_incidents": incident_count,
                    "total_fills": total_fills,
                    "tradeable_now": tradeable_now,
                    "blocked_now": blocked_now,
                    "research_triggers": len(research_directives),
                },
                "reports": {
                    "tca_report": str(tca_report.report_path),
                    "tca_impact_report": str(impact_report),
                    "tca_adaptation_impact_report": str(adaptation_impact_report),
                    "market_interpreter_report": str(interpreter_report),
                    "market_interpreter_research_queue": str(interpreter_research_report),
                    "live_research_queue": str(research_queue_report),
                    "live_improvement_activity_report": str(improvement_activity_report),
                },
                "symbols": [],
            },
        }
    for row_lines in symbol_rows:
        lines.extend(line for line in row_lines if line != "")
        lines.append("")
    return {
        "text": "\n".join(lines).rstrip() + "\n",
        "json": {
            "generated_at": timestamp,
            "summary": {
                "deployments_scanned": len(deployment_paths),
                "statuses": statuses,
                "symbols_with_incidents": incident_count,
                "total_fills": total_fills,
                "tradeable_now": tradeable_now,
                "blocked_now": blocked_now,
                "recent_incidents": recent_incidents[:5],
                "research_triggers": len(research_directives),
                "tca_overview": asdict(tca_report.overview) if tca_report.overview is not None else None,
                "worst_edge_retention": (
                    {
                        "symbol": impact_rows[0].symbol,
                        "candidate_name": impact_rows[0].candidate_name,
                        "edge_retention_pct": impact_rows[0].edge_retention_pct,
                    }
                    if impact_rows
                    else None
                ),
            },
            "reports": {
                "tca_report": str(tca_report.report_path),
                "tca_impact_report": str(impact_report),
                "tca_adaptation_impact_report": str(adaptation_impact_report),
                "market_interpreter_report": str(interpreter_report),
                "market_interpreter_research_queue": str(interpreter_research_report),
                "live_research_queue": str(research_queue_report),
                "live_improvement_activity_report": str(improvement_activity_report),
            },
            "symbols": symbol_json_rows,
        },
    }


def _latest_file(directory: Path, suffix: str) -> Path | None:
    if not directory.exists():
        return None
    files = sorted((path for path in directory.glob(f"*{suffix}") if path.is_file()), key=lambda item: item.name)
    return files[-1] if files else None


def _latest_journal_summary(path: Path | None) -> dict[str, object]:
    if path is None or not path.exists():
        return {"display": "", "blocked": False, "tradeable": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"display": "", "blocked": False, "tradeable": False}
    actions = payload.get("actions", [])
    if not isinstance(actions, list) or not actions:
        return {"display": "none", "blocked": False, "tradeable": False}
    parts: list[str] = []
    blocked = False
    tradeable = False
    for action in actions[:4]:
        candidate = str(action.get("candidate_name", "") or "")
        intended = str(action.get("intended_action", "") or "")
        tier = str(action.get("promotion_tier", "") or "")
        veto = str(action.get("veto_reason", "") or "")
        fragment = f"{candidate}:{intended}"
        if tier:
            fragment += f"[{tier}]"
        if veto:
            fragment += f" veto={veto}"
            blocked = True
        if intended.startswith("regime_blocked::") or intended.startswith("policy_blocked::"):
            blocked = True
        if intended in {"buy", "sell", "close_buy", "close_sell"}:
            tradeable = True
        elif intended not in {"", "hold"} and not intended.startswith("regime_blocked::") and not intended.startswith("policy_blocked::"):
            tradeable = True
        parts.append(fragment)
    return {"display": "; ".join(parts), "blocked": blocked, "tradeable": tradeable}


def _format_fill_summary(summary: dict[str, object] | None) -> str:
    if not summary:
        return "none"
    return (
        f"count={int(summary.get('fill_count', 0) or 0)} "
        f"last={summary.get('last_fill_at') or 'n/a'} "
        f"avg_spread={float(summary.get('avg_spread_points', 0.0) or 0.0):.2f} "
        f"avg_slippage_bps={float(summary.get('avg_slippage_bps', 0.0) or 0.0):.2f}"
    )
