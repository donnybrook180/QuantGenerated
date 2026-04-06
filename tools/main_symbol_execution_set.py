from __future__ import annotations

import sys

import _bootstrap  # noqa: F401

from quant_system.ai.storage import ExperimentStore
from quant_system.config import SystemConfig
from quant_system.symbol_research import _symbol_slug


def _resolve_requested_profiles(store: ExperimentStore, args: list[str]) -> list[str]:
    available = store.list_symbol_execution_set_profiles()
    if not args:
        return available

    resolved: list[str] = []
    for item in args:
        candidate = item.strip()
        if not candidate:
            continue
        if candidate in available:
            resolved.append(candidate)
            continue
        slug_profile = f"symbol::{_symbol_slug(candidate)}"
        if slug_profile in available:
            resolved.append(slug_profile)
            continue
        compact_symbol_profile = f"symbol::{candidate}"
        if compact_symbol_profile in available:
            resolved.append(compact_symbol_profile)
            continue
        resolved.append(candidate)
    return resolved


def main() -> int:
    config = SystemConfig()
    store = ExperimentStore(config.ai.experiment_database_path)
    requested_profiles = [part.strip() for part in sys.argv[1:] if part.strip()]
    profiles = _resolve_requested_profiles(store, requested_profiles)

    if not profiles:
        print("No symbol execution sets available yet. Run main_symbol_research.py first.")
        return 1

    lines = ["Symbol execution sets"]
    found_any = False
    for profile_name in profiles:
        execution_set = store.get_latest_symbol_execution_set(profile_name)
        if execution_set is None:
            lines.extend(
                [
                    "",
                    f"Profile: {profile_name}",
                    "No saved execution set available.",
                ]
            )
            continue

        found_any = True
        lines.extend(
            [
                "",
                f"Profile: {profile_name}",
                f"Execution set id: {execution_set['id']}",
                f"Research run id: {execution_set['symbol_research_run_id']}",
                f"Selection method: {execution_set['selection_method']}",
                f"Created at: {execution_set['created_at']}",
                "Candidates:",
            ]
        )
        for item in execution_set["items"]:
            lines.append(
                f"- #{item['selection_rank']} {item['candidate_name']} [{item['code_path']}]"
            )

    print("\n".join(lines))
    return 0 if found_any else 1


if __name__ == "__main__":
    raise SystemExit(main())
