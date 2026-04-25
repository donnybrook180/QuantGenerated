from __future__ import annotations

import json

from quant_system.config import SystemConfig
from quant_system.research.app import run_symbol_research_app


def symbol_research_usage() -> str:
    return (
        "Usage: .\\.venv\\Scripts\\python.exe main_symbol_research.py <data_symbol> [broker_symbol]\n"
        "Or set SYMBOL_RESEARCH_SYMBOL in .env.\n"
        "You can use aliases like US500, US100, GER40, or XAUUSD."
    )


def resolve_symbol_research_request(argv: list[str], config: SystemConfig | None = None) -> tuple[str | None, str | None]:
    config = config or SystemConfig()
    if len(argv) >= 1 and argv[0].strip():
        data_symbol = argv[0].strip()
        broker_symbol = argv[1].strip() if len(argv) >= 2 and argv[1].strip() else None
        return data_symbol, broker_symbol
    data_symbol = config.symbol_research.symbol.strip()
    broker_symbol = config.symbol_research.broker_symbol.strip() or None
    return (data_symbol or None), broker_symbol


def run_symbol_research_cli(argv: list[str], *, print_fn=print) -> int:
    data_symbol, broker_symbol = resolve_symbol_research_request(argv)
    if not data_symbol:
        print_fn(symbol_research_usage())
        return 1
    print_fn("\n".join(run_symbol_research_app(data_symbol, broker_symbol)))
    return 0


def run_live_research_cli(argv: list[str], *, print_fn=print) -> int:
    if len(argv) < 3:
        print_fn(
            "Usage: python tools/main_live_research_runner.py "
            "<data_symbol> <broker_symbol> <experiment_type> [candidate_prefixes_json] [execution_overrides_json]"
        )
        return 1
    data_symbol = argv[0].strip()
    broker_symbol = argv[1].strip()
    experiment_type = argv[2].strip()
    candidate_prefixes: tuple[str, ...] = ()
    if len(argv) >= 4 and argv[3].strip():
        candidate_prefixes = tuple(json.loads(argv[3]))
    execution_overrides = {}
    if len(argv) >= 5 and argv[4].strip():
        execution_overrides = dict(json.loads(argv[4]))

    print_fn(f"Live research runner experiment_type={experiment_type}")
    if candidate_prefixes:
        print_fn("Candidate prefixes: " + ", ".join(candidate_prefixes))
    if execution_overrides:
        print_fn("Requested execution_overrides: " + json.dumps(execution_overrides, sort_keys=True))
        print_fn(
            "Note: overrides are logged for research intent; current runner filters candidates but does not inject runtime override search automatically."
        )
    lines = run_symbol_research_app(data_symbol, broker_symbol, candidate_name_prefixes=candidate_prefixes or None)
    print_fn("\n".join(lines))
    return 0
