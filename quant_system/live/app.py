from __future__ import annotations

from pathlib import Path

from quant_system.config import SystemConfig
from quant_system.integrations.mt5 import MT5Error
from quant_system.live.deploy import DEPLOY_DIR, deployment_path_for_symbol, load_symbol_deployment
from quant_system.live.journal import write_live_incident, write_live_run_journal
from quant_system.live.runtime import MT5LiveExecutor
from quant_system.symbols import resolve_symbol_request


def resolve_live_deployment_paths(args: list[str]) -> list[Path]:
    if args:
        paths: list[Path] = []
        for raw_symbol in args:
            resolved = resolve_symbol_request(raw_symbol)
            path = deployment_path_for_symbol(resolved.profile_symbol)
            if path.exists():
                paths.append(path)
        return paths
    if not DEPLOY_DIR.exists():
        return []
    return sorted(DEPLOY_DIR.glob("*.live.json"))


def run_live_once_app(paths: list[Path], config: SystemConfig | None = None) -> list[str]:
    config = config or SystemConfig()
    lines: list[str] = []
    for path in paths:
        deployment = load_symbol_deployment(path)
        if not deployment.strategies:
            lines.append(f"{deployment.symbol}: no active live strategies in {path}")
            continue
        executor = MT5LiveExecutor(deployment, config)
        try:
            result = executor.run_once()
        except MT5Error as exc:
            incident_path = write_live_incident(deployment.symbol, str(path), str(exc))
            lines.append(f"{deployment.symbol}: MT5 live run failed: {exc}")
            lines.append(f"Incident log: {incident_path}")
            continue
        journal_path = write_live_run_journal(result, str(path))
        lines.extend(
            [
                f"Symbol: {result.symbol}",
                f"Broker symbol: {result.broker_symbol}",
                f"Deployment: {path}",
                f"Account mode: {result.account_mode_label}",
                f"Strategy isolation supported: {'yes' if result.strategy_isolation_supported else 'no'}",
                f"Journal: {journal_path}",
            ]
        )
        for action in result.actions:
            lines.append(
                f"- {action.candidate_name}: signal={action.signal_side.value} "
                f"current_qty={action.current_quantity:.2f} action={action.intended_action} magic={action.magic_number}"
            )
        lines.append("")
    return lines
