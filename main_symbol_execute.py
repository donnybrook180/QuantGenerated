from __future__ import annotations

import sys

from quant_system.config import SystemConfig
from quant_system.research.app import run_symbol_execute_app


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
    print("\n".join(run_symbol_execute_app(requested_symbol)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
