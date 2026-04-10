from __future__ import annotations

import _bootstrap  # noqa: F401

from quant_system.config import SystemConfig
from quant_system.live.health import generate_live_health_report


def main() -> int:
    config = SystemConfig()
    path = generate_live_health_report(config)
    print(f"Live health report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
