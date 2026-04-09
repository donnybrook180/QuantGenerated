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
    return sorted(DEPLOY_DIR.glob("*/live.json"))


def resolve_live_portfolio_weights(paths: list[Path]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for path in paths:
        deployment = load_symbol_deployment(path)
        weights[deployment.symbol.upper()] = 1.0
    return weights


def resolve_live_strategy_weights(paths: list[Path]) -> dict[str, dict[str, float]]:
    weights: dict[str, dict[str, float]] = {}
    for path in paths:
        deployment = load_symbol_deployment(path)
        weights[deployment.symbol.upper()] = {
            strategy.candidate_name: 1.0
            for strategy in deployment.strategies
        }
    return weights


def run_live_once_app(paths: list[Path], config: SystemConfig | None = None) -> list[str]:
    config = config or SystemConfig()
    lines: list[str] = []
    portfolio_weights = resolve_live_portfolio_weights(paths)
    strategy_weights = resolve_live_strategy_weights(paths)
    for path in paths:
        deployment = load_symbol_deployment(path)
        if not deployment.strategies:
            lines.append(f"{deployment.symbol}: no active live strategies in {path}")
            continue
        portfolio_weight = portfolio_weights.get(deployment.symbol.upper(), 0.0)
        executor = MT5LiveExecutor(
            deployment,
            config,
            portfolio_weight=portfolio_weight,
            strategy_portfolio_weights=strategy_weights.get(deployment.symbol.upper(), {}),
        )
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
                f"Portfolio weight: {result.portfolio_weight:.2f}",
                (
                    f"Regime: {result.regime_snapshot.regime_label} "
                    f"(vol_pct={result.regime_snapshot.vol_percentile:.2f}, "
                    f"risk={result.regime_snapshot.risk_multiplier:.2f})"
                )
                if result.regime_snapshot is not None
                else "Regime: unknown",
                f"Journal: {journal_path}",
            ]
        )
        for action in result.actions:
            strategy = next((item for item in deployment.strategies if item.candidate_name == action.candidate_name), None)
            lines.append(
                f"- {action.candidate_name}: signal={action.signal_side.value} "
                f"current_qty={action.current_quantity:.2f} action={action.intended_action} "
                f"regime={action.regime_label or 'n/a'} vol_pct={action.vol_percentile:.2f} "
                f"risk={action.risk_multiplier:.2f} alloc={action.allocation_fraction:.2f} "
                f"portfolio={action.portfolio_weight:.2f} "
                f"base_alloc={action.base_allocation_weight:.2f} "
                f"size_factor={action.effective_size_factor:.3f} "
                f"tier={action.promotion_tier} "
                f"score={action.allocator_score:.2f} magic={action.magic_number}"
            )
            if action.veto_reason:
                lines.append(f"  veto: {action.veto_reason}")
            if strategy is not None and strategy.policy_summary:
                lines.append(f"  policy: {strategy.policy_summary}")
        lines.append("")
    return lines
