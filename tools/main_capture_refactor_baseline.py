from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from quant_system.artifacts import RESEARCH_DIR, SYSTEM_DIR, artifact_slug, ensure_dir, resolve_deployment_path


DEFAULT_SYMBOLS = ("EURUSD", "XAUUSD", "JP225")
RESEARCH_REPORT_FILENAMES = ("symbol_research.txt", "symbol_research.csv", "viability_autopsy.txt")
SYSTEM_REPORT_FILENAMES = ("live_health_report.txt", "live_health_report.json")


@dataclass
class BaselineManifest:
    created_at: str
    python_executable: str
    symbols: list[str]
    copied_files: list[str]
    functional_suite_exit_code: int | None


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _baseline_dir() -> Path:
    return ensure_dir(SYSTEM_DIR / "baselines" / "refactor_step1")


def _copy_file_if_present(source: Path, target: Path, copied_files: list[str]) -> None:
    if not source.exists():
        return
    ensure_dir(target.parent)
    shutil.copy2(source, target)
    copied_files.append(str(target.resolve().relative_to(_repo_root().resolve())))


def _capture_symbol_artifacts(symbol: str, baseline_dir: Path, copied_files: list[str]) -> None:
    slug = artifact_slug(symbol)
    baseline_symbol_dir = baseline_dir / "symbols" / slug
    reports_dir = RESEARCH_DIR / slug / "reports"
    deploy_path = resolve_deployment_path(symbol)

    for filename in RESEARCH_REPORT_FILENAMES:
        _copy_file_if_present(reports_dir / filename, baseline_symbol_dir / "reports" / filename, copied_files)

    _copy_file_if_present(deploy_path, baseline_symbol_dir / "deploy" / "live.json", copied_files)


def _capture_system_reports(baseline_dir: Path, copied_files: list[str]) -> None:
    system_reports_dir = SYSTEM_DIR / "reports"
    for filename in SYSTEM_REPORT_FILENAMES:
        _copy_file_if_present(system_reports_dir / filename, baseline_dir / "system_reports" / filename, copied_files)


def _run_functional_suite(repo_root: Path, baseline_dir: Path) -> int:
    command = [sys.executable, "tools/main_test_functional_suite.py"]
    result = subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output_path = baseline_dir / "functional_suite_baseline.txt"
    output_path.write_text(result.stdout + ("\n" if result.stdout else "") + result.stderr, encoding="utf-8")
    return int(result.returncode)


def main() -> int:
    repo_root = _repo_root()
    baseline_dir = _baseline_dir()
    copied_files: list[str] = []

    for symbol in DEFAULT_SYMBOLS:
        _capture_symbol_artifacts(symbol, baseline_dir, copied_files)
    _capture_system_reports(baseline_dir, copied_files)

    functional_suite_exit_code = _run_functional_suite(repo_root, baseline_dir)
    manifest = BaselineManifest(
        created_at=datetime.now(UTC).isoformat(),
        python_executable=sys.executable,
        symbols=list(DEFAULT_SYMBOLS),
        copied_files=sorted(copied_files),
        functional_suite_exit_code=functional_suite_exit_code,
    )
    manifest_path = baseline_dir / "manifest.json"
    manifest_path.write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")

    print(f"Baseline captured in {baseline_dir}")
    print(f"Copied files: {len(copied_files)}")
    print(f"Functional suite exit code: {functional_suite_exit_code}")
    print(f"Manifest: {manifest_path}")
    return 0 if functional_suite_exit_code == 0 else functional_suite_exit_code


if __name__ == "__main__":
    raise SystemExit(main())
