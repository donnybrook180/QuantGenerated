from __future__ import annotations

import sys

import _bootstrap  # noqa: F401

from quant_system.config import SystemConfig
from quant_system.symbol_research import _load_symbol_features_variant, _research_variant_plan, _symbol_research_history_days
from quant_system.symbols import resolve_symbol_request


def main() -> int:
    config = SystemConfig()
    if len(sys.argv) >= 2:
        requested_symbol = sys.argv[1].strip()
        broker_symbol = sys.argv[2].strip() if len(sys.argv) > 2 and sys.argv[2].strip() else None
    else:
        requested_symbol = config.symbol_research.symbol.strip()
        broker_symbol = config.symbol_research.broker_symbol.strip() or None
        if not requested_symbol:
            print("Usage: .\\.venv\\Scripts\\python.exe main_refresh_symbol_cache.py <symbol> [broker_symbol]")
            return 1

    resolved = resolve_symbol_request(requested_symbol, broker_symbol)
    config.symbol_research.broker_symbol = resolved.broker_symbol
    config.market_data.history_days = _symbol_research_history_days(config, resolved.profile_symbol)
    timeframe_specs, _, _ = _research_variant_plan(resolved.profile_symbol, "full")
    lines = [
        f"Requested symbol: {resolved.requested_symbol}",
        f"Symbol: {resolved.profile_symbol}",
        f"Data symbol: {resolved.data_symbol}",
    ]

    for timeframe_label, multiplier, timespan in timeframe_specs:
        features, source = _load_symbol_features_variant(
            config,
            resolved.data_symbol,
            multiplier,
            timespan,
            resolved.broker_symbol,
            resolved.profile_symbol,
        )
        lines.append(f"{timeframe_label}: source={source} bars={len(features)}")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
