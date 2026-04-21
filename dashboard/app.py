from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from quant_system.artifacts import LIVE_DIR, system_reports_dir
from quant_system.ai.storage import ExperimentStore
from quant_system.config import SystemConfig


REPORTS_DIR = system_reports_dir()


def _metric_heat(value: object, *, good_high: float | None = None, good_low: float | None = None, warn_low: float | None = None, warn_high: float | None = None) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return ""
    if good_high is not None and numeric >= good_high:
        return "background-color: #d8f3dc; color: #1b4332;"
    if good_low is not None and numeric <= good_low:
        return "background-color: #d8f3dc; color: #1b4332;"
    if warn_low is not None and numeric <= warn_low:
        return "background-color: #ffd6d6; color: #7f1d1d;"
    if warn_high is not None and numeric >= warn_high:
        return "background-color: #ffd6d6; color: #7f1d1d;"
    return "background-color: #fff3bf; color: #6b4f00;"


def _recommended_style(value: object) -> str:
    return "background-color: #95d5b2; color: #081c15; font-weight: 700;" if bool(value) else ""


def _status_style(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"live_ready", "accepted", "healthy"}:
        return "background-color: #d8f3dc; color: #1b4332; font-weight: 700;"
    if normalized in {"reduced_risk_only", "degraded", "warning"}:
        return "background-color: #fff3bf; color: #6b4f00; font-weight: 700;"
    if normalized in {"research_only", "reject", "failed", "blocked"}:
        return "background-color: #ffd6d6; color: #7f1d1d; font-weight: 700;"
    return ""


