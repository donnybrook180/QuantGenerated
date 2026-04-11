from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import _bootstrap  # noqa: F401


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    app_path = repo_root / "dashboard" / "app.py"
    command = [sys.executable, "-m", "streamlit", "run", str(app_path)]
    if len(sys.argv) > 1:
        command.extend(sys.argv[1:])
    completed = subprocess.run(command, cwd=str(repo_root), check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
