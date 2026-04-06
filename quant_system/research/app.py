from __future__ import annotations

from quant_system.ai.storage import ExperimentStore
from quant_system.config import SystemConfig
from quant_system.symbol_research import (
    _configure_symbol_execution,
    _run_candidate_bundle,
    _symbol_slug,
    run_symbol_research,
    select_execution_candidates,
)
from quant_system.symbols import resolve_symbol_request


def run_symbol_research_app(data_symbol: str, broker_symbol: str | None = None) -> list[str]:
    return run_symbol_research(data_symbol, broker_symbol)


def run_symbol_execute_app(requested_symbol: str) -> list[str]:
    config = SystemConfig()
    resolved = resolve_symbol_request(requested_symbol)
    profile_name = f"symbol::{_symbol_slug(resolved.profile_symbol)}"
    store = ExperimentStore(config.ai.experiment_database_path)
    research_run = store.get_latest_symbol_research_run(profile_name)
    if research_run is None:
        return [f"No symbol research run found for {resolved.profile_symbol}. Run main_symbol_research.py first."]

    execution_set = store.get_latest_symbol_execution_set(profile_name)
    selected_candidates: list[dict[str, object]]
    execution_set_label: str
    if (
        execution_set is not None
        and execution_set["items"]
        and int(execution_set["symbol_research_run_id"]) == int(research_run["id"])
    ):
        selected_candidates = list(execution_set["items"])
        execution_set_label = f"saved::{execution_set['id']}"
    else:
        candidate_rows = store.list_latest_symbol_research_candidates(profile_name)
        if not candidate_rows:
            return [f"No symbol research candidates found for {profile_name}."]
        selected_candidates = select_execution_candidates(candidate_rows, max_candidates=1)
        if not selected_candidates:
            return [
                f"No executable candidates selected for {profile_name}. "
                "Run main_symbol_research.py again after the strategy improves."
            ]
        execution_set_label = "fallback_heuristic"

    candidate_rows = {str(row["candidate_name"]): row for row in store.list_latest_symbol_research_candidates(profile_name)}
    enriched_candidates: list[dict[str, object]] = []
    for row in selected_candidates:
        merged = dict(row)
        merged.update(candidate_rows.get(str(row["candidate_name"]), {}))
        enriched_candidates.append(merged)
    if not enriched_candidates:
        return [f"No executable candidates selected for {profile_name}."]

    _configure_symbol_execution(config, resolved.profile_symbol)
    config.polygon.symbol = str(research_run["data_symbol"])
    config.mt5.symbol = str(research_run["broker_symbol"])
    result, data_source, execution_variant_label = _run_candidate_bundle(
        config,
        resolved.profile_symbol,
        str(research_run["data_symbol"]),
        enriched_candidates,
    )

    return [
        f"Requested symbol: {resolved.requested_symbol}",
        f"Symbol: {resolved.profile_symbol}",
        f"Data symbol: {research_run['data_symbol']}",
        f"Catalog profile: {profile_name}",
        f"Broker symbol: {research_run['broker_symbol']}",
        f"Data source: {data_source}",
        f"Execution set source: {execution_set_label}",
        f"Execution variant: {execution_variant_label}",
        "Selected candidates: " + ", ".join(str(row["candidate_name"]) for row in enriched_candidates),
        f"Ending equity: {result.ending_equity:.2f}",
        f"Realized PnL: {result.realized_pnl:.2f}",
        f"Closed trades: {len(result.closed_trades)}",
        f"Win rate: {result.win_rate_pct:.2f}%",
        f"Profit factor: {result.profit_factor:.2f}",
    ]
