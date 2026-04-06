from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quant_system.ai.storage import ExperimentStore
from quant_system.config import SystemConfig
from quant_system.symbol_research import _symbol_slug
from quant_system.symbols import resolve_symbol_request


ARTIFACTS_DIR = Path("artifacts")


@dataclass(slots=True)
class AllocationRow:
    profile_name: str
    symbol: str
    candidate_name: str
    variant_label: str
    regime_filter_label: str
    score: float
    weight_pct: float
    realized_pnl: float
    profit_factor: float
    max_drawdown_pct: float
    closed_trades: int
    validation_pnl: float
    validation_profit_factor: float
    validation_closed_trades: int
    test_pnl: float
    test_profit_factor: float
    test_closed_trades: int
    walk_forward_pass_rate_pct: float
    walk_forward_windows: int
    combo_outperformance_score: float
    dominant_regime_share_pct: float


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0.0:
        return 0.0
    return numerator / denominator


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _candidate_score(row: dict[str, object]) -> float:
    validation_pf_score = _clamp(_safe_div(float(row.get("validation_profit_factor", 0.0)), 2.5))
    test_pf_score = _clamp(_safe_div(float(row.get("test_profit_factor", 0.0)), 2.5))
    validation_pnl_score = _clamp(_safe_div(float(row.get("validation_pnl", 0.0)), 100.0))
    test_pnl_score = _clamp(_safe_div(float(row.get("test_pnl", 0.0)), 100.0))
    walk_forward_score = _clamp(_safe_div(float(row.get("walk_forward_pass_rate_pct", 0.0)), 100.0))
    walk_forward_pnl_score = _clamp(_safe_div(float(row.get("walk_forward_avg_test_pnl", 0.0)), 100.0))
    trade_depth_score = _clamp(_safe_div(float(row.get("closed_trades", 0)), 20.0))
    drawdown_score = 1.0 - _clamp(_safe_div(float(row.get("max_drawdown_pct", 0.0)), 5.0))
    combo_score = _clamp(0.5 + _safe_div(float(row.get("combo_outperformance_score", 0.0)), 2.0))
    regime_stability_score = 1.0 - _clamp(_safe_div(max(float(row.get("dominant_regime_share_pct", 0.0)) - 70.0, 0.0), 30.0))

    score = (
        validation_pf_score * 0.16
        + test_pf_score * 0.18
        + validation_pnl_score * 0.12
        + test_pnl_score * 0.14
        + walk_forward_score * 0.16
        + walk_forward_pnl_score * 0.08
        + trade_depth_score * 0.06
        + drawdown_score * 0.06
        + combo_score * 0.02
        + regime_stability_score * 0.02
    )
    return max(score, 0.0)


def _row_to_allocation(profile_name: str, symbol: str, row: dict[str, object], score: float, weight_pct: float) -> AllocationRow:
    return AllocationRow(
        profile_name=profile_name,
        symbol=symbol,
        candidate_name=str(row.get("candidate_name", "")),
        variant_label=str(row.get("variant_label", "") or ""),
        regime_filter_label=str(row.get("regime_filter_label", "") or ""),
        score=score,
        weight_pct=weight_pct,
        realized_pnl=float(row.get("realized_pnl", 0.0)),
        profit_factor=float(row.get("profit_factor", 0.0)),
        max_drawdown_pct=float(row.get("max_drawdown_pct", 0.0)),
        closed_trades=int(row.get("closed_trades", 0)),
        validation_pnl=float(row.get("validation_pnl", 0.0)),
        validation_profit_factor=float(row.get("validation_profit_factor", 0.0)),
        validation_closed_trades=int(row.get("validation_closed_trades", 0)),
        test_pnl=float(row.get("test_pnl", 0.0)),
        test_profit_factor=float(row.get("test_profit_factor", 0.0)),
        test_closed_trades=int(row.get("test_closed_trades", 0)),
        walk_forward_pass_rate_pct=float(row.get("walk_forward_pass_rate_pct", 0.0)),
        walk_forward_windows=int(row.get("walk_forward_windows", 0)),
        combo_outperformance_score=float(row.get("combo_outperformance_score", 0.0)),
        dominant_regime_share_pct=float(row.get("dominant_regime_share_pct", 0.0)),
    )


