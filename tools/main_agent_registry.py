from __future__ import annotations

import sys

import _bootstrap  # noqa: F401

from quant_system.artifacts import parse_symbol_profile_name, symbol_profile_name
from quant_system.ai.models import AgentRegistryRecord
from quant_system.ai.registry import render_agent_catalog, render_agent_registry
from quant_system.ai.storage import ExperimentStore
from quant_system.config import SystemConfig


def _resolve_requested_profiles(store: ExperimentStore, args: list[str], active_profiles: list[str]) -> list[str]:
    available = store.list_agent_catalog_profiles()
    config = SystemConfig()
    if not args:
        return available or active_profiles

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
        legacy_match = next(
            (
                profile_name
                for profile_name in available
                if (parsed := parse_symbol_profile_name(profile_name)) is not None and parsed[1] == candidate.lower()
            ),
            None,
        )
        if legacy_match is not None:
            resolved.append(legacy_match)
            continue
        resolved.append(candidate)
    return resolved


def main() -> int:
    config = SystemConfig()
    store = ExperimentStore(config.ai.experiment_database_path)
    requested_profiles = [part.strip() for part in sys.argv[1:] if part.strip()]
    profiles = _resolve_requested_profiles(store, requested_profiles, list(config.instrument.active_profiles))

    output_lines = ["Agent overview"]
    found_any = False
    for profile_name in profiles:
        catalog_rows = store.list_agent_catalog(profile_name)
        registry_rows = store.list_agent_registry(profile_name)
        output_lines.append("")
        output_lines.append(render_agent_catalog(profile_name, catalog_rows))
        output_lines.append("")
        if registry_rows:
            registry_text = render_agent_registry(
                [
                    AgentRegistryRecord(
                        profile_name=profile_name,
                        agent_name=str(row["agent_name"]),
                        source_type=str(row["source_type"]),
                        realized_pnl=float(row["best_realized_pnl"]),
                        closed_trades=int(row["best_closed_trades"]),
                        win_rate_pct=0.0,
                        profit_factor=float(row["best_profit_factor"]),
                        max_drawdown_pct=0.0,
                        data_source="historical",
                        verdict=str(row["last_verdict"]),
                        recommended_action=str(row["last_recommended_action"]),
                    )
                    for row in registry_rows
                ],
                profile_name,
            )
            output_lines.append(registry_text)
        else:
            output_lines.append(f"Profile: {profile_name}\nAgent registry\n\nNo registry entries available yet.")
        found_any = found_any or bool(catalog_rows or registry_rows)

    print("\n".join(output_lines))
    return 0 if found_any else 1


if __name__ == "__main__":
    raise SystemExit(main())
