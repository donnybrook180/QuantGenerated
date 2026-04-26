from __future__ import annotations

import signal
import subprocess
import sys
from pathlib import Path

from quant_system.config import SystemConfig
from quant_system.live.app import parse_live_cli_args


def _spawn_loop(broker: str, passthrough_args: list[str]) -> subprocess.Popen[str]:
    command = [sys.executable, "main_live_loop.py", "--broker", broker, *passthrough_args]
    print(f"Starting live loop for broker={broker}: {' '.join(command)}")
    return subprocess.Popen(command, cwd=str(Path.cwd()), text=True)


def main() -> int:
    config = SystemConfig()
    brokers = config.live.prop_brokers
    if not brokers:
        print("No live brokers configured. Set LIVE_PROP_BROKERS or run main_live_loop.py --broker <venue>.")
        return 1

    _broker_override, passthrough_args = parse_live_cli_args(sys.argv[1:])
    processes = [_spawn_loop(broker, passthrough_args) for broker in brokers]

    def _shutdown(*_args) -> None:
        for process in processes:
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    exit_code = 0
    try:
        for process in processes:
            code = process.wait()
            if code != 0 and exit_code == 0:
                exit_code = code
    finally:
        _shutdown()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
