from __future__ import annotations

import sys

from quant_system.ai.storage import ExperimentStore
from quant_system.config import SystemConfig
from quant_system.costs import apply_ftmo_cost_profile
from quant_system.symbols import resolve_symbol_request


def _report_symbol(requested_symbol: str, broker_symbol: str | None = None) -> list[str]:
    config = SystemConfig()
    resolved = resolve_symbol_request(requested_symbol, broker_symbol)
    store = ExperimentStore(config.ai.experiment_database_path, read_only=True)
    profile = apply_ftmo_cost_profile(config, resolved.profile_symbol, resolved.broker_symbol)
    fill_summary = store.load_mt5_fill_summary(resolved.broker_symbol)
    fill_calibration = store.load_mt5_fill_calibration(resolved.broker_symbol)

    lines = [
        f"Requested symbol: {resolved.requested_symbol}",
        f"Profile symbol: {resolved.profile_symbol}",
        f"Data symbol: {resolved.data_symbol}",
        f"Broker symbol: {resolved.broker_symbol}",
        f"Active spread points: {config.execution.spread_points:.8f}",
        f"Active slippage bps: {config.execution.slippage_bps:.6f}",
        f"Cost notes: {profile.notes}",
    ]
    if fill_summary is None:
        lines.append("Fill history: none")
        return lines

    lines.extend(
        [
            f"Fill count: {fill_summary['fill_count']}",
            f"First fill: {fill_summary['first_fill_at']}",
            f"Last fill: {fill_summary['last_fill_at']}",
            f"Average spread points: {float(fill_summary['avg_spread_points']):.8f}",
            f"Average slippage bps: {float(fill_summary['avg_slippage_bps']):.6f}",
        ]
    )
    if fill_calibration is not None:
        lines.extend(
            [
                f"Calibration sample size: {int(fill_calibration['count'])}",
                f"Median spread points: {float(fill_calibration['median_spread_points']):.8f}",
                f"P75 spread points: {float(fill_calibration['p75_spread_points']):.8f}",
                f"Median slippage bps: {float(fill_calibration['median_slippage_bps']):.6f}",
                f"P75 slippage bps: {float(fill_calibration['p75_slippage_bps']):.6f}",
                f"P90 slippage bps: {float(fill_calibration['p90_slippage_bps']):.6f}",
            ]
        )
    return lines


def _report_all_symbols() -> list[str]:
    config = SystemConfig()
    store = ExperimentStore(config.ai.experiment_database_path, read_only=True)
    symbols = store.list_mt5_fill_symbols()
    if not symbols:
        return ["No MT5 fill history found."]
    lines = ["MT5 fill calibration coverage:"]
    for broker_symbol in symbols:
        summary = store.load_mt5_fill_summary(broker_symbol)
        calibration = store.load_mt5_fill_calibration(broker_symbol)
        if summary is None:
            continue
        lines.append(
            f"- {broker_symbol}: fills={summary['fill_count']} last={summary['last_fill_at']} "
            f"avg_spread={float(summary['avg_spread_points']):.8f} "
            f"avg_slippage_bps={float(summary['avg_slippage_bps']):.6f} "
            f"calibration={'yes' if calibration is not None else 'no'}"
        )
    return lines


def main() -> int:
    if len(sys.argv) == 1:
        print("\n".join(_report_all_symbols()))
        return 0
    requested_symbol = sys.argv[1].strip()
    broker_symbol = sys.argv[2].strip() if len(sys.argv) >= 3 and sys.argv[2].strip() else None
    print("\n".join(_report_symbol(requested_symbol, broker_symbol)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
