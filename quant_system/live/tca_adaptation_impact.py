from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from quant_system.artifacts import DEPLOY_DIR, system_reports_dir
from quant_system.config import SystemConfig
from quant_system.live.adaptation import adapt_deployment_for_execution
from quant_system.live.deploy import load_symbol_deployment
from quant_system.live.tca_impact import build_tca_impact_rows


def _fmt_num(value: float, decimals: int = 2) -> str:
    return f"{value:.{decimals}f}"


@dataclass(slots=True)
class TCAAdaptationImpactRow:
    symbol: str
    candidate_name: str
    live_fill_count: int
    edge_retention_pct: float
    baseline_base_weight: float
    adapted_base_weight: float
    baseline_max_risk: float
    adapted_max_risk: float
    baseline_result_index: float
    adapted_result_index: float
    result_index_change_pct: float
    adaptation_action: str
    adaptation_reason: str


def build_tca_adaptation_impact_rows(config: SystemConfig | None = None) -> list[TCAAdaptationImpactRow]:
    config = config or SystemConfig()
    impact_rows = {
        (row.symbol, row.candidate_name): row
        for row in build_tca_impact_rows(config)
    }
    rows: list[TCAAdaptationImpactRow] = []
    for path in sorted(DEPLOY_DIR.glob("*/live.json")) if DEPLOY_DIR.exists() else []:
        baseline = load_symbol_deployment(path)
        adapted, adaptation = adapt_deployment_for_execution(baseline, config)
        adapted_actions = {item.candidate_name: item for item in adaptation.strategy_actions}
        baseline_map = {item.candidate_name: item for item in baseline.strategies}
        adapted_map = {item.candidate_name: item for item in adapted.strategies}
        for candidate_name, baseline_strategy in baseline_map.items():
            adapted_strategy = adapted_map.get(candidate_name)
            if adapted_strategy is None:
                continue
            impact = impact_rows.get((baseline.symbol, candidate_name))
            edge_retention_pct = impact.edge_retention_pct if impact is not None else 0.0
            live_fill_count = impact.live_fill_count if impact is not None else 0
            baseline_result_index = (
                edge_retention_pct
                * max(baseline_strategy.base_allocation_weight, 0.0)
                * max(baseline_strategy.max_risk_multiplier, 0.0)
            )
            adapted_result_index = (
                edge_retention_pct
                * max(adapted_strategy.base_allocation_weight, 0.0)
                * max(adapted_strategy.max_risk_multiplier, 0.0)
            )
            change_pct = (
                ((adapted_result_index - baseline_result_index) / baseline_result_index) * 100.0
                if baseline_result_index > 0.0
                else 0.0
            )
            action = adapted_actions.get(candidate_name)
            rows.append(
                TCAAdaptationImpactRow(
                    symbol=baseline.symbol,
                    candidate_name=candidate_name,
                    live_fill_count=live_fill_count,
                    edge_retention_pct=edge_retention_pct,
                    baseline_base_weight=baseline_strategy.base_allocation_weight,
                    adapted_base_weight=adapted_strategy.base_allocation_weight,
                    baseline_max_risk=baseline_strategy.max_risk_multiplier,
                    adapted_max_risk=adapted_strategy.max_risk_multiplier,
                    baseline_result_index=baseline_result_index,
                    adapted_result_index=adapted_result_index,
                    result_index_change_pct=change_pct,
                    adaptation_action=action.action if action is not None else "unknown",
                    adaptation_reason=action.reason if action is not None else "",
                )
            )
    rows.sort(key=lambda row: (row.result_index_change_pct, row.symbol, row.candidate_name))
    return rows


def generate_tca_adaptation_impact_report(config: SystemConfig | None = None) -> Path:
    config = config or SystemConfig()
    rows = build_tca_adaptation_impact_rows(config)
    report_path = system_reports_dir() / "tca_adaptation_impact_report.txt"
    lines = [
        "TCA adaptation impact report",
        f"generated_at: {datetime.now(UTC).isoformat()}",
        "",
        "Metric: estimated result index = edge_retention_pct x base_allocation_weight x max_risk_multiplier.",
        "Interpretation: this is a before/after estimate of what the execution adaptation layer changes in exposure to retained edge.",
        "",
    ]
    if not rows:
        lines.append("No rows available.")
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        _write_tca_adaptation_impact_json(report_path, rows)
        return report_path
    header = (
        f"{'symbol':<8} {'strategy':<24} {'fills':>6} {'edge_ret%':>9} "
        f"{'base_idx':>10} {'adapt_idx':>10} {'chg%':>8} {'action':<18}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for row in rows:
        lines.append(
            f"{row.symbol[:8]:<8} {row.candidate_name[:24]:<24} {row.live_fill_count:>6} "
            f"{_fmt_num(row.edge_retention_pct, 1):>9} {_fmt_num(row.baseline_result_index, 2):>10} "
            f"{_fmt_num(row.adapted_result_index, 2):>10} {_fmt_num(row.result_index_change_pct, 1):>8} "
            f"{row.adaptation_action[:18]:<18}"
        )
    lines.extend(["", "Details"])
    for row in rows:
        lines.extend(
            [
                f"{row.symbol} | {row.candidate_name}",
                f"  live_fill_count: {row.live_fill_count}",
                f"  edge_retention_pct: {_fmt_num(row.edge_retention_pct, 2)}",
                f"  baseline_base_weight: {_fmt_num(row.baseline_base_weight, 3)}",
                f"  adapted_base_weight: {_fmt_num(row.adapted_base_weight, 3)}",
                f"  baseline_max_risk: {_fmt_num(row.baseline_max_risk, 3)}",
                f"  adapted_max_risk: {_fmt_num(row.adapted_max_risk, 3)}",
                f"  baseline_result_index: {_fmt_num(row.baseline_result_index, 4)}",
                f"  adapted_result_index: {_fmt_num(row.adapted_result_index, 4)}",
                f"  result_index_change_pct: {_fmt_num(row.result_index_change_pct, 2)}",
                f"  adaptation_action: {row.adaptation_action}",
                f"  adaptation_reason: {row.adaptation_reason}",
                "",
            ]
        )
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    _write_tca_adaptation_impact_json(report_path, rows)
    return report_path


def _write_tca_adaptation_impact_json(report_path: Path, rows: list[TCAAdaptationImpactRow]) -> None:
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "rows": [asdict(row) for row in rows],
        "report_path": str(report_path),
    }
    report_path.with_suffix(".json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
