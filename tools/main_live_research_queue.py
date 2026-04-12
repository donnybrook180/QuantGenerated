from __future__ import annotations

import _bootstrap  # noqa: F401

from quant_system.config import SystemConfig
from quant_system.live.autopsy import generate_live_research_queue


def main() -> int:
    path = generate_live_research_queue(SystemConfig())
    print(f"Live research queue: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
