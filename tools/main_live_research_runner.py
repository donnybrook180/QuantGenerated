from __future__ import annotations

import json
import sys

import _bootstrap  # noqa: F401

from quant_system.research.app import run_symbol_research_app


def main() -> int:
    if len(sys.argv) < 4:
        print(
            "Usage: python tools/main_live_research_runner.py "
            "<data_symbol> <broker_symbol> <experiment_type> [candidate_prefixes_json] [execution_overrides_json]"
        )
        return 1
    data_symbol = sys.argv[1].strip()
    broker_symbol = sys.argv[2].strip()
    experiment_type = sys.argv[3].strip()
    candidate_prefixes = ()
    if len(sys.argv) >= 5 and sys.argv[4].strip():
        candidate_prefixes = tuple(json.loads(sys.argv[4]))
    execution_overrides = {}
    if len(sys.argv) >= 6 and sys.argv[5].strip():
        execution_overrides = dict(json.loads(sys.argv[5]))

    print(f"Live research runner experiment_type={experiment_type}")
    if candidate_prefixes:
        print("Candidate prefixes: " + ", ".join(candidate_prefixes))
    if execution_overrides:
        print("Requested execution_overrides: " + json.dumps(execution_overrides, sort_keys=True))
        print("Note: overrides are logged for research intent; current runner filters candidates but does not inject runtime override search automatically.")
    lines = run_symbol_research_app(data_symbol, broker_symbol, candidate_name_prefixes=candidate_prefixes or None)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
