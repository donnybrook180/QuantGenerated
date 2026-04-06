from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime

from quant_system.config import SystemConfig
from quant_system.integrations.mt5 import MT5Error
from quant_system.live.app import resolve_live_deployment_paths
from quant_system.live.deploy import load_symbol_deployment
from quant_system.live.journal import LIVE_ARTIFACTS_DIR, write_live_incident, write_live_run_journal
from quant_system.live.runtime import MT5LiveExecutor


STATE_PATH = LIVE_ARTIFACTS_DIR / "loop_state.json"


def _load_state() -> dict[str, dict[str, object]]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_state(state: dict[str, dict[str, object]]) -> None:
    LIVE_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _action_key(symbol: str, candidate_name: str) -> str:
    return f"{symbol}::{candidate_name}"


def _normalize_action_label(value: str) -> str:
    normalized = value
    for prefix in ("dry_run_", "duplicate_skipped::"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
    return normalized


def _should_skip_duplicate(state: dict[str, dict[str, object]], symbol: str, action) -> bool:
    if action.signal_timestamp is None:
        return False
    key = _action_key(symbol, action.candidate_name)
    previous = state.get(key)
    if previous is None:
        return False
    return (
        previous.get("signal_timestamp") == action.signal_timestamp.isoformat()
        and previous.get("signal_side") == action.signal_side.value
        and _normalize_action_label(str(previous.get("intended_action", ""))) == _normalize_action_label(action.intended_action)
    )


def _record_action_state(state: dict[str, dict[str, object]], symbol: str, action) -> None:
    key = _action_key(symbol, action.candidate_name)
    state[key] = {
        "signal_timestamp": action.signal_timestamp.isoformat() if action.signal_timestamp else "",
        "signal_side": action.signal_side.value,
        "intended_action": action.intended_action,
        "updated_at": datetime.now(UTC).isoformat(),
    }


def main() -> int:
    config = SystemConfig()
    paths = resolve_live_deployment_paths(sys.argv[1:])
    if not paths:
        print(
            "No live deployment artifacts found. Run main_symbol_research.py first so it exports "
            "artifacts/deploy/<symbol>.live.json."
        )
        return 1

    print(f"Starting live loop. Poll seconds: {config.mt5.poll_seconds}")
    print(f"Live trading enabled: {'yes' if config.execution.live_trading_enabled else 'no (dry-run)'}")
    state = _load_state()

    while True:
        cycle_started = datetime.now(UTC).isoformat()
        print(f"Cycle started: {cycle_started}")
        for path in paths:
            deployment = load_symbol_deployment(path)
            if not deployment.strategies:
                print(f"{deployment.symbol}: no active live strategies in {path}")
                continue
            executor = MT5LiveExecutor(deployment, config)
            try:
                result = executor.run_once(
                    should_skip_duplicate=lambda action, symbol=deployment.symbol: _should_skip_duplicate(state, symbol, action)
                )
            except MT5Error as exc:
                incident_path = write_live_incident(deployment.symbol, str(path), str(exc))
                print(f"{deployment.symbol}: MT5 live run failed: {exc}")
                print(f"Incident log: {incident_path}")
                continue

            filtered_actions = []
            for action in result.actions:
                _record_action_state(state, result.symbol, action)
                filtered_actions.append(asdict(action))
            _save_state(state)

            journal_path = write_live_run_journal(result, str(path))
            print(f"Symbol: {result.symbol}")
            print(f"Broker symbol: {result.broker_symbol}")
            print(f"Account mode: {result.account_mode_label}")
            print(f"Strategy isolation supported: {'yes' if result.strategy_isolation_supported else 'no'}")
            print(f"Journal: {journal_path}")
            for action in filtered_actions:
                print(
                    f"- {action['candidate_name']}: signal={action['signal_side']} "
                    f"ts={action['signal_timestamp']} action={action['intended_action']}"
                )
            print("")
        time.sleep(max(config.mt5.poll_seconds, 5))


if __name__ == "__main__":
    raise SystemExit(main())
