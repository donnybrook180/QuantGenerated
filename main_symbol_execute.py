from __future__ import annotations

import asyncio
import sys

from quant_system.ai.storage import ExperimentStore
from quant_system.catalog_runtime import build_agents_from_catalog_paths
from quant_system.config import SystemConfig
from quant_system.execution.engine import AgentCoordinator
from quant_system.symbol_research import _build_engine, _configure_symbol_execution, _load_symbol_features, _symbol_slug, select_execution_candidates


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: .\\.venv\\Scripts\\python.exe main_symbol_execute.py <data_symbol>")
        return 1

    data_symbol = sys.argv[1].strip()
    profile_name = f"symbol::{_symbol_slug(data_symbol)}"
    config = SystemConfig()
    store = ExperimentStore(config.ai.experiment_database_path)
    research_run = store.get_latest_symbol_research_run(profile_name)
    if research_run is None:
        print(f"No symbol research run found for {data_symbol}. Run main_symbol_research.py first.")
        return 1

    execution_set = store.get_latest_symbol_execution_set(profile_name)
    selected_candidates: list[dict[str, object]]
    execution_set_label: str
    if execution_set is not None and execution_set["items"]:
        selected_candidates = list(execution_set["items"])
        execution_set_label = f"saved::{execution_set['id']}"
    else:
        candidate_rows = store.list_latest_symbol_research_candidates(profile_name)
        if not candidate_rows:
            print(f"No symbol research candidates found for {profile_name}.")
            return 1
        selected_candidates = select_execution_candidates(candidate_rows, max_candidates=2)
        if not selected_candidates:
            print(f"No executable candidates selected for {profile_name}.")
            return 1
        execution_set_label = "fallback_heuristic"

    _configure_symbol_execution(config, data_symbol)
    config.polygon.symbol = data_symbol
    config.mt5.symbol = str(research_run["broker_symbol"])
    features, data_source = _load_symbol_features(config, data_symbol)
    agents = build_agents_from_catalog_paths([str(row["code_path"]) for row in selected_candidates], config)
    engine = _build_engine(config, agents)
    result = asyncio.run(engine.run(features, sleep_seconds=0.0))
    coordinator = AgentCoordinator(agents, consensus_min_confidence=config.agents.consensus_min_confidence)

    print(f"Symbol: {data_symbol}")
    print(f"Catalog profile: {profile_name}")
    print(f"Broker symbol: {research_run['broker_symbol']}")
    print(f"Data source: {data_source}")
    print(f"Execution set source: {execution_set_label}")
    print("Selected candidates: " + ", ".join(str(row["candidate_name"]) for row in selected_candidates))
    print(f"Ending equity: {result.ending_equity:.2f}")
    print(f"Realized PnL: {result.realized_pnl:.2f}")
    print(f"Closed trades: {len(result.closed_trades)}")
    print(f"Win rate: {result.win_rate_pct:.2f}%")
    print(f"Profit factor: {result.profit_factor:.2f}")
    latest_side = coordinator.decide(features[-1])
    print(f"Latest consensus signal: {latest_side.value if latest_side is not None else 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
