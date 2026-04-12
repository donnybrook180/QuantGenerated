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


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    except (json.JSONDecodeError, OSError):
        return []
    return rows


def _report_path(name: str) -> Path:
    return REPORTS_DIR / name


def _load_activity_rows() -> list[dict]:
    rows: list[dict] = []
    for path in sorted(LIVE_DIR.glob("*/improvement_activity.jsonl")) if LIVE_DIR.exists() else []:
        rows.extend(_load_jsonl(path))
    rows.sort(key=lambda row: str(row.get("recorded_at", "")), reverse=True)
    return rows


def _to_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _metric(label: str, value, help_text: str = "") -> None:
    st.metric(label, value, help=help_text or None)


def render_overview(health: dict, tca: dict, impact: dict, queue: dict, activity_rows: list[dict]) -> None:
    summary = health.get("summary", {})
    statuses = summary.get("statuses", {})
    overview = tca.get("overview", {}) or {}
    cols = st.columns(4)
    with cols[0]:
        _metric("Deployments", summary.get("deployments_scanned", 0))
        _metric("Fills", summary.get("total_fills", 0))
    with cols[1]:
        _metric("Live Ready", statuses.get("live_ready", 0))
        _metric("Blocked", len(summary.get("blocked_now", [])))
    with cols[2]:
        _metric("Weighted Shortfall", f"{overview.get('weighted_shortfall_bps', 0.0):.2f} bps")
        _metric("Weighted Cost", f"{overview.get('weighted_cost_bps', 0.0):.2f} bps")
    with cols[3]:
        impact_rows = impact.get("rows", [])
        median_retention = 0.0
        if impact_rows:
            median_retention = float(pd.DataFrame(impact_rows)["edge_retention_pct"].median())
        _metric("Median Edge Retention", f"{median_retention:.1f}%")
        _metric("Research Triggers", len(queue.get("items", [])))

    st.subheader("Symbols")
    symbols = _to_frame(health.get("symbols", []))
    if not symbols.empty:
        view = symbols[["symbol", "status", "broker_symbol", "strategy_count", "execution_adaptation", "execution_guardrail", "latest_incident"]]
        st.dataframe(view, width="stretch", hide_index=True)
    else:
        st.info("No symbol snapshot available.")

    st.subheader("Recent Activity")
    activity = _to_frame(activity_rows[:20])
    if not activity.empty:
        view = activity[["recorded_at", "symbol", "category", "action", "candidate_name", "reason"]]
        st.dataframe(view, width="stretch", hide_index=True)
    else:
        st.info("No adaptation or research activity recorded yet.")


def render_execution(tca: dict) -> None:
    overview = tca.get("overview", {}) or {}
    cols = st.columns(4)
    with cols[0]:
        _metric("Fills", overview.get("fill_count", 0))
    with cols[1]:
        _metric("Touch Slippage", f"{overview.get('weighted_touch_slippage_bps', 0.0):.2f} bps")
    with cols[2]:
        _metric("Shortfall", f"{overview.get('weighted_shortfall_bps', 0.0):.2f} bps")
    with cols[3]:
        _metric("Adverse Fill Rate", f"{overview.get('adverse_touch_fill_rate_pct', 0.0):.1f}%")

    for title, key in [
        ("By Symbol", "by_symbol"),
        ("By Strategy", "by_strategy"),
        ("By Hour", "by_hour"),
        ("Worst Fills", "worst_fills"),
    ]:
        st.subheader(title)
        frame = _to_frame(tca.get(key, []))
        if frame.empty:
            st.info("No data.")
        else:
            st.dataframe(frame, width="stretch", hide_index=True)


def render_agents(impact: dict, adaptation_impact: dict, health: dict) -> None:
    impact_frame = _to_frame(impact.get("rows", []))
    adaptation_frame = _to_frame(adaptation_impact.get("rows", []))
    if impact_frame.empty:
        st.info("No agent health data available yet.")
        return

    if not adaptation_frame.empty:
        merged = impact_frame.merge(
            adaptation_frame[["symbol", "candidate_name", "adaptation_action", "result_index_change_pct"]],
            on=["symbol", "candidate_name"],
            how="left",
        )
    else:
        merged = impact_frame

    st.subheader("Agent Health")
    st.dataframe(
        merged[
            [
                "symbol",
                "candidate_name",
                "live_fill_count",
                "edge_retention_pct",
                "drag_share_pct",
                "execution_drag_bps",
                "cost_bps",
                "fragility_label",
                "adaptation_action",
                "result_index_change_pct",
            ]
        ],
        width="stretch",
        hide_index=True,
    )

    st.subheader("Agent Distribution")
    counts = merged["fragility_label"].value_counts().rename_axis("label").reset_index(name="count")
    st.bar_chart(counts.set_index("label"))


def render_research(queue: dict, activity_rows: list[dict]) -> None:
    queue_frame = _to_frame(queue.get("items", []))
    st.subheader("Research Queue")
    if queue_frame.empty:
        st.info("No research triggers.")
    else:
        st.dataframe(
            queue_frame[
                [
                    "symbol",
                    "candidate_name",
                    "priority",
                    "escalation_mode",
                    "edge_retention_pct",
                    "live_fill_count",
                    "failure_labels",
                ]
            ],
            width="stretch",
            hide_index=True,
        )

    st.subheader("Research Activity")
    research_rows = [row for row in activity_rows if str(row.get("category", "")).startswith("research")]
    research_frame = _to_frame(research_rows[:50])
    if research_frame.empty:
        st.info("No research activity recorded yet.")
    else:
        st.dataframe(
            research_frame[["recorded_at", "symbol", "category", "action", "candidate_name", "reason"]],
            width="stretch",
            hide_index=True,
        )


def main() -> None:
    st.set_page_config(page_title="QuantGenerated Dashboard", layout="wide")
    st.title("QuantGenerated Dashboard")
    st.caption("Research -> live trading -> TCA -> adaptation -> autopsy -> research")

    health = _load_json(_report_path("live_health_report.json"))
    tca = _load_json(_report_path("trade_cost_analysis.json"))
    impact = _load_json(_report_path("tca_impact_report.json"))
    adaptation_impact = _load_json(_report_path("tca_adaptation_impact_report.json"))
    queue = _load_json(_report_path("live_research_queue.json"))
    activity_rows = _load_activity_rows()

    st.sidebar.header("Inputs")
    st.sidebar.write(f"Reports dir: `{REPORTS_DIR}`")
    st.sidebar.write(f"Activity dir: `{LIVE_DIR}`")

    tabs = st.tabs(["Overview", "Execution", "Agents", "Research"])
    with tabs[0]:
        render_overview(health, tca, impact, queue, activity_rows)
    with tabs[1]:
        render_execution(tca)
    with tabs[2]:
        render_agents(impact, adaptation_impact, health)
    with tabs[3]:
        render_research(queue, activity_rows)


if __name__ == "__main__":
    main()
