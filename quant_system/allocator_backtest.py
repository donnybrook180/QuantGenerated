from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from quant_system.ai.storage import ExperimentStore
from quant_system.allocator import AllocationInput, allocate_portfolio_candidates, load_symbol_returns_before
from quant_system.artifacts import system_reports_dir
from quant_system.config import SystemConfig
from quant_system.data.market_data import DuckDBMarketDataStore
from quant_system.symbols import resolve_symbol_request


@dataclass(slots=True)
class AllocatorSnapshotResult:
    as_of: datetime
    symbol_count: int
    snapshot_pnl_by_method: dict[str, float]


@dataclass(slots=True)
class AllocatorBacktestSummary:
    method: str
    snapshots: int
    avg_snapshot_pnl: float
    total_snapshot_pnl: float
    positive_snapshot_rate_pct: float
    cumulative_weighted_pnl: float


def _as_utc(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _select_candidate_row(store: ExperimentStore, run: dict[str, object]) -> tuple[str, dict[str, object]] | None:
    candidates = store.list_symbol_research_candidates_for_run(int(run["id"]))
    if not candidates:
        return None
    candidate_map = {str(row["candidate_name"]): row for row in candidates}
    execution_set = store.get_symbol_execution_set_for_run(str(run["profile_name"]), int(run["id"]))
    if execution_set and execution_set["items"]:
        lead_name = str(execution_set["items"][0]["candidate_name"])
        lead_row = candidate_map.get(lead_name)
        if lead_row is not None:
            resolved = resolve_symbol_request(str(run["data_symbol"]), broker_symbol=str(run.get("broker_symbol") or ""))
            return resolved.profile_symbol.upper(), lead_row
    recommended_names = [str(name) for name in run.get("recommended_names", [])]
    for name in recommended_names:
        recommended = candidate_map.get(name)
        if recommended is not None:
            resolved = resolve_symbol_request(str(run["data_symbol"]), broker_symbol=str(run.get("broker_symbol") or ""))
            return resolved.profile_symbol.upper(), recommended
    recommended_rows = [row for row in candidates if bool(row.get("recommended"))]
    if recommended_rows:
        resolved = resolve_symbol_request(str(run["data_symbol"]), broker_symbol=str(run.get("broker_symbol") or ""))
        return resolved.profile_symbol.upper(), recommended_rows[0]
    resolved = resolve_symbol_request(str(run["data_symbol"]), broker_symbol=str(run.get("broker_symbol") or ""))
    return resolved.profile_symbol.upper(), candidates[0]


def _build_snapshot_inputs(
    selected_by_profile: dict[str, list[tuple[datetime, AllocationInput]]], as_of: datetime
) -> list[AllocationInput]:
    inputs: list[AllocationInput] = []
    for items in selected_by_profile.values():
        latest_input: AllocationInput | None = None
        for created_at, selected_input in items:
            if created_at <= as_of:
                latest_input = selected_input
            else:
                break
        if latest_input is None:
            continue
        inputs.append(latest_input)
    return inputs


def _snapshot_returns(
    market_store: DuckDBMarketDataStore, inputs: list[AllocationInput], as_of: datetime, history_limit: int
) -> dict[str, list[float]]:
    return {
        item.symbol: load_symbol_returns_before(market_store, item.symbol, as_of, history_limit=history_limit) for item in inputs
    }


def backtest_portfolio_allocator(
    *,
    symbols_or_profiles: list[str] | None = None,
    min_symbols: int = 2,
    correlation_history_limit: int = 96,
) -> tuple[list[AllocatorBacktestSummary], list[AllocatorSnapshotResult], Path]:
    config = SystemConfig()
    store = ExperimentStore(config.ai.experiment_database_path)
    market_store = DuckDBMarketDataStore(config.mt5.database_path, read_only=True)

    profile_filter = set(symbols_or_profiles or [])
    runs_by_profile: dict[str, list[dict[str, object]]] = {}
    for profile_name in store.list_symbol_research_profiles():
        if not profile_name.startswith("symbol::"):
            continue
        if profile_filter and profile_name not in profile_filter and profile_name.split("::", 1)[1].upper() not in profile_filter:
            continue
        runs = store.list_symbol_research_runs(profile_name)
        if runs:
            runs_by_profile[profile_name] = runs

    selected_by_profile: dict[str, list[tuple[datetime, AllocationInput]]] = {}
    for profile_name, runs in runs_by_profile.items():
        selected_items: list[tuple[datetime, AllocationInput]] = []
        for run in runs:
            selected = _select_candidate_row(store, run)
            if selected is None:
                continue
            symbol, candidate_row = selected
            selected_items.append(
                (
                    _as_utc(run["created_at"]),
                    AllocationInput(profile_name=profile_name, symbol=symbol, candidate_row=candidate_row),
                )
            )
        if selected_items:
            selected_by_profile[profile_name] = selected_items

    snapshot_times = sorted({_as_utc(run["created_at"]) for runs in runs_by_profile.values() for run in runs})
    methods = ("naive", "bucket", "correlation_aware")
    snapshot_results: list[AllocatorSnapshotResult] = []
    method_pnls: dict[str, list[float]] = {method: [] for method in methods}

    for as_of in snapshot_times:
        inputs = _build_snapshot_inputs(selected_by_profile, as_of)
        if len(inputs) < min_symbols:
            continue
        snapshot_pnl_by_method: dict[str, float] = {}
        for method in methods:
            returns_by_symbol = (
                _snapshot_returns(market_store, inputs, as_of, correlation_history_limit)
                if method == "correlation_aware"
                else None
            )
            allocations = allocate_portfolio_candidates(inputs, method=method, returns_by_symbol=returns_by_symbol)
            if not allocations:
                continue
            weighted_pnl = sum((row.weight_pct / 100.0) * row.test_pnl for row in allocations)
            snapshot_pnl_by_method[method] = weighted_pnl
            method_pnls[method].append(weighted_pnl)
        if snapshot_pnl_by_method:
            snapshot_results.append(
                AllocatorSnapshotResult(
                    as_of=as_of,
                    symbol_count=len(inputs),
                    snapshot_pnl_by_method=snapshot_pnl_by_method,
                )
            )

    summaries: list[AllocatorBacktestSummary] = []
    for method in methods:
        pnls = method_pnls[method]
        snapshots = len(pnls)
        total = sum(pnls)
        avg = total / float(snapshots) if snapshots else 0.0
        positive_rate = (sum(1 for value in pnls if value > 0.0) / float(snapshots) * 100.0) if snapshots else 0.0
        summaries.append(
            AllocatorBacktestSummary(
                method=method,
                snapshots=snapshots,
                avg_snapshot_pnl=avg,
                total_snapshot_pnl=total,
                positive_snapshot_rate_pct=positive_rate,
                cumulative_weighted_pnl=total,
            )
        )

    report_path = system_reports_dir() / "portfolio_allocator_backtest.txt"
    lines = [
        "Portfolio allocator backtest",
        "Proxy metric: weighted candidate test_pnl per historical symbol-research snapshot.",
        "",
        "Summary",
    ]
    for summary in summaries:
        lines.extend(
            [
                f"{summary.method}",
                f"  snapshots: {summary.snapshots}",
                f"  avg_snapshot_pnl: {summary.avg_snapshot_pnl:.2f}",
                f"  total_snapshot_pnl: {summary.total_snapshot_pnl:.2f}",
                f"  positive_snapshot_rate_pct: {summary.positive_snapshot_rate_pct:.2f}",
                "",
            ]
        )
    lines.append("Snapshots")
    for snapshot in snapshot_results:
        naive = snapshot.snapshot_pnl_by_method.get("naive", 0.0)
        bucket = snapshot.snapshot_pnl_by_method.get("bucket", 0.0)
        corr = snapshot.snapshot_pnl_by_method.get("correlation_aware", 0.0)
        lines.extend(
            [
                snapshot.as_of.isoformat(),
                f"  symbols: {snapshot.symbol_count}",
                f"  naive: {naive:.2f}",
                f"  bucket: {bucket:.2f}",
                f"  correlation_aware: {corr:.2f}",
                "",
            ]
        )
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return summaries, snapshot_results, report_path
