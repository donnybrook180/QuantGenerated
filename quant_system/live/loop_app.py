from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from quant_system.artifacts import ensure_dir, live_venue_dir
from quant_system.config import SystemConfig
from quant_system.integrations.mt5 import MT5Error
from quant_system.interpreter.reporting import generate_market_interpreter_report
from quant_system.interpreter.research import generate_interpreter_research_report
from quant_system.live.activity import generate_improvement_activity_report
from quant_system.live.adaptation import adapt_deployment_for_execution, generate_execution_adaptation_report, summarize_execution_adaptation
from quant_system.live.app import configure_live_runtime, resolve_live_deployment_paths, resolve_live_portfolio_weights, resolve_live_strategy_weights
from quant_system.live.autopsy import generate_live_research_queue, maybe_run_auto_research
from quant_system.live.deploy import load_symbol_deployment
from quant_system.live.health import generate_live_health_report
from quant_system.live.journal import LIVE_ARTIFACTS_DIR, write_live_incident, write_live_run_journal
from quant_system.live.runtime import MT5LiveExecutor
from quant_system.live.tca_adaptation_impact import generate_tca_adaptation_impact_report
from quant_system.live.tca_impact import generate_tca_impact_report
from quant_system.tca import generate_tca_report, summarize_tca_overview


def _state_path(venue_key: str) -> Path:
    return live_venue_dir(venue_key) / "state" / "loop_state.json"


def _load_state(state_path: Path) -> dict[str, dict[str, object]]:
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_state(state: dict[str, dict[str, object]], state_path: Path) -> None:
    ensure_dir(state_path.parent)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _action_key(venue_key: str, symbol: str, candidate_name: str) -> str:
    return f"{venue_key}::{symbol}::{candidate_name}"


