from __future__ import annotations

import _bootstrap  # noqa: F401

from quant_system.config import SystemConfig
from quant_system.interpreter.reporting import generate_market_interpreter_report


def main() -> int:
    path = generate_market_interpreter_report(SystemConfig())
    print(f"Market interpreter report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
