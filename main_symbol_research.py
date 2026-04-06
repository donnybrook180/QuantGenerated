from __future__ import annotations

import sys

from quant_system.symbol_research import run_symbol_research


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: .\\.venv\\Scripts\\python.exe main_symbol_research.py <data_symbol> [broker_symbol]")
        return 1
    data_symbol = sys.argv[1].strip()
    broker_symbol = sys.argv[2].strip() if len(sys.argv) > 2 and sys.argv[2].strip() else None
    print("\n".join(run_symbol_research(data_symbol, broker_symbol)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
