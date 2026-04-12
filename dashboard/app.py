from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from quant_system.artifacts import LIVE_DIR, system_reports_dir


REPORTS_DIR = system_reports_dir()


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _load_activity_rows() -> list[dict]:
    rows: list[dict] = []
    for path in sorted(LIVE_DIR.glob("*/improvement_activity.jsonl")) if LIVE_DIR.exists() else []:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        except (json.JSONDecodeError, OSError):
            continue
    rows.sort(key=lambda row: str(row.get("recorded_at", "")), reverse=True)
    return rows


def _load_latest_journal_actions() -> list[dict]:
    rows: list[dict] = []
    for symbol_dir in sorted(LIVE_DIR.glob("*")) if LIVE_DIR.exists() else []:
        journal_dir = symbol_dir / "journals"
        if not journal_dir.exists():
            continue
        files = sorted(journal_dir.glob("*_journal.json"))
        if not files:
            continue
        latest = files[-1]
        payload = _load_json(latest)
        interpreter = payload.get("interpreter_state", {}) or {}
        for action in payload.get("actions", []) or []:
            if not isinstance(action, dict):
                continue
            rows.append(
                {
                    "symbol": payload.get("symbol", symbol_dir.name.upper()),
                    "journal": str(latest),
                    "candidate_name": action.get("candidate_name"),
                    "intended_action": action.get("intended_action"),
                    "veto_reason": action.get("veto_reason", ""),
                    "interpreter_reason": action.get("interpreter_reason", ""),
                    "interpreter_bias": action.get("interpreter_bias", interpreter.get("directional_bias", "")),
                    "interpreter_confidence": action.get("interpreter_confidence", interpreter.get("confidence", 0.0)),
                }
            )
    return rows


def _frame(rows) -> pd.DataFrame:
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _metric(label: str, value) -> None:
    st.metric(label, value)


def render_overview(health: dict, tca: dict, impact: dict, interpreter: dict) -> None:
    summary = health.get("summary", {})
    statuses = summary.get("statuses", {})
    overview = tca.get("overview", {}) or {}
    cols = st.columns(4)
    with cols[0]:
        _metric("Deployments", summary.get("deployments_scanned", 0))
        _metric("Fills", summary.get("total_fills", 0))
    with cols[1]:
        _metric("Live Ready", statuses.get("live_ready", 0))
        _metric("Reduced Risk", statuses.get("reduced_risk_only", 0))
    with cols[2]:
        _metric("Weighted Shortfall", f"{overview.get('weighted_shortfall_bps', 0.0):.2f} bps")
        _metric("Weighted Cost", f"{overview.get('weighted_cost_bps', 0.0):.2f} bps")
    with cols[3]:
        rows = impact.get("rows", [])
        median_retention = float(_frame(rows)["edge_retention_pct"].median()) if rows else 0.0
        _metric("Median Edge Retention", f"{median_retention:.1f}%")
        _metric("Interpreter Symbols", len(interpreter.get("states", [])))

    symbols = _frame(health.get("symbols", []))
    st.subheader("Symbols")
    if not symbols.empty:
        st.dataframe(symbols[["symbol", "status", "broker_symbol", "execution_adaptation", "latest_incident"]], width="stretch", hide_index=True)
    else:
        st.info("No symbol snapshot available.")


def render_execution(tca: dict) -> None:
    st.subheader("By Symbol")
    frame = _frame(tca.get("by_symbol", []))
    if frame.empty:
        st.info("No TCA data.")
    else:
        st.dataframe(frame, width="stretch", hide_index=True)
    st.subheader("Worst Fills")
    worst = _frame(tca.get("worst_fills", []))
    if worst.empty:
        st.info("No fill data.")
    else:
        st.dataframe(worst, width="stretch", hide_index=True)


def render_agents(impact: dict) -> None:
    frame = _frame(impact.get("rows", []))
    st.subheader("Agent Health")
    if frame.empty:
        st.info("No agent data.")
    else:
        st.dataframe(frame, width="stretch", hide_index=True)


def render_interpreter(interpreter: dict, research_bridge: dict) -> None:
    states = _frame(interpreter.get("states", []))
    st.subheader("Interpreter States")
    if states.empty:
        st.info("No interpreter states.")
    else:
        states = states.copy()
        view = states[[
            "symbol",
            "legacy_regime_label",
            "unified_regime_label",
            "directional_bias",
            "session_regime",
            "structure_regime",
            "execution_regime",
            "risk_posture",
            "confidence",
            "allowed_archetypes",
            "blocked_archetypes",
            "no_trade_reason",
            "explanation",
        ]]
        st.dataframe(view, width="stretch", hide_index=True)
    st.subheader("Interpreter Research Bridge")
    queue = _frame(research_bridge.get("items", []))
    if queue.empty:
        st.info("No interpreter-driven research directives.")
    else:
        st.dataframe(queue[["symbol", "priority", "labels", "suggested_experiments"]], width="stretch", hide_index=True)
    st.subheader("Latest Journal Actions")
    journal_actions = _frame(_load_latest_journal_actions())
    if journal_actions.empty:
        st.info("No live journals found.")
    else:
        st.dataframe(
            journal_actions[
                [
                    "symbol",
                    "candidate_name",
                    "intended_action",
                    "interpreter_reason",
                    "interpreter_bias",
                    "interpreter_confidence",
                    "veto_reason",
                    "journal",
                ]
            ],
            width="stretch",
            hide_index=True,
        )


def main() -> None:
    st.set_page_config(page_title="QuantGenerated Dashboard", layout="wide")
    st.title("QuantGenerated Dashboard")
    health = _load_json(REPORTS_DIR / "live_health_report.json")
    tca = _load_json(REPORTS_DIR / "trade_cost_analysis.json")
    impact = _load_json(REPORTS_DIR / "tca_impact_report.json")
    interpreter = _load_json(REPORTS_DIR / "market_interpreter_report.json")
    research_bridge = _load_json(REPORTS_DIR / "market_interpreter_research_queue.json")
    _load_activity_rows()  # warm path; later reusable when activity log returns to this tree

    tabs = st.tabs(["Overview", "Execution", "Agents", "Interpreter"])
    with tabs[0]:
        render_overview(health, tca, impact, interpreter)
    with tabs[1]:
        render_execution(tca)
    with tabs[2]:
        render_agents(impact)
    with tabs[3]:
        render_interpreter(interpreter, research_bridge)


if __name__ == "__main__":
    main()
