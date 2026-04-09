from __future__ import annotations

from pathlib import Path


ARTIFACTS_DIR = Path("artifacts")
RESEARCH_DIR = ARTIFACTS_DIR / "research"
PROFILES_DIR = ARTIFACTS_DIR / "profiles"
DEPLOY_DIR = ARTIFACTS_DIR / "deploy"
LIVE_DIR = ARTIFACTS_DIR / "live"
SYSTEM_DIR = ARTIFACTS_DIR / "system"


def artifact_slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def research_symbol_dir(symbol: str) -> Path:
    return ensure_dir(RESEARCH_DIR / artifact_slug(symbol))


def research_reports_dir(symbol: str) -> Path:
    return ensure_dir(research_symbol_dir(symbol) / "reports")


def research_plots_dir(symbol: str) -> Path:
    return ensure_dir(research_symbol_dir(symbol) / "plots")


def research_candidates_dir(symbol: str) -> Path:
    return ensure_dir(research_symbol_dir(symbol) / "candidates")


def profile_dir(profile_name: str) -> Path:
    return ensure_dir(PROFILES_DIR / artifact_slug(profile_name))


def profile_reports_dir(profile_name: str) -> Path:
    return ensure_dir(profile_dir(profile_name) / "reports")


def profile_logs_dir(profile_name: str) -> Path:
    return ensure_dir(profile_dir(profile_name) / "logs")


def deploy_symbol_dir(symbol: str) -> Path:
    return ensure_dir(DEPLOY_DIR / artifact_slug(symbol))


def system_reports_dir() -> Path:
    return ensure_dir(SYSTEM_DIR / "reports")


def live_symbol_dir(symbol: str) -> Path:
    return ensure_dir(LIVE_DIR / artifact_slug(symbol))


def live_journals_dir(symbol: str) -> Path:
    return ensure_dir(live_symbol_dir(symbol) / "journals")


def live_incidents_dir(symbol: str) -> Path:
    return ensure_dir(live_symbol_dir(symbol) / "incidents")
