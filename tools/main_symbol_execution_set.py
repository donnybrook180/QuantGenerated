from __future__ import annotations

import sys

import _bootstrap  # noqa: F401

from quant_system.artifacts import parse_symbol_profile_name, symbol_profile_name
from quant_system.ai.storage import ExperimentStore
from quant_system.config import SystemConfig


def _resolve_requested_profiles(store: ExperimentStore, args: list[str]) -> list[str]:
    available = store.list_symbol_execution_set_profiles()
    config = SystemConfig()
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
        venue_profile = symbol_profile_name(candidate, str(config.mt5.prop_broker))
        if venue_profile in available:
            resolved.append(venue_profile)
            continue
        matched_profile = next(
            (
                profile_name
                for profile_name in available
                if (parsed := parse_symbol_profile_name(profile_name)) is not None and parsed[1] == candidate.lower()
            ),
            None,
        )
        if matched_profile is not None:
            resolved.append(matched_profile)
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
