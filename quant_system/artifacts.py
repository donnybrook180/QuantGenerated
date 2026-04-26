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


def symbol_profile_name(symbol: str, venue_key: str = "generic") -> str:
    return f"symbol::{artifact_slug(venue_key)}::{artifact_slug(symbol)}"


def parse_symbol_profile_name(profile_name: str) -> tuple[str, str] | None:
    raw = profile_name.strip()
    if not raw.startswith("symbol::"):
        return None
    parts = [part.strip() for part in raw.split("::") if part.strip()]
    if len(parts) >= 3:
        return parts[1], parts[2]
    if len(parts) == 2:
        return "generic", parts[1]
    return None


def deploy_symbol_dir(symbol: str, venue_key: str = "generic") -> Path:
    return ensure_dir(DEPLOY_DIR / artifact_slug(venue_key) / artifact_slug(symbol))


def legacy_deploy_symbol_dir(symbol: str) -> Path:
    return ensure_dir(DEPLOY_DIR / artifact_slug(symbol))


def deployment_path(symbol: str, venue_key: str = "generic") -> Path:
    return deploy_symbol_dir(symbol, venue_key) / "live.json"


def legacy_deployment_path(symbol: str) -> Path:
    return legacy_deploy_symbol_dir(symbol) / "live.json"


def resolve_deployment_path(symbol: str, venue_key: str = "generic") -> Path:
    current = deployment_path(symbol, venue_key)
    if current.exists():
        return current
    legacy = legacy_deployment_path(symbol)
    if legacy.exists():
        return legacy
    return current


def list_deployment_paths() -> list[Path]:
    if not DEPLOY_DIR.exists():
        return []
    return sorted(DEPLOY_DIR.rglob("live.json"))


def system_reports_dir() -> Path:
    return ensure_dir(SYSTEM_DIR / "reports")


def live_venue_dir(venue_key: str = "generic") -> Path:
    return ensure_dir(LIVE_DIR / artifact_slug(venue_key))


def live_symbol_dir(symbol: str, venue_key: str = "generic") -> Path:
    return ensure_dir(live_venue_dir(venue_key) / artifact_slug(symbol))


def legacy_live_symbol_dir(symbol: str) -> Path:
    return ensure_dir(LIVE_DIR / artifact_slug(symbol))


def resolve_live_symbol_dir(symbol: str, venue_key: str = "generic") -> Path:
    current = LIVE_DIR / artifact_slug(venue_key) / artifact_slug(symbol)
    legacy = LIVE_DIR / artifact_slug(symbol)
    if current.exists():
        return current
    if legacy.exists():
        return legacy
    return ensure_dir(current)


def live_journals_dir(symbol: str, venue_key: str = "generic") -> Path:
    return ensure_dir(live_symbol_dir(symbol, venue_key) / "journals")


def live_incidents_dir(symbol: str, venue_key: str = "generic") -> Path:
    return ensure_dir(live_symbol_dir(symbol, venue_key) / "incidents")
