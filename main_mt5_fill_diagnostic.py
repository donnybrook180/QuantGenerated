from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta

import MetaTrader5 as mt5

from quant_system.config import MT5Config, SystemConfig
from quant_system.integrations.mt5 import MT5Client


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _coerce_record(item) -> dict[str, object]:
    if item is None:
        return {}
    if hasattr(item, "_asdict"):
        return dict(item._asdict())
    keys = getattr(item, "_fields", None)
    if keys:
        return {key: getattr(item, key, None) for key in keys}
    result: dict[str, object] = {}
    for name in dir(item):
        if name.startswith("_"):
            continue
        try:
            value = getattr(item, name)
        except Exception:
            continue
        if callable(value):
            continue
        result[name] = value
    return result


def _find_fill_row(order_ticket: int) -> tuple[str, dict[str, object]] | None:
    config = SystemConfig()
    if not config.postgres.enabled:
        return None
    import psycopg

    with psycopg.connect(config.postgres.dsn(), autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT broker_symbol, metadata_json
                FROM mt5_fill_events
                WHERE CAST(COALESCE(metadata_json, '{}') AS TEXT) LIKE %s
                ORDER BY event_timestamp DESC
                LIMIT 1
                """,
                [f'%"order_ticket": {order_ticket}%'],
            )
            row = cursor.fetchone()
    if row is None:
        return None
    return str(row[0]), json.loads(row[1] or "{}")


def diagnose_order(order_ticket: int, symbol: str | None = None) -> dict[str, object]:
    system = SystemConfig()
    broker_symbol = symbol
    if broker_symbol is None:
        fill_row = _find_fill_row(order_ticket)
        if fill_row is not None:
            broker_symbol = fill_row[0]
    if not broker_symbol:
        broker_symbol = system.mt5.symbol

    client = MT5Client(MT5Config(symbol=broker_symbol))
    client.initialize()
    try:
        end = datetime.now(UTC)
        start = end - timedelta(days=3)
        deals = mt5.history_deals_get(start, end) or []
        orders = mt5.history_orders_get(start, end) or []
        matching_deals = []
        for item in deals:
            record = _coerce_record(item)
            if int(record.get("order") or 0) == order_ticket or int(record.get("ticket") or 0) == order_ticket:
                matching_deals.append(record)
        matching_orders = []
        for item in orders:
            record = _coerce_record(item)
            if int(record.get("ticket") or 0) == order_ticket or int(record.get("position_id") or 0) == order_ticket:
                matching_orders.append(record)
        return {
            "requested_order_ticket": order_ticket,
            "broker_symbol": broker_symbol,
            "mt5_last_error": mt5.last_error(),
            "matching_deals": matching_deals,
            "matching_orders": matching_orders,
        }
    finally:
        client.shutdown()


def main() -> int:
    raw_args = [item.strip() for item in sys.argv[1:] if item.strip()]
    if not raw_args:
        print("Usage: .\\.venv\\Scripts\\python.exe main_mt5_fill_diagnostic.py <order_ticket> [more_tickets]")
        return 1
    payloads = []
    for raw in raw_args:
        payloads.append(diagnose_order(int(raw)))
    print(json.dumps(payloads, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
