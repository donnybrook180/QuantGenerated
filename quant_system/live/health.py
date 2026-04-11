from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from quant_system.ai.storage import ExperimentStore
from quant_system.artifacts import DEPLOY_DIR, system_reports_dir
from quant_system.config import SystemConfig
from quant_system.live.adaptation import adapt_deployment_for_execution, summarize_execution_adaptation
from quant_system.live.activity import generate_improvement_activity_report
from quant_system.live.autopsy import build_live_research_directives, generate_live_research_queue
from quant_system.live.deploy import load_symbol_deployment
from quant_system.live.tca_adaptation_impact import generate_tca_adaptation_impact_report
from quant_system.live.tca_impact import build_tca_impact_rows, generate_tca_impact_report
from quant_system.tca import generate_tca_report, summarize_tca_overview


def generate_live_health_report(config: SystemConfig | None = None) -> Path:
    config = config or SystemConfig()
    report_path = system_reports_dir() / "live_health_report.txt"
    report_path.write_text(build_live_health_report_text(config), encoding="utf-8")
    return report_path


def build_live_health_report_text(config: SystemConfig) -> str:
    store = ExperimentStore(config.ai.experiment_database_path, read_only=True)
    deployment_paths = sorted(DEPLOY_DIR.glob("*/live.json")) if DEPLOY_DIR.exists() else []
    tca_report = generate_tca_report(config)
    impact_rows = build_tca_impact_rows(config)
    impact_report = generate_tca_impact_report(config)
    adaptation_impact_report = generate_tca_adaptation_impact_report(config)
    research_directives = build_live_research_directives(config)
    research_queue_report = generate_live_research_queue(config)
    improvement_activity_report = generate_improvement_activity_report()
    timestamp = datetime.now(UTC).isoformat()
    statuses = {"live_ready": 0, "reduced_risk_only": 0, "research_only": 0}
    incident_count = 0
    total_fills = 0
    symbol_rows: list[list[str]] = []
    tradeable_now: list[str] = []
    blocked_now: list[str] = []
    recent_incidents: list[str] = []

    for path in deployment_paths:
        deployment = load_symbol_deployment(path)
        adapted_deployment, adaptation = adapt_deployment_for_execution(deployment, config)
        symbol = deployment.symbol
        live_symbol_dir = Path("artifacts") / "live" / path.parent.name
        latest_journal = _latest_file(live_symbol_dir / "journals", ".json")
        latest_incident = _latest_file(live_symbol_dir / "incidents", ".txt")
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
                f"  latest_actions: {latest_actions}" if latest_actions else "",
                "",
            ]
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
        return "\n".join(lines)
    for row_lines in symbol_rows:
        lines.extend(line for line in row_lines if line != "")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


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