def _normalize_action_label(value: str) -> str:
    normalized = value
    for prefix in ("dry_run_", "duplicate_skipped::"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
    return normalized


def should_skip_duplicate(
    state: dict[str, dict[str, object]],
    venue_key: str,
    symbol: str,
    action,
) -> bool:
    if action.signal_timestamp is None:
        return False
    key = _action_key(venue_key, symbol, action.candidate_name)
    previous = state.get(key)
    if previous is None:
        return False
    return (
        previous.get("signal_timestamp") == action.signal_timestamp.isoformat()
        and previous.get("signal_side") == action.signal_side.value
        and _normalize_action_label(str(previous.get("intended_action", ""))) == _normalize_action_label(action.intended_action)
    )


def record_action_state(
    state: dict[str, dict[str, object]],
    venue_key: str,
    symbol: str,
    action,
) -> None:
    key = _action_key(venue_key, symbol, action.candidate_name)
    state[key] = {
        "signal_timestamp": action.signal_timestamp.isoformat() if action.signal_timestamp else "",
        "signal_side": action.signal_side.value,
        "intended_action": action.intended_action,
        "updated_at": datetime.now(UTC).isoformat(),
    }


def _run_report(label: str, builder):
    try:
        return builder(), None
    except Exception as exc:
        return None, f"{label} skipped: {exc}"


def _print_loaded_deployments(paths: list[Path]) -> None:
    print("Loaded live deployments:")
    for path in paths:
        deployment = load_symbol_deployment(path)
        active_strategy_names = [strategy.candidate_name for strategy in deployment.strategies]
        strategies_label = ", ".join(active_strategy_names) if active_strategy_names else "none"
        print(
            f"- {deployment.symbol}: status={deployment.symbol_status} "
            f"broker={deployment.broker_symbol} strategies={strategies_label}"
        )
    print("")


def _run_symbol_cycle(
    paths: list[Path],
    config: SystemConfig,
    state: dict[str, dict[str, object]],
) -> None:
    portfolio_weights = resolve_live_portfolio_weights(paths)
    strategy_weights = resolve_live_strategy_weights(paths)
    for path in paths:
        deployment = load_symbol_deployment(path)
        if deployment.symbol_status == "research_only" and not config.execution.mini_trades_enabled:
            print(f"{deployment.symbol}: skipped ({deployment.symbol_status}) - Enable MINI_TRADES=true to include.")
            continue

        deployment, adaptation = adapt_deployment_for_execution(deployment, config)
        if not deployment.strategies:
            print(f"{deployment.symbol}: no active live strategies in {path}")
            continue

        portfolio_weight = portfolio_weights.get(deployment.symbol.upper(), 0.0)
        executor = MT5LiveExecutor(
            deployment,
            config,
            portfolio_weight=portfolio_weight,
            strategy_portfolio_weights=strategy_weights.get(deployment.symbol.upper(), {}),
        )
        try:
            result = executor.run_once(
                should_skip_duplicate=lambda action, symbol=deployment.symbol, venue=deployment.venue_key: should_skip_duplicate(
                    state,
                    venue,
                    symbol,
                    action,
                )
            )
        except MT5Error as exc:
            incident_path = write_live_incident(deployment.symbol, str(path), str(exc), deployment.venue_key)
            print(f"{deployment.symbol}: MT5 live run failed: {exc}")
            print(f"Incident log: {incident_path}")
            continue

        filtered_actions = []
        for action in result.actions:
            record_action_state(state, deployment.venue_key, result.symbol, action)
            filtered_actions.append(asdict(action))
        _save_state(state, _state_path(deployment.venue_key))

        journal_path = write_live_run_journal(result, str(path), deployment.venue_key)
        print(f"Symbol: {result.symbol}")
        print(f"Broker symbol: {result.broker_symbol}")
        print(f"Symbol status: {deployment.symbol_status}")
        print(f"Execution adaptation: {summarize_execution_adaptation(adaptation)}")
        print(f"Account mode: {result.account_mode_label}")
        print(f"Strategy isolation supported: {'yes' if result.strategy_isolation_supported else 'no'}")
        print(f"Portfolio weight: {result.portfolio_weight:.2f}")
        if result.regime_snapshot is not None:
            print(
                f"Regime: {result.regime_snapshot.regime_label} "
                f"vol_pct={result.regime_snapshot.vol_percentile:.2f} "
                f"risk={result.regime_snapshot.risk_multiplier:.2f}"
            )
        print(f"Journal: {journal_path}")
        for action in filtered_actions:
            strategy = next((item for item in deployment.strategies if item.candidate_name == action["candidate_name"]), None)
            print(
                f"- {action['candidate_name']}: signal={action['signal_side']} "
                f"ts={action['signal_timestamp']} action={action['intended_action']} "
                f"regime={action.get('regime_label', '')} "
                f"vol_pct={action.get('vol_percentile', 0.0):.2f} "
                f"risk={action.get('risk_multiplier', 0.0):.2f} "
                f"alloc={action.get('allocation_fraction', 0.0):.2f} "
                f"portfolio={action.get('portfolio_weight', 0.0):.2f} "
                f"base_alloc={action.get('base_allocation_weight', 1.0):.2f} "
                f"size_factor={action.get('effective_size_factor', 0.0):.3f} "
                f"risk_budget={action.get('risk_budget_cash', 0.0):.2f} "
                f"tier={action.get('promotion_tier', 'core')} "
                f"score={action.get('allocator_score', 0.0):.2f}"
            )
            if action.get("veto_reason"):
                print(f"  veto: {action['veto_reason']}")
            if action.get("interpreter_reason"):
                print(
                    f"  interpreter: reason={action['interpreter_reason']} "
                    f"bias={action.get('interpreter_bias', '')} "
                    f"confidence={float(action.get('interpreter_confidence', 0.0) or 0.0):.2f}"
                )
            if strategy is not None and strategy.policy_summary:
                print(f"  policy: {strategy.policy_summary}")
        print("")


def _run_cycle_reports(config: SystemConfig) -> None:
    report_errors: list[str] = []

    tca_report, error = _run_report("TCA", lambda: generate_tca_report(config))
    if error is not None:
        report_errors.append(error)

    adaptation_report, error = _run_report(
        "Execution adaptation report",
        lambda: generate_execution_adaptation_report(config),
    )
    if error is not None:
        report_errors.append(error)

    impact_report, error = _run_report("TCA impact report", lambda: generate_tca_impact_report(config))
    if error is not None:
        report_errors.append(error)

    adaptation_impact_report, error = _run_report(
        "TCA adaptation impact report",
        lambda: generate_tca_adaptation_impact_report(config),
    )
    if error is not None:
        report_errors.append(error)

    research_queue_report, error = _run_report("Live research queue", lambda: generate_live_research_queue(config))
    if error is not None:
        report_errors.append(error)

    improvement_activity_report, error = _run_report(
        "Live improvement activity report",
        generate_improvement_activity_report,
    )
    if error is not None:
        report_errors.append(error)

    market_interpreter_report, error = _run_report(
        "Market interpreter report",
        lambda: generate_market_interpreter_report(config),
    )
    if error is not None:
        report_errors.append(error)

    market_interpreter_research_report, error = _run_report(
        "Market interpreter research queue",
        lambda: generate_interpreter_research_report(config),
    )
    if error is not None:
        report_errors.append(error)

    health_report, error = _run_report("Health report", lambda: generate_live_health_report(config))
    if error is not None:
        report_errors.append(error)

    auto_research_lines = maybe_run_auto_research(config)
    if tca_report is not None:
        print(f"TCA: {summarize_tca_overview(tca_report)}")
        print(f"TCA report: {tca_report.report_path}")
    if impact_report is not None:
        print(f"TCA impact report: {impact_report}")
    if adaptation_impact_report is not None:
        print(f"TCA adaptation impact report: {adaptation_impact_report}")
    if adaptation_report is not None:
        print(f"Execution adaptation report: {adaptation_report}")
    if research_queue_report is not None:
        print(f"Live research queue: {research_queue_report}")
    if improvement_activity_report is not None:
        print(f"Live improvement activity report: {improvement_activity_report}")
    if market_interpreter_report is not None:
        print(f"Market interpreter report: {market_interpreter_report}")
    if market_interpreter_research_report is not None:
        print(f"Market interpreter research queue: {market_interpreter_research_report}")
    for line in auto_research_lines:
        print(line)
    if health_report is not None:
        print(f"Health report: {health_report}")
    for error in report_errors:
        print(error)
    print("")


def main(argv: list[str] | None = None) -> int:
    args = argv or []
    config, _symbols = configure_live_runtime(args)
    paths = resolve_live_deployment_paths(args, config)
    if not paths:
        print(
            "No live deployment artifacts found. Run main_symbol_research.py first so it exports "
            "artifacts/deploy/<venue>/<symbol>/live.json and stores research outputs under artifacts/research/<symbol>/."
        )
        return 1

    print(f"Starting live loop. Poll seconds: {config.mt5.poll_seconds}")
    print(f"Live trading enabled: {'yes' if config.execution.live_trading_enabled else 'no (dry-run)'}")
    print(f"Mini-trades (Calibration) mode: {'enabled' if config.execution.mini_trades_enabled else 'disabled'}")
    print(
        "MT5 config: "
        f"login={config.mt5.login} "
        f"server={config.mt5.server} "
        f"broker={config.mt5.prop_broker} "
        f"terminal_path={config.mt5.terminal_path}"
    )
    _print_loaded_deployments(paths)
    state = _load_state(_state_path(str(config.mt5.prop_broker)))

    while True:
        cycle_started = datetime.now(UTC).isoformat()
        print(f"Cycle started: {cycle_started}")
        _run_symbol_cycle(paths, config, state)
        _run_cycle_reports(config)
        time.sleep(max(config.mt5.poll_seconds, 5))