def _resolve_profile_symbol(symbol_or_profile: str) -> tuple[str, str]:
    raw = symbol_or_profile.strip()
    if raw.startswith("symbol::"):
        profile_name = raw
        symbol = raw.split("::", 1)[1].upper()
        return profile_name, symbol
    resolved = resolve_symbol_request(raw)
    return f"symbol::{_symbol_slug(resolved.profile_symbol)}", resolved.profile_symbol


def build_portfolio_allocation(symbols_or_profiles: list[str] | None = None) -> tuple[list[AllocationRow], Path]:
    config = SystemConfig()
    store = ExperimentStore(config.ai.experiment_database_path)
    requested_profiles: list[tuple[str, str]]
    if symbols_or_profiles:
        requested_profiles = [_resolve_profile_symbol(item) for item in symbols_or_profiles]
    else:
        requested_profiles = []
        for profile_name in store.list_symbol_research_profiles():
            if profile_name.startswith("symbol::"):
                requested_profiles.append((profile_name, profile_name.split("::", 1)[1].upper()))

    scored_rows: list[tuple[str, str, dict[str, object], float]] = []
    for profile_name, symbol in requested_profiles:
        latest_run = store.get_latest_symbol_research_run(profile_name)
        if latest_run is None:
            continue
        execution_set = store.get_latest_symbol_execution_set(profile_name)
        if execution_set is None or int(execution_set["symbol_research_run_id"]) != int(latest_run["id"]):
            continue
        candidate_rows = {str(row["candidate_name"]): row for row in store.list_latest_symbol_research_candidates(profile_name)}
        if not execution_set["items"]:
            continue
        lead_item = execution_set["items"][0]
        candidate_row = candidate_rows.get(str(lead_item["candidate_name"]))
        if candidate_row is None:
            continue
        score = _candidate_score(candidate_row)
        if score <= 0.0:
            continue
        scored_rows.append((profile_name, symbol, candidate_row, score))

    total_score = sum(score for _, _, _, score in scored_rows)
    allocations: list[AllocationRow] = []
    for profile_name, symbol, row, score in sorted(scored_rows, key=lambda item: item[3], reverse=True):
        weight_pct = 0.0 if total_score <= 0.0 else (score / total_score) * 100.0
        allocations.append(_row_to_allocation(profile_name, symbol, row, score, weight_pct))

    ARTIFACTS_DIR.mkdir(exist_ok=True)
    report_path = ARTIFACTS_DIR / "portfolio_allocator.txt"
    if not allocations:
        report_path.write_text(
            "Portfolio allocator\n\nNo eligible symbol execution sets were found from the latest symbol research runs.\n",
            encoding="utf-8",
        )
        return allocations, report_path

    lines = ["Portfolio allocator", ""]
    for row in allocations:
        variant = row.variant_label or "default"
        if row.regime_filter_label:
            variant = f"{variant}|{row.regime_filter_label}"
        lines.extend(
            [
                f"{row.symbol} ({row.profile_name})",
                f"  weight_pct: {row.weight_pct:.2f}",
                f"  score: {row.score:.4f}",
                f"  candidate: {row.candidate_name}",
                f"  variant: {variant}",
                f"  realized: pnl={row.realized_pnl:.2f} pf={row.profit_factor:.2f} closed={row.closed_trades} dd={row.max_drawdown_pct:.2f}%",
                f"  validation: pnl={row.validation_pnl:.2f} pf={row.validation_profit_factor:.2f} closed={row.validation_closed_trades}",
                f"  test: pnl={row.test_pnl:.2f} pf={row.test_profit_factor:.2f} closed={row.test_closed_trades}",
                f"  walk_forward: pass_rate={row.walk_forward_pass_rate_pct:.2f}% windows={row.walk_forward_windows}",
                f"  regime_stability: dominant_share={row.dominant_regime_share_pct:.2f}% combo_score={row.combo_outperformance_score:.2f}",
                "",
            ]
        )
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return allocations, report_path
