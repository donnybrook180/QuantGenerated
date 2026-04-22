from __future__ import annotations

import sys

import _bootstrap  # noqa: F401

from quant_system.ai.storage import ExperimentStore
from quant_system.config import SystemConfig
from quant_system.symbols import resolve_symbol_request


DEFAULT_SYMBOLS: tuple[str, ...] = ("EURUSD", "JP225", "EU50", "UK100")


def _resolution_source(row: dict[str, object]) -> str:
    metadata = row.get("metadata") or {}
    explicit = str(metadata.get("fill_resolution_source") or "").strip()
    if explicit:
        return explicit
    if int(metadata.get("deal_ticket") or 0) > 0:
        return "deal_history"
    if int(metadata.get("broker_position_id") or 0) > 0 and float(row.get("fill_price") or 0.0) > 0.0:
        return "position_open"
    if int(metadata.get("order_ticket") or 0) > 0 and float(row.get("fill_price") or 0.0) > 0.0:
        return "order_history"
    return "unknown"


def _report_symbol(requested_symbol: str) -> list[str]:
    config = SystemConfig()
    store = ExperimentStore(config.ai.experiment_database_path, read_only=True)
    resolved = resolve_symbol_request(requested_symbol)
    rows = store.list_mt5_fill_events(broker_symbol=resolved.broker_symbol)
    valid_price_rows = [row for row in rows if float(row.get("fill_price") or 0.0) > 0.0]
    valid_deal_rows = [row for row in rows if int((row.get("metadata") or {}).get("deal_ticket") or 0) > 0]
    invalid_rows = [row for row in rows if float(row.get("fill_price") or 0.0) <= 0.0]
    source_counts: dict[str, int] = {}
    for row in valid_price_rows:
        source = _resolution_source(row)
        source_counts[source] = source_counts.get(source, 0) + 1

    lines = [
        f"Requested symbol: {requested_symbol}",
        f"Profile symbol: {resolved.profile_symbol}",
        f"Broker symbol: {resolved.broker_symbol}",
        f"Recorded fills: {len(rows)}",
        f"Rows with fill_price > 0: {len(valid_price_rows)}",
        f"Rows with deal_ticket > 0: {len(valid_deal_rows)}",
        "Valid fill sources: "
        + (", ".join(f"{name}={count}" for name, count in sorted(source_counts.items())) if source_counts else "none"),
    ]
    if rows:
        lines.append(f"First fill: {rows[0].get('event_timestamp')}")
        lines.append(f"Last fill: {rows[-1].get('event_timestamp')}")
    if valid_price_rows:
        latest_valid = valid_price_rows[-1]
        latest_valid_meta = latest_valid.get("metadata") or {}
        lines.extend(
            [
                "Latest valid fill: "
                f"ts={latest_valid.get('event_timestamp')} "
                f"fill_price={float(latest_valid.get('fill_price') or 0.0):.5f} "
                f"requested_price={float(latest_valid.get('requested_price') or 0.0):.5f} "
                f"deal_ticket={int(latest_valid_meta.get('deal_ticket') or 0)} "
                f"order_ticket={int(latest_valid_meta.get('order_ticket') or 0)} "
                f"fill_source={_resolution_source(latest_valid)}",
            ]
        )
    if invalid_rows:
        latest_invalid = invalid_rows[-1]
        latest_invalid_meta = latest_invalid.get("metadata") or {}
        lines.extend(
            [
                "Latest invalid fill: "
                f"ts={latest_invalid.get('event_timestamp')} "
                f"fill_price={float(latest_invalid.get('fill_price') or 0.0):.5f} "
                f"requested_price={float(latest_invalid.get('requested_price') or 0.0):.5f} "
                f"deal_ticket={int(latest_invalid_meta.get('deal_ticket') or 0)} "
                f"order_ticket={int(latest_invalid_meta.get('order_ticket') or 0)} "
                f"fill_source={_resolution_source(latest_invalid)}",
            ]
        )
    if rows and not valid_price_rows:
        lines.append("Status: FAIL - fills exist but none have a valid fill_price yet.")
    elif valid_price_rows and len(valid_price_rows) == len(rows):
        lines.append("Status: PASS - all recorded fills have valid fill prices.")
    elif valid_price_rows:
        lines.append("Status: MIXED - new fill capture is working, but older invalid rows still exist.")
    else:
        lines.append("Status: WAITING - no fills recorded yet for this symbol.")
    return lines


def main() -> int:
    requested_symbols = tuple(item.strip() for item in sys.argv[1:] if item.strip()) or DEFAULT_SYMBOLS
    blocks: list[str] = []
    for symbol in requested_symbols:
        blocks.extend(_report_symbol(symbol))
        blocks.append("")
    print("\n".join(blocks[:-1] if blocks else blocks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
