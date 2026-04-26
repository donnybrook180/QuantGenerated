from __future__ import annotations

import hashlib
import json
import os
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from quant_system.artifacts import LIVE_DIR, live_symbol_dir, system_reports_dir


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _activity_log_path(symbol: str, venue_key: str) -> Path:
    return live_symbol_dir(symbol, venue_key) / "improvement_activity.jsonl"


def _activity_state_path(symbol: str, venue_key: str) -> Path:
    return live_symbol_dir(symbol, venue_key) / "improvement_activity_state.json"


def _load_state(symbol: str, venue_key: str) -> dict[str, Any]:
    path = _activity_state_path(symbol, venue_key)
    if not path.exists():
        return {"dedupe": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"dedupe": {}}
    if not isinstance(payload, dict):
        return {"dedupe": {}}
    payload.setdefault("dedupe", {})
    return payload


def _save_state(symbol: str, venue_key: str, state: dict[str, Any]) -> None:
    _activity_state_path(symbol, venue_key).write_text(json.dumps(state, indent=2), encoding="utf-8")


def _event_digest(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _append_event(symbol: str, venue_key: str, payload: dict[str, Any]) -> bool:
    state = _load_state(symbol, venue_key)
    dedupe: dict[str, str] = dict(state.get("dedupe", {}))
    cooldown_seconds = _env_int("LIVE_ACTIVITY_EVENT_COOLDOWN_SECONDS", 15)
    event_core = {
        "category": payload.get("category"),
        "action": payload.get("action"),
        "symbol": payload.get("symbol"),
        "broker_symbol": payload.get("broker_symbol"),
        "candidate_name": payload.get("candidate_name"),
        "reason": payload.get("reason"),
        "location": payload.get("location"),
    }
    digest = _event_digest(event_core)
    now = datetime.now(UTC)
    last_seen_raw = dedupe.get(digest)
    if last_seen_raw:
        try:
            last_seen = datetime.fromisoformat(last_seen_raw)
            if now - last_seen < timedelta(seconds=cooldown_seconds):
                return False
        except ValueError:
            pass
    payload = dict(payload)
    payload["venue_key"] = venue_key
    payload["recorded_at"] = now.isoformat()
    with _activity_log_path(symbol, venue_key).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, default=str) + "\n")
    dedupe[digest] = payload["recorded_at"]
    state["dedupe"] = dedupe
    _save_state(symbol, venue_key, state)
    return True


def record_adaptation_result(result) -> int:
    recorded = 0
    for item in result.strategy_actions:
        if item.action in {"unchanged", "promote_healthy"}:
            continue
        payload = {
            "category": "adaptation",
            "action": item.action,
            "symbol": result.symbol,
            "broker_symbol": result.broker_symbol,
            "candidate_name": item.candidate_name,
            "reason": item.reason,
            "location": str(result.report_path),
            "fill_count": item.fill_count,
            "base_weight_scale": item.base_weight_scale,
            "risk_scale": item.risk_scale,
            "local_rank_label": item.local_rank_label,
            "guardrail_reason": result.guardrail_reason,
        }
        recorded += 1 if _append_event(result.symbol, result.venue_key, payload) else 0
    if result.guardrail_reason != "none":
        payload = {
            "category": "guardrail",
            "action": result.action,
            "symbol": result.symbol,
            "broker_symbol": result.broker_symbol,
            "candidate_name": "",
            "reason": result.guardrail_reason,
            "location": str(result.report_path),
            "fill_count": result.fill_count,
        }
        recorded += 1 if _append_event(result.symbol, result.venue_key, payload) else 0
    return recorded


def record_research_directives(directives: list[Any]) -> int:
    recorded = 0
    for item in directives:
        payload = {
            "category": "research_trigger",
            "action": item.escalation_mode,
            "symbol": item.symbol,
            "broker_symbol": item.broker_symbol,
            "candidate_name": item.candidate_name,
            "reason": ", ".join(item.failure_labels),
            "location": str(item.report_path),
            "priority": item.priority,
            "edge_retention_pct": item.edge_retention_pct,
            "live_fill_count": item.live_fill_count,
            "structured_experiments": [experiment.experiment_type for experiment in item.structured_experiments],
        }
        recorded += 1 if _append_event(item.symbol, item.venue_key, payload) else 0
    return recorded


