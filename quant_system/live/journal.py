from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from quant_system.live.runtime import LiveRunResult


LIVE_ARTIFACTS_DIR = Path("artifacts") / "live"


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def _json_safe(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def write_live_run_journal(result: LiveRunResult, deployment_path: str) -> Path:
    LIVE_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = LIVE_ARTIFACTS_DIR / f"{_slug(result.symbol)}_{timestamp}_journal.json"
    payload = {
        "symbol": result.symbol,
        "broker_symbol": result.broker_symbol,
        "deployment_path": deployment_path,
        "account_mode_label": result.account_mode_label,
        "strategy_isolation_supported": result.strategy_isolation_supported,
        "actions": [_json_safe(asdict(action)) for action in result.actions],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def write_live_incident(symbol: str, deployment_path: str, message: str) -> Path:
    LIVE_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = LIVE_ARTIFACTS_DIR / f"{_slug(symbol)}_{timestamp}_incident.txt"
    path.write_text(
        "\n".join(
            [
                f"symbol: {symbol}",
                f"deployment_path: {deployment_path}",
                f"timestamp_utc: {timestamp}",
                f"message: {message}",
            ]
        ),
        encoding="utf-8",
    )
    return path
