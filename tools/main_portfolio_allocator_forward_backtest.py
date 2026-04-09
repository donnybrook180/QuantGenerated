from __future__ import annotations

import _bootstrap  # noqa: F401

from quant_system.allocator_forward_backtest import backtest_forward_portfolio_allocator


def main() -> int:
    summaries, report_path = backtest_forward_portfolio_allocator()
    print(f"Allocator forward backtest report: {report_path}")
    if not summaries:
        print("No forward allocator results were produced.")
        return 1
    for summary in summaries:
        print(
            f"{summary.method}: equity={summary.final_equity:.4f} "
            f"return={summary.total_return_pct:.2f}% buckets={summary.buckets} dd={summary.max_drawdown_pct:.2f}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
