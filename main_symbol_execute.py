from __future__ import annotations

import asyncio
import sys

from quant_system.ai.storage import ExperimentStore
from quant_system.catalog_runtime import build_agents_from_catalog_paths
from quant_system.config import SystemConfig
from quant_system.execution.engine import AgentCoordinator
from quant_system.symbol_research import (
    _configure_symbol_execution,
    _symbol_slug,
    _run_candidate_bundle,
    select_execution_candidates,
)
from quant_system.symbols import resolve_symbol_request


def main() -> int:
    config = SystemConfig()
    if len(sys.argv) >= 2:
        requested_symbol = sys.argv[1].strip()
    else:
        requested_symbol = config.symbol_research.symbol.strip()
        if not requested_symbol:
            print(
                "Usage: .\\.venv\\Scripts\\python.exe main_symbol_execute.py <data_symbol>\n"
                "Or set SYMBOL_RESEARCH_SYMBOL in .env."
            )
            return 1

    resolved = resolve_symbol_request(requested_symbol)
    profile_name = f"symbol::{_symbol_slug(resolved.profile_symbol)}"
    store = ExperimentStore(config.ai.experiment_database_path)
    research_run = store.get_latest_symbol_research_run(profile_name)
    if research_run is None:
        print(f"No symbol research run found for {resolved.profile_symbol}. Run main_symbol_research.py first.")
        return 1

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
            print(f"No symbol research candidates found for {profile_name}.")
            return 1
        selected_candidates = select_execution_candidates(candidate_rows, max_candidates=1)
        if not selected_candidates:
            print(
                f"No executable candidates selected for {profile_name}. "
                "Run main_symbol_research.py again after the strategy improves."
            )
            return 1
        execution_set_label = "fallback_heuristic"

    candidate_rows = {
        str(row["candidate_name"]): row
        for row in store.list_latest_symbol_research_candidates(profile_name)
    }
    enriched_candidates: list[dict[str, object]] = []
    for row in selected_candidates:
        merged = dict(row)
        merged.update(candidate_rows.get(str(row["candidate_name"]), {}))
        enriched_candidates.append(merged)
    if not enriched_candidates:
        print(f"No executable candidates selected for {profile_name}.")
        return 1

    _configure_symbol_execution(config, resolved.profile_symbol)
    config.polygon.symbol = str(research_run["data_symbol"])
    config.mt5.symbol = str(research_run["broker_symbol"])
    result, data_source, execution_variant_label = _run_candidate_bundle(
        config,
        resolved.profile_symbol,
        str(research_run["data_symbol"]),
        enriched_candidates,
    )

    print(f"Requested symbol: {resolved.requested_symbol}")
    print(f"Symbol: {resolved.profile_symbol}")
    print(f"Data symbol: {research_run['data_symbol']}")
    print(f"Catalog profile: {profile_name}")
    print(f"Broker symbol: {research_run['broker_symbol']}")
    print(f"Data source: {data_source}")
    print(f"Execution set source: {execution_set_label}")
    print(f"Execution variant: {execution_variant_label}")
    print("Selected candidates: " + ", ".join(str(row["candidate_name"]) for row in enriched_candidates))
    print(f"Ending equity: {result.ending_equity:.2f}")
    print(f"Realized PnL: {result.realized_pnl:.2f}")
    print(f"Closed trades: {len(result.closed_trades)}")
    print(f"Win rate: {result.win_rate_pct:.2f}%")
    print(f"Profit factor: {result.profit_factor:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
