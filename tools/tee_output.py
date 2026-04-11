from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: tee_output.py <log_path> <command> [args...]", file=sys.stderr)
        return 2

    log_path = Path(sys.argv[1])
    command = sys.argv[2:]
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with log_path.open("a", encoding="utf-8", buffering=1) as log_file:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.write(line)
            log_file.write(line)
        return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
