from __future__ import annotations

import sys

from quant_system.config import SystemConfig
from quant_system.research.app import run_symbol_research_app


def main() -> int:
    config = SystemConfig()
    if len(sys.argv) >= 2:
        data_symbol = sys.argv[1].strip()
        broker_symbol = sys.argv[2].strip() if len(sys.argv) > 2 and sys.argv[2].strip() else None
    else:
        data_symbol = config.symbol_research.symbol.strip()
        broker_symbol = config.symbol_research.broker_symbol.strip() or None
        if not data_symbol:
            print(
                "Usage: .\\.venv\\Scripts\\python.exe main_symbol_research.py <data_symbol> [broker_symbol]\n"
                "Or set SYMBOL_RESEARCH_SYMBOL in .env.\n"
                "You can use aliases like US500, US100, GER40, or XAUUSD."
            )
            return 1
    print("\n".join(run_symbol_research_app(data_symbol, broker_symbol)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
