from __future__ import annotations

import sys

from quant_system.config import SystemConfig
from quant_system.live.app import resolve_live_deployment_paths, run_live_once_app


def main() -> int:
    config = SystemConfig()
    paths = resolve_live_deployment_paths(sys.argv[1:])
    if not paths:
        print(
            "No live deployment artifacts found. Run main_symbol_research.py first so it exports "
            "artifacts/deploy/<symbol>/live.json and stores research outputs under artifacts/research/<symbol>/."
        )
        return 1
    print("\n".join(run_live_once_app(paths, config)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
