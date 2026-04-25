from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _run_step(command: list[str], repo_root: Path) -> int:
    print(f"\nRunning: {' '.join(command)}")
    result = subprocess.run(command, cwd=repo_root, check=False)
    return int(result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the standard refactor milestone validation workflow.")
    parser.add_argument(
        "--refresh-baseline",
        action="store_true",
        help="Capture a new baseline before running regressions.",
    )
    parser.add_argument(
        "--skip-functional-suite",
        action="store_true",
        help="Skip the full functional suite inside the regression runner.",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["EURUSD", "XAUUSD", "JP225"],
        help="Symbols to compare against the baseline snapshot set.",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    python_executable = sys.executable

    if args.refresh_baseline:
        baseline_exit_code = _run_step(
            [python_executable, "tools/main_capture_refactor_baseline.py"],
            repo_root,
        )
        if baseline_exit_code != 0:
            print("\nMilestone workflow stopped: baseline capture failed.")
            return baseline_exit_code

    regression_command = [python_executable, "tools/main_test_refactor_regressions.py", "--symbols", *args.symbols]
    if args.skip_functional_suite:
        regression_command.append("--skip-functional-suite")
    regression_exit_code = _run_step(regression_command, repo_root)
    if regression_exit_code != 0:
        print("\nMilestone workflow failed during regression validation.")
        return regression_exit_code

    print("\nMilestone workflow passed.")
    print("Artifacts:")
    print("- artifacts/system/reports/refactor_regression_report.json")
    if args.refresh_baseline:
        print("- artifacts/system/baselines/refactor_step1/manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
