from __future__ import annotations

from pathlib import Path

from quant_system.artifacts import list_deployment_paths
from quant_system.config import SystemConfig, apply_mt5_broker
from quant_system.integrations.mt5 import MT5Error
from quant_system.live.adaptation import adapt_deployment_for_execution, summarize_execution_adaptation
from quant_system.live.deploy import DEPLOY_DIR, deployment_path_for_symbol, load_symbol_deployment
from quant_system.live.journal import write_live_incident, write_live_run_journal
from quant_system.live.runtime import MT5LiveExecutor
from quant_system.symbols import resolve_symbol_request
from quant_system.venues import normalize_venue_key


def parse_live_cli_args(args: list[str]) -> tuple[str | None, list[str]]:
    broker: str | None = None
    symbols: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--broker":
            if index + 1 >= len(args):
                raise ValueError("Missing value after --broker.")
            broker = normalize_venue_key(args[index + 1])
            index += 2
            continue
        symbols.append(token)
        index += 1
    return broker, symbols


def configure_live_runtime(args: list[str], config: SystemConfig | None = None) -> tuple[SystemConfig, list[str]]:
    config = config or SystemConfig()
    broker_override, symbols = parse_live_cli_args(args)
    if broker_override:
        apply_mt5_broker(config, broker_override)
    return config, symbols


def resolve_live_deployment_paths(args: list[str], config: SystemConfig | None = None) -> list[Path]:
    config, symbols = configure_live_runtime(args, config)
    venue_key = str(config.mt5.prop_broker)
    if symbols:
        paths: list[Path] = []
        for raw_symbol in symbols:
            resolved = resolve_symbol_request(raw_symbol)
            path = deployment_path_for_symbol(resolved.profile_symbol, venue_key)
            if path.exists():
                paths.append(path)
        return paths
    if not DEPLOY_DIR.exists():
        return []
    return [
        path
        for path in list_deployment_paths()
        if normalize_venue_key(load_symbol_deployment(path).venue_key) == venue_key
    ]


def resolve_live_portfolio_weights(paths: list[Path]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for path in paths:
        deployment = load_symbol_deployment(path)
        if deployment.symbol_status == "research_only":
            continue
        weights[deployment.symbol.upper()] = 1.0
    return weights


def resolve_live_strategy_weights(paths: list[Path]) -> dict[str, dict[str, float]]:
    weights: dict[str, dict[str, float]] = {}
    for path in paths:
        deployment = load_symbol_deployment(path)
        if deployment.symbol_status == "research_only":
            continue
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
        if deployment.symbol_status == "research_only":
            lines.append(f"{deployment.symbol}: skipped ({deployment.symbol_status})")
            continue
        deployment, adaptation = adapt_deployment_for_execution(deployment, config)
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
            incident_path = write_live_incident(deployment.symbol, str(path), str(exc), deployment.venue_key)
            lines.append(f"{deployment.symbol}: MT5 live run failed: {exc}")
            lines.append(f"Incident log: {incident_path}")
            continue
        journal_path = write_live_run_journal(result, str(path), deployment.venue_key)
        lines.extend(
            [
                f"Symbol: {result.symbol}",
                f"Broker symbol: {result.broker_symbol}",
                f"Deployment: {path}",
                f"Symbol status: {deployment.symbol_status}",
                f"Execution adaptation: {summarize_execution_adaptation(adaptation)}",
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
                f"risk_budget={action.risk_budget_cash:.2f} "
                f"tier={action.promotion_tier} "
                f"score={action.allocator_score:.2f} magic={action.magic_number}"
            )
            if action.veto_reason:
                lines.append(f"  veto: {action.veto_reason}")
            if strategy is not None and strategy.policy_summary:
                lines.append(f"  policy: {strategy.policy_summary}")
        lines.append("")
    return lines
