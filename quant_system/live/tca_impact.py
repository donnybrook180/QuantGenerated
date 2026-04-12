from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from quant_system.ai.storage import ExperimentStore
from quant_system.artifacts import DEPLOY_DIR, system_reports_dir
from quant_system.config import SystemConfig
from quant_system.live.deploy import load_symbol_deployment
from quant_system.tca import TCAAggregate, generate_tca_report


def _fmt_num(value: float, decimals: int = 2) -> str:
    return f"{value:.{decimals}f}"


def _find_strategy_row(rows: list[TCAAggregate], candidate_name: str) -> TCAAggregate | None:
    target = candidate_name.strip().lower()
    truncated = target[:31]
    for row in rows:
        label = row.label.strip().lower()
        if label == target or label == truncated:
            return row
        if target.startswith(label) or label.startswith(truncated):
            return row
    return None


def _find_candidate_row(store: ExperimentStore, deployment, candidate_name: str) -> dict[str, object] | None:
    candidates = store.list_symbol_research_candidates_for_run(int(deployment.research_run_id))
    for row in candidates:
        if str(row.get("candidate_name") or "") == candidate_name:
            return row
    return None


@dataclass(slots=True)
class StrategyImpactRow:
    symbol: str
    broker_symbol: str
    candidate_name: str
    research_expectancy: float
    research_closed_trades: int
    live_fill_count: int
    execution_drag_bps: float
    cost_bps: float
    total_drag_bps: float
    drag_share_pct: float
    edge_retention_pct: float
    fragility_label: str


def _fragility_label(edge_retention_pct: float, live_fill_count: int) -> str:
    if live_fill_count < 4:
        return "insufficient_live_data"
    if edge_retention_pct <= 0.0:
        return "untradeable"
    if edge_retention_pct < 40.0:
        return "fragile"
    if edge_retention_pct < 70.0:
        return "watch"
    return "safe"


def _estimate_edge_bps(candidate_row: dict[str, object]) -> float:
    expectancy = float(candidate_row.get("expectancy") or 0.0)
    avg_win = abs(float(candidate_row.get("avg_win") or 0.0))
    avg_loss = abs(float(candidate_row.get("avg_loss") or 0.0))
    scale = avg_win if avg_win > 0.0 else avg_loss
    if scale <= 0.0:
        realized = float(candidate_row.get("realized_pnl") or 0.0)
        closed = int(candidate_row.get("closed_trades") or 0)
        scale = abs(realized / closed) if closed > 0 else 0.0
    if scale <= 0.0:
        return 0.0
    return max(0.0, expectancy / scale * 10_000.0)


def build_tca_impact_rows(config: SystemConfig | None = None) -> list[StrategyImpactRow]:
    config = config or SystemConfig()
    store = ExperimentStore(config.ai.experiment_database_path, read_only=True)
    rows: list[StrategyImpactRow] = []
    for path in sorted(DEPLOY_DIR.glob("*/live.json")) if DEPLOY_DIR.exists() else []:
        deployment = load_symbol_deployment(path)
        tca_report = generate_tca_report(config, broker_symbol=deployment.broker_symbol)
        for strategy in deployment.strategies:
            candidate_row = _find_candidate_row(store, deployment, strategy.candidate_name)
            if candidate_row is None:
                continue
            strategy_tca = _find_strategy_row(tca_report.by_strategy, strategy.candidate_name)
            research_edge_bps = _estimate_edge_bps(candidate_row)
            execution_drag_bps = strategy_tca.weighted_shortfall_bps if strategy_tca is not None else 0.0
            cost_bps = strategy_tca.weighted_cost_bps if strategy_tca is not None else 0.0
            total_drag_bps = execution_drag_bps + cost_bps
            drag_share_pct = (total_drag_bps / research_edge_bps * 100.0) if research_edge_bps > 0.0 else 0.0
            edge_retention_pct = max(0.0, 100.0 - drag_share_pct) if research_edge_bps > 0.0 else 0.0
            live_fill_count = strategy_tca.fill_count if strategy_tca is not None else 0
            rows.append(
                StrategyImpactRow(
                    symbol=deployment.symbol,
                    broker_symbol=deployment.broker_symbol,
                    candidate_name=strategy.candidate_name,
                    research_expectancy=float(candidate_row.get("expectancy") or 0.0),
                    research_closed_trades=int(candidate_row.get("closed_trades") or 0),
                    live_fill_count=live_fill_count,
                    execution_drag_bps=execution_drag_bps,
                    cost_bps=cost_bps,
                    total_drag_bps=total_drag_bps,
                    drag_share_pct=drag_share_pct,
                    edge_retention_pct=edge_retention_pct,
                    fragility_label=_fragility_label(edge_retention_pct, live_fill_count),
                )
            )
    rows.sort(key=lambda row: (row.fragility_label, row.edge_retention_pct, -row.live_fill_count, row.symbol, row.candidate_name))
    return rows


def generate_tca_impact_report(config: SystemConfig | None = None) -> Path:
    config = config or SystemConfig()
    rows = build_tca_impact_rows(config)
    report_path = system_reports_dir() / "tca_impact_report.txt"
    lines = [
        "TCA impact report",
        f"generated_at: {datetime.now(UTC).isoformat()}",
        "",
        "Metric: estimated research edge vs live execution drag.",
        "Interpretation: drag_share_pct shows how much of expected edge execution is consuming.",
        "",
    ]
    if not rows:
        lines.append("No live deployments or candidate rows found.")
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        _write_tca_impact_json(report_path, rows)
        return report_path
    header = (
        f"{'symbol':<8} {'strategy':<24} {'livefills':>9} {'edge_ret%':>9} "
        f"{'drag%':>8} {'short_bps':>10} {'cost_bps':>9} {'label':<22}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for row in rows:
        lines.append(
            f"{row.symbol[:8]:<8} {row.candidate_name[:24]:<24} {row.live_fill_count:>9} "
            f"{_fmt_num(row.edge_retention_pct, 1):>9} {_fmt_num(row.drag_share_pct, 1):>8} "
            f"{_fmt_num(row.execution_drag_bps, 3):>10} {_fmt_num(row.cost_bps, 3):>9} {row.fragility_label:<22}"
        )
    lines.extend(["", "Details"])
    for row in rows:
        lines.extend(
            [
                f"{row.symbol} | {row.candidate_name}",
                f"  broker_symbol: {row.broker_symbol}",
                f"  research_expectancy: {_fmt_num(row.research_expectancy, 4)}",
                f"  research_closed_trades: {row.research_closed_trades}",
                f"  live_fill_count: {row.live_fill_count}",
                f"  execution_drag_bps: {_fmt_num(row.execution_drag_bps, 4)}",
                f"  cost_bps: {_fmt_num(row.cost_bps, 4)}",
                f"  total_drag_bps: {_fmt_num(row.total_drag_bps, 4)}",
                f"  drag_share_pct: {_fmt_num(row.drag_share_pct, 2)}",
                f"  edge_retention_pct: {_fmt_num(row.edge_retention_pct, 2)}",
                f"  verdict: {row.fragility_label}",
                "",
            ]
        )
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    _write_tca_impact_json(report_path, rows)
    return report_path


def _write_tca_impact_json(report_path: Path, rows: list[StrategyImpactRow]) -> None:
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "rows": [asdict(row) for row in rows],
        "report_path": str(report_path),
    }
    report_path.with_suffix(".json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
