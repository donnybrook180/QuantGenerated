from __future__ import annotations

import sys

import _bootstrap  # noqa: F401

from quant_system.allocator_backtest import backtest_portfolio_allocator


def main() -> int:
    requested = [item.strip() for item in sys.argv[1:] if item.strip()]
    summaries, snapshots, report_path = backtest_portfolio_allocator(symbols_or_profiles=requested or None)
    print(f"Allocator backtest report: {report_path}")
    if not snapshots:
        print("No historical snapshots matched the requested symbol set.")
        return 1
    for summary in summaries:
        print(f"{summary.method}: total={summary.total_snapshot_pnl:.2f} avg={summary.avg_snapshot_pnl:.2f} snapshots={summary.snapshots}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
