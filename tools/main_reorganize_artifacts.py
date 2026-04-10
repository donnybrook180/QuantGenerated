from __future__ import annotations

import shutil
from pathlib import Path

import _bootstrap  # noqa: F401

from quant_system.artifacts import (
    ARTIFACTS_DIR,
    DEPLOY_DIR,
    LIVE_DIR,
    deploy_symbol_dir,
    ensure_dir,
    live_incidents_dir,
    live_journals_dir,
    profile_logs_dir,
    profile_reports_dir,
    research_candidates_dir,
    research_plots_dir,
    research_reports_dir,
    system_reports_dir,
)

def _safe_stem(value: str, max_length: int = 110) -> str:
    if len(value) <= max_length:
        return value
    import hashlib

    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    trimmed = value[: max_length - 13].rstrip("_")
    return f"{trimmed}_{digest}"


def _move(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    ensure_dir(dst.parent)
    if dst.exists():
        src.unlink()
        return
    shutil.move(str(src), str(dst))


def _candidate_destination(candidate_dir: Path, slug: str, path: Path) -> Path:
    name = path.name
    if name.startswith(f"{slug}_"):
        name = name[len(slug) + 1 :]
    stem = _safe_stem(Path(name).stem, max_length=110)
    return candidate_dir / f"{stem}{path.suffix}"


def reorganize_research_artifacts() -> None:
    plot_suffix_map = {
        "_best_candidate_equity.png": "best_candidate_equity.png",
        "_candidate_ranking.png": "candidate_ranking.png",
        "_validation_test_scatter.png": "validation_test_scatter.png",
        "_regimes.png": "regimes.png",
    }
    for path in list(ARTIFACTS_DIR.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        if name == "portfolio_allocator.txt":
            continue
        if any(name.endswith(suffix) for suffix in PROFILE_REPORT_SUFFIXES):
            continue
        if any(name.endswith(suffix) for suffix in PROFILE_LOG_SUFFIXES):
            continue
        if name.endswith("_symbol_research.csv"):
            slug = name[: -len("_symbol_research.csv")]
            _move(path, research_reports_dir(slug) / "symbol_research.csv")
            continue
        if name.endswith("_symbol_research.txt"):
            slug = name[: -len("_symbol_research.txt")]
            _move(path, research_reports_dir(slug) / "symbol_research.txt")
            continue
        if name.endswith("_viability_autopsy.txt"):
            slug = name[: -len("_viability_autopsy.txt")]
            _move(path, research_reports_dir(slug) / "viability_autopsy.txt")
            continue
        matched_plot = next((item for item in plot_suffix_map.items() if name.endswith(item[0])), None)
        if matched_plot is not None:
            suffix, target_name = matched_plot
            slug = name[: -len(suffix)]
            _move(path, research_plots_dir(slug) / target_name)
            continue
        if "_" not in name or path.suffix.lower() not in {".csv", ".txt"}:
            continue
        slug = name.split("_", 1)[0]
        _move(path, _candidate_destination(research_candidates_dir(slug), slug, path))


PROFILE_REPORT_SUFFIXES = {
    "_ai_summary.txt": "ai_summary.txt",
    "_next_experiment.txt": "next_experiment.txt",
    "_experiment_history.txt": "experiment_history.txt",
    "_run_comparison.txt": "run_comparison.txt",
    "_agent_registry.txt": "agent_registry.txt",
    "_agent_catalog.txt": "agent_catalog.txt",
    "_shadow_setups.txt": "shadow_setups.txt",
    "_signals_analysis.txt": "signals_analysis.txt",
}


PROFILE_LOG_SUFFIXES = {
    "_shadow_setups.csv": "shadow_setups.csv",
    "_signals.csv": "signals.csv",
}


def reorganize_profile_artifacts() -> None:
    for path in list(ARTIFACTS_DIR.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        matched_report = next((item for item in PROFILE_REPORT_SUFFIXES.items() if name.endswith(item[0])), None)
        if matched_report is not None:
            suffix, target_name = matched_report
            profile_name = name[: -len(suffix)]
            _move(path, profile_reports_dir(profile_name) / target_name)
            continue
        matched_log = next((item for item in PROFILE_LOG_SUFFIXES.items() if name.endswith(item[0])), None)
        if matched_log is not None:
            suffix, target_name = matched_log
            profile_name = name[: -len(suffix)]
            _move(path, profile_logs_dir(profile_name) / target_name)


def reorganize_deploy_artifacts() -> None:
    ensure_dir(DEPLOY_DIR)
    for path in list(DEPLOY_DIR.glob("*.live.json")):
        symbol_slug = path.stem.replace(".live", "")
        _move(path, deploy_symbol_dir(symbol_slug) / "live.json")


def reorganize_live_artifacts() -> None:
    ensure_dir(LIVE_DIR)
    old_state = LIVE_DIR / "loop_state.json"
    if old_state.exists():
        _move(old_state, LIVE_DIR / "state" / "loop_state.json")
    for path in list(LIVE_DIR.glob("*_journal.json")):
        slug, _, tail = path.name.partition("_")
        _move(path, live_journals_dir(slug) / tail)
    for path in list(LIVE_DIR.glob("*_incident.txt")):
        slug, _, tail = path.name.partition("_")
        _move(path, live_incidents_dir(slug) / tail)


def reorganize_system_artifacts() -> None:
    allocator_path = ARTIFACTS_DIR / "portfolio_allocator.txt"
    if allocator_path.exists():
        _move(allocator_path, system_reports_dir() / "portfolio_allocator.txt")


def main() -> int:
    ensure_dir(ARTIFACTS_DIR)
    reorganize_profile_artifacts()
    reorganize_research_artifacts()
    reorganize_deploy_artifacts()
    reorganize_live_artifacts()
    reorganize_system_artifacts()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
