from __future__ import annotations

import sys

from quant_system.research.cli import run_symbol_research_cli


def main() -> int:
    return run_symbol_research_cli(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
