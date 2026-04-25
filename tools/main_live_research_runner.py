from __future__ import annotations

import sys

import _bootstrap  # noqa: F401

from quant_system.research.cli import run_live_research_cli


def main() -> int:
    return run_live_research_cli(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