def record_research_run(
    *,
    symbol: str,
    venue_key: str,
    broker_symbol: str,
    candidate_name: str,
    experiment_type: str,
    command: list[str],
    return_code: int,
) -> bool:
    payload = {
        "category": "research_run",
        "action": experiment_type,
        "symbol": symbol,
        "broker_symbol": broker_symbol,
        "candidate_name": candidate_name,
        "reason": f"auto_research_rc={return_code}",
        "location": " ".join(command),
        "return_code": return_code,
    }
    return _append_event(symbol, venue_key, payload)


def _load_activity_events() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in sorted(LIVE_DIR.rglob("improvement_activity.jsonl")) if LIVE_DIR.exists() else []:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                if isinstance(payload, dict):
                    events.append(payload)
        except (OSError, json.JSONDecodeError):
            continue
    events.sort(key=lambda row: str(row.get("recorded_at", "")), reverse=True)
    return events


def generate_improvement_activity_report() -> Path:
    events = _load_activity_events()
    report_path = system_reports_dir() / "live_improvement_activity_report.txt"
    lines = [
        "Live improvement activity report",
        f"generated_at: {datetime.now(UTC).isoformat()}",
        "",
    ]
    if not events:
        lines.append("No adaptation or research activity has been recorded yet.")
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report_path

    category_counts = Counter(str(item.get("category", "unknown")) for item in events)
    action_counts = Counter(f"{item.get('category', 'unknown')}::{item.get('action', 'unknown')}" for item in events)
    lines.extend(
        [
            f"Total events: {len(events)}",
            "By category: " + ", ".join(f"{key}={value}" for key, value in sorted(category_counts.items())),
            "Top actions: " + ", ".join(f"{key}={value}" for key, value in action_counts.most_common(10)),
            "",
            "By symbol:",
        ]
    )

    events_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in events:
        events_by_symbol[str(item.get("symbol", "unknown"))].append(item)

    for symbol in sorted(events_by_symbol):
        symbol_events = events_by_symbol[symbol]
        symbol_action_counts = Counter(f"{item.get('category', 'unknown')}::{item.get('action', 'unknown')}" for item in symbol_events)
        last_adaptation = next((item for item in symbol_events if item.get("category") == "adaptation"), None)
        last_research_trigger = next((item for item in symbol_events if item.get("category") == "research_trigger"), None)
        last_research_run = next((item for item in symbol_events if item.get("category") == "research_run"), None)
        broker_symbol = next((str(item.get("broker_symbol", "")) for item in symbol_events if item.get("broker_symbol")), "")
        venue_key = next((str(item.get("venue_key", "")) for item in symbol_events if item.get("venue_key")), "")
        lines.append(
            f"{symbol}: events={len(symbol_events)} broker_symbol={broker_symbol or 'n/a'} venue={venue_key or 'n/a'}"
        )
        lines.append("  actions: " + ", ".join(f"{key}={value}" for key, value in symbol_action_counts.most_common(8)))
        if last_adaptation is not None:
            lines.append(
                "  last_demotion: "
                f"{last_adaptation.get('recorded_at')} {last_adaptation.get('candidate_name')} "
                f"{last_adaptation.get('action')} reason={last_adaptation.get('reason')}"
            )
        else:
            lines.append("  last_demotion: none")
        if last_research_trigger is not None:
            lines.append(
                "  last_research_trigger: "
                f"{last_research_trigger.get('recorded_at')} {last_research_trigger.get('candidate_name')} "
                f"{last_research_trigger.get('action')} reason={last_research_trigger.get('reason')}"
            )
        else:
            lines.append("  last_research_trigger: none")
        if last_research_run is not None:
            lines.append(
                "  last_research_run: "
                f"{last_research_run.get('recorded_at')} {last_research_run.get('candidate_name')} "
                f"{last_research_run.get('action')} reason={last_research_run.get('reason')}"
            )
        else:
            lines.append("  last_research_run: none")
        lines.append("")

    lines.append("Recent events:")
    for item in events[:20]:
        lines.append(
            f"- {item.get('recorded_at')} {item.get('symbol')} "
            f"{item.get('category')}::{item.get('action')} "
            f"{item.get('candidate_name') or '-'} "
            f"where={item.get('location')}"
        )

    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return report_path
