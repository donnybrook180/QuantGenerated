from __future__ import annotations

import sys

import _bootstrap  # noqa: F401

from quant_system.ai.storage import ExperimentStore
from quant_system.config import MT5Config, SystemConfig
from quant_system.integrations.mt5 import MT5Client
from quant_system.symbols import resolve_symbol_request


def _reconcile_symbol(requested_symbol: str) -> list[str]:
    config = SystemConfig()
    store = ExperimentStore(config.ai.experiment_database_path, read_only=True)
    resolved = resolve_symbol_request(requested_symbol)
    rows = store.list_mt5_fill_events(resolved.broker_symbol)
    unresolved = [row for row in rows if float(row.get("fill_price") or 0.0) <= 0.0]
    lines = [
        f"Requested symbol: {requested_symbol}",
        f"Broker symbol: {resolved.broker_symbol}",
        f"Recorded fills: {len(rows)}",
        f"Unresolved fills: {len(unresolved)}",
    ]
    if not unresolved:
        lines.append("Resolved now: 0")
        return lines

    client = MT5Client(MT5Config(symbol=resolved.broker_symbol, database_path=config.ai.experiment_database_path))
    resolved_count = 0
    client.initialize()
    try:
        for row in unresolved:
            resolution = client.reconcile_stored_fill_event(row)
            if resolution is None:
                continue
            store.update_mt5_fill_event_resolution(
                int(resolution["fill_id"]),
                fill_price=float(resolution["fill_price"]),
                slippage_points=float(resolution["slippage_points"]),
                slippage_bps=float(resolution["slippage_bps"]),
                costs=float(resolution["costs"]),
                metadata_updates=dict(resolution["metadata_updates"]),
            )
            resolved_count += 1
    finally:
        client.shutdown()
    lines.append(f"Resolved now: {resolved_count}")
    return lines


def main() -> int:
    requested_symbols = tuple(item.strip() for item in sys.argv[1:] if item.strip())
    if not requested_symbols:
        requested_symbols = ("EURUSD", "JP225", "EU50", "UK100", "XAUUSD", "US500", "US100")
    blocks: list[str] = []
    for symbol in requested_symbols:
        blocks.extend(_reconcile_symbol(symbol))
        blocks.append("")
    print("\n".join(blocks[:-1] if blocks else blocks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