def _bias_style(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if "long" in normalized or "bull" in normalized:
        return "background-color: #d8f3dc; color: #1b4332;"
    if "short" in normalized or "bear" in normalized:
        return "background-color: #ffd6d6; color: #7f1d1d;"
    return "background-color: #fff3bf; color: #6b4f00;"


def _posture_style(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if "aggressive" in normalized or "risk_on" in normalized:
        return "background-color: #d8f3dc; color: #1b4332;"
    if "defensive" in normalized or "risk_off" in normalized:
        return "background-color: #ffd6d6; color: #7f1d1d;"
    return "background-color: #fff3bf; color: #6b4f00;"


def _style_symbols(frame: pd.DataFrame):
    style = frame.style.map(_status_style, subset=["status"])
    if "strategy_count" in frame.columns:
        style = style.map(lambda value: _metric_heat(value, good_high=1.0, warn_low=0.0), subset=["strategy_count"])
    return style


def _style_interpreter_states(frame: pd.DataFrame):
    return (
        frame.style
        .map(_bias_style, subset=["directional_bias"])
        .map(_posture_style, subset=["risk_posture"])
        .map(lambda value: _metric_heat(value, good_high=0.7, warn_low=0.35), subset=["confidence"])
        .format({"confidence": "{:.2f}"})
    )


def _priority_style(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"high", "urgent", "critical"}:
        return "background-color: #ffd6d6; color: #7f1d1d; font-weight: 700;"
    if normalized in {"medium", "normal"}:
        return "background-color: #fff3bf; color: #6b4f00; font-weight: 700;"
    if normalized in {"low"}:
        return "background-color: #d8f3dc; color: #1b4332; font-weight: 700;"
    return ""


def _action_style(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if any(token in normalized for token in ("block", "veto", "stop", "no_trade")):
        return "background-color: #ffd6d6; color: #7f1d1d;"
    if any(token in normalized for token in ("allow", "buy", "long", "go")):
        return "background-color: #d8f3dc; color: #1b4332;"
    return "background-color: #fff3bf; color: #6b4f00;"


def _style_interpreter_bridge(frame: pd.DataFrame):
    style = frame.style
    if "priority" in frame.columns:
        style = style.map(_priority_style, subset=["priority"])
    return style


def _style_journal_actions(frame: pd.DataFrame):
    style = frame.style
    if "intended_action" in frame.columns:
        style = style.map(_action_style, subset=["intended_action"])
    if "interpreter_bias" in frame.columns:
        style = style.map(_bias_style, subset=["interpreter_bias"])
    if "interpreter_confidence" in frame.columns:
        style = style.map(lambda value: _metric_heat(value, good_high=0.7, warn_low=0.35), subset=["interpreter_confidence"])
        style = style.format({"interpreter_confidence": "{:.2f}"})
    if "veto_reason" in frame.columns:
        style = style.map(lambda value: "background-color: #ffd6d6; color: #7f1d1d;" if str(value or "").strip() else "", subset=["veto_reason"])
    return style


def _style_execution_frame(frame: pd.DataFrame):
    style = frame.style
    for column in [name for name in ("weighted_shortfall_bps", "shortfall_bps", "weighted_touch_slippage_bps", "touch_slippage_bps", "cost_bps", "execution_drag_bps", "spread_bps", "slippage_bps") if name in frame.columns]:
        style = style.map(lambda value: _metric_heat(value, good_low=2.0, warn_high=8.0), subset=[column])
    for column in [name for name in ("adverse_touch_fill_rate_pct", "drag_share_pct") if name in frame.columns]:
        style = style.map(lambda value: _metric_heat(value, good_low=25.0, warn_high=50.0), subset=[column])
    for column in [name for name in ("edge_retention_pct",) if name in frame.columns]:
        style = style.map(lambda value: _metric_heat(value, good_high=70.0, warn_low=40.0), subset=[column])
    return style


def _fragility_style(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"robust", "healthy", "stable"}:
        return "background-color: #d8f3dc; color: #1b4332; font-weight: 700;"
    if normalized in {"watch", "fragile", "warning"}:
        return "background-color: #fff3bf; color: #6b4f00; font-weight: 700;"
    if normalized in {"broken", "critical", "degraded"}:
        return "background-color: #ffd6d6; color: #7f1d1d; font-weight: 700;"
    return ""


def _style_agents_frame(frame: pd.DataFrame):
    style = frame.style
    for column in [name for name in ("raw_live_fill_count", "live_fill_count") if name in frame.columns]:
        style = style.map(lambda value: _metric_heat(value, good_high=20.0, warn_low=5.0), subset=[column])
    for column in [name for name in ("edge_retention_pct",) if name in frame.columns]:
        style = style.map(lambda value: _metric_heat(value, good_high=70.0, warn_low=40.0), subset=[column])
    if "drag_share_pct" in frame.columns:
        style = style.map(lambda value: _metric_heat(value, good_low=20.0, warn_high=50.0), subset=["drag_share_pct"])
    for column in [name for name in ("execution_drag_bps", "cost_bps") if name in frame.columns]:
        style = style.map(lambda value: _metric_heat(value, good_low=2.0, warn_high=8.0), subset=[column])
    if "fragility_label" in frame.columns:
        style = style.map(_fragility_style, subset=["fragility_label"])
    if "result_index_change_pct" in frame.columns:
        style = style.map(lambda value: _metric_heat(value, good_high=0.0, warn_low=0.0), subset=["result_index_change_pct"])
        style = style.format({"result_index_change_pct": "{:.2f}"})
    return style


def _style_research_metrics(frame: pd.DataFrame):
    return (
        frame.style
        .map(_recommended_style, subset=["recommended"])
        .map(lambda value: _metric_heat(value, good_high=0.0, warn_low=0.0), subset=["realized_pnl", "expectancy", "mc_pnl_median", "mc_pnl_p05"])
        .map(lambda value: _metric_heat(value, good_high=1.2, warn_low=1.0), subset=["profit_factor", "validation_profit_factor", "test_profit_factor"])
        .map(lambda value: _metric_heat(value, good_high=0.3, warn_low=0.0), subset=["sharpe_ratio", "sortino_ratio", "calmar_ratio"])
        .map(lambda value: _metric_heat(value, good_high=70.0, warn_low=40.0), subset=["walk_forward_pass_rate_pct"])
        .map(lambda value: _metric_heat(value, good_high=10.0, warn_low=1.0), subset=["closed_trades", "mc_simulations"])
        .map(lambda value: _metric_heat(value, good_low=5.0, warn_high=15.0), subset=["max_drawdown_pct", "mc_max_drawdown_pct_median", "mc_max_drawdown_pct_p95"])
        .map(lambda value: _metric_heat(value, good_low=10.0, warn_high=25.0), subset=["mc_loss_probability_pct"])
        .format(
            {
                "realized_pnl": "{:.2f}",
                "profit_factor": "{:.2f}",
                "max_drawdown_pct": "{:.2f}",
                "expectancy": "{:.2f}",
                "sharpe_ratio": "{:.2f}",
                "sortino_ratio": "{:.2f}",
                "calmar_ratio": "{:.2f}",
                "mc_pnl_median": "{:.2f}",
                "mc_pnl_p05": "{:.2f}",
                "mc_pnl_p95": "{:.2f}",
                "mc_max_drawdown_pct_median": "{:.2f}",
                "mc_max_drawdown_pct_p95": "{:.2f}",
                "mc_loss_probability_pct": "{:.1f}",
                "validation_profit_factor": "{:.2f}",
                "test_profit_factor": "{:.2f}",
                "walk_forward_pass_rate_pct": "{:.1f}",
            }
        )
    )


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


def _load_activity_rows() -> list[dict]:
    rows: list[dict] = []
    for path in sorted(LIVE_DIR.glob("*/improvement_activity.jsonl")) if LIVE_DIR.exists() else []:
        rows.extend(_load_jsonl(path))
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


def _frame(rows: list[dict] | list[object]) -> pd.DataFrame:
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _load_latest_symbol_research_rows() -> list[dict]:
    config = SystemConfig()
    store = ExperimentStore(config.ai.experiment_database_path, read_only=True)
    rows: list[dict] = []
    for profile_name in store.list_symbol_research_profiles():
        if not profile_name.startswith("symbol::"):
            continue
        latest = store.get_latest_symbol_research_run(profile_name)
        if latest is None:
            continue
        for candidate in store.list_latest_symbol_research_candidates(profile_name):
            rows.append(
                {
                    "profile_name": profile_name,
                    "symbol": str(latest.get("broker_symbol") or latest.get("data_symbol") or profile_name),
                    "candidate_name": candidate.get("candidate_name", ""),
                    "recommended": bool(candidate.get("recommended", False)),
                    "realized_pnl": float(candidate.get("realized_pnl", 0.0) or 0.0),
                    "closed_trades": int(candidate.get("closed_trades", 0) or 0),
                    "profit_factor": float(candidate.get("profit_factor", 0.0) or 0.0),
                    "max_drawdown_pct": float(candidate.get("max_drawdown_pct", 0.0) or 0.0),
                    "expectancy": float(candidate.get("expectancy", 0.0) or 0.0),
                    "sharpe_ratio": float(candidate.get("sharpe_ratio", 0.0) or 0.0),
                    "sortino_ratio": float(candidate.get("sortino_ratio", 0.0) or 0.0),
                    "calmar_ratio": float(candidate.get("calmar_ratio", 0.0) or 0.0),
                    "mc_simulations": int(candidate.get("mc_simulations", 0) or 0),
                    "mc_pnl_median": float(candidate.get("mc_pnl_median", 0.0) or 0.0),
                    "mc_pnl_p05": float(candidate.get("mc_pnl_p05", 0.0) or 0.0),
                    "mc_pnl_p95": float(candidate.get("mc_pnl_p95", 0.0) or 0.0),
                    "mc_max_drawdown_pct_median": float(candidate.get("mc_max_drawdown_pct_median", 0.0) or 0.0),
                    "mc_max_drawdown_pct_p95": float(candidate.get("mc_max_drawdown_pct_p95", 0.0) or 0.0),
                    "mc_loss_probability_pct": float(candidate.get("mc_loss_probability_pct", 0.0) or 0.0),
                    "validation_profit_factor": float(candidate.get("validation_profit_factor", 0.0) or 0.0),
                    "test_profit_factor": float(candidate.get("test_profit_factor", 0.0) or 0.0),
                    "walk_forward_pass_rate_pct": float(candidate.get("walk_forward_pass_rate_pct", 0.0) or 0.0),
                }
            )
    rows.sort(
        key=lambda row: (
            row["recommended"],
            row["sortino_ratio"],
            row["sharpe_ratio"],
            row["calmar_ratio"],
            row["profit_factor"],
            row["realized_pnl"],
        ),
        reverse=True,
    )
    return rows


def _metric(label: str, value, help_text: str = "") -> None:
    st.metric(label, value, help=help_text or None)


def render_overview(
    health: dict,
    tca: dict,
    impact: dict,
    queue: dict,
    activity_rows: list[dict],
    interpreter: dict,
) -> None:
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
        impact_rows = impact.get("rows", [])
        median_retention = float(pd.DataFrame(impact_rows)["edge_retention_pct"].median()) if impact_rows else 0.0
        _metric("Median Edge Retention", f"{median_retention:.1f}%")
        _metric("Research Triggers", len(queue.get("items", [])))

    st.subheader("Symbols")
    symbols = _frame(health.get("symbols", []))
    if not symbols.empty:
        columns = [
            "symbol",
            "status",
            "broker_symbol",
            "strategy_count",
            "execution_adaptation",
            "execution_guardrail",
            "latest_incident",
        ]
        st.dataframe(_style_symbols(symbols[columns]), width="stretch", hide_index=True)
    else:
        st.info("No symbol snapshot available.")

    st.subheader("Recent Activity")
    activity = _frame(activity_rows[:20])
    if not activity.empty:
        view = activity[["recorded_at", "symbol", "category", "action", "candidate_name", "reason"]]
        st.dataframe(view, width="stretch", hide_index=True)
    else:
        st.info("No adaptation or research activity recorded yet.")

    st.subheader("Interpreter Coverage")
    states = _frame(interpreter.get("states", []))
    if not states.empty:
        state_view = states[["symbol", "unified_regime_label", "directional_bias", "risk_posture", "confidence"]]
        st.dataframe(_style_interpreter_states(state_view), width="stretch", hide_index=True)
    else:
        st.info("No interpreter states available.")


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
        frame = _frame(tca.get(key, []))
        if frame.empty:
            st.info("No data.")
        else:
            st.dataframe(_style_execution_frame(frame), width="stretch", hide_index=True)


def render_agents(impact: dict, adaptation_impact: dict) -> None:
    impact_frame = _frame(impact.get("rows", []))
    adaptation_frame = _frame(adaptation_impact.get("rows", []))
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
    agent_view = merged[
        [
            "symbol",
            "candidate_name",
            "raw_live_fill_count",
            "live_fill_count",
            "edge_retention_pct",
            "drag_share_pct",
            "execution_drag_bps",
            "cost_bps",
            "fragility_label",
            "adaptation_action",
            "result_index_change_pct",
        ]
    ]
    st.dataframe(_style_agents_frame(agent_view), width="stretch", hide_index=True)

    st.subheader("Agent Distribution")
    counts = merged["fragility_label"].value_counts().rename_axis("label").reset_index(name="count")
    st.bar_chart(counts.set_index("label"))


def render_research(queue: dict, activity_rows: list[dict]) -> None:
    st.subheader("Latest Research Metrics")
    research_metrics = _frame(_load_latest_symbol_research_rows())
    if research_metrics.empty:
        st.info("No symbol research candidates available.")
    else:
        search_term = st.text_input("Filter research", value="", placeholder="BTC, EURUSD, JP225...")
        if search_term.strip():
            needle = search_term.strip().lower()
            mask = research_metrics.apply(
                lambda row: any(needle in str(value).lower() for value in row.values),
                axis=1,
            )
            research_metrics = research_metrics[mask]

        if research_metrics.empty:
            st.info("No research candidates match the current filter.")
            return

        research_view = research_metrics[
            [
                "symbol",
                "candidate_name",
                "recommended",
                "realized_pnl",
                "closed_trades",
                "profit_factor",
                "max_drawdown_pct",
                "expectancy",
                "sharpe_ratio",
                "sortino_ratio",
                "calmar_ratio",
                "mc_simulations",
                "mc_pnl_median",
                "mc_pnl_p05",
                "mc_pnl_p95",
                "mc_max_drawdown_pct_median",
                "mc_max_drawdown_pct_p95",
                "mc_loss_probability_pct",
                "validation_profit_factor",
                "test_profit_factor",
                "walk_forward_pass_rate_pct",
            ]
        ]
        st.dataframe(
            _style_research_metrics(research_view),
            width="stretch",
            hide_index=True,
        )

    queue_frame = _frame(queue.get("items", []))
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
    research_frame = _frame(research_rows[:50])
    if research_frame.empty:
        st.info("No research activity recorded yet.")
    else:
        st.dataframe(
            research_frame[["recorded_at", "symbol", "category", "action", "candidate_name", "reason"]],
            width="stretch",
            hide_index=True,
        )


def render_interpreter(interpreter: dict, research_bridge: dict) -> None:
    states = _frame(interpreter.get("states", []))
    st.subheader("Interpreter States")
    if states.empty:
        st.info("No interpreter states.")
    else:
        state_view = states[
            [
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
            ]
        ]
        st.dataframe(_style_interpreter_states(state_view), width="stretch", hide_index=True)

    st.subheader("Interpreter Research Bridge")
    queue = _frame(research_bridge.get("items", []))
    if queue.empty:
        st.info("No interpreter-driven research directives.")
    else:
        columns = [column for column in ["symbol", "priority", "labels", "suggested_experiments"] if column in queue.columns]
        st.dataframe(_style_interpreter_bridge(queue[columns]), width="stretch", hide_index=True)

    st.subheader("Latest Journal Actions")
    journal_actions = _frame(_load_latest_journal_actions())
    if journal_actions.empty:
        st.info("No live journals found.")
    else:
        journal_view = journal_actions[
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
        ]
        st.dataframe(_style_journal_actions(journal_view), width="stretch", hide_index=True)


def main() -> None:
    st.set_page_config(page_title="QuantGenerated Dashboard", layout="wide")
    st.title("QuantGenerated Dashboard")
    st.caption("Research -> live trading -> TCA -> adaptation -> autopsy -> interpreter -> research")

    health = _load_json(REPORTS_DIR / "live_health_report.json")
    tca = _load_json(REPORTS_DIR / "trade_cost_analysis.json")
    impact = _load_json(REPORTS_DIR / "tca_impact_report.json")
    adaptation_impact = _load_json(REPORTS_DIR / "tca_adaptation_impact_report.json")
    queue = _load_json(REPORTS_DIR / "live_research_queue.json")
    interpreter = _load_json(REPORTS_DIR / "market_interpreter_report.json")
    research_bridge = _load_json(REPORTS_DIR / "market_interpreter_research_queue.json")
    activity_rows = _load_activity_rows()

    st.sidebar.header("Inputs")
    st.sidebar.write(f"Reports dir: `{REPORTS_DIR}`")
    st.sidebar.write(f"Activity dir: `{LIVE_DIR}`")

    tabs = st.tabs(["Overview", "Execution", "Agents", "Research", "Interpreter"])
    with tabs[0]:
        render_overview(health, tca, impact, queue, activity_rows, interpreter)
    with tabs[1]:
        render_execution(tca)
    with tabs[2]:
        render_agents(impact, adaptation_impact)
    with tabs[3]:
        render_research(queue, activity_rows)
    with tabs[4]:
        render_interpreter(interpreter, research_bridge)


if __name__ == "__main__":
    main()
