from __future__ import annotations

import sys

import _bootstrap  # noqa: F401

from quant_system.config import SystemConfig
from quant_system.research.stock_selector import select_top_stock_candidates, write_stock_selector_report


def main() -> int:
    args = [item.strip().upper() for item in sys.argv[1:] if item.strip()]
    rows = select_top_stock_candidates(SystemConfig(), tuple(args) if args else None)
    txt_path, csv_path = write_stock_selector_report(rows)
    print(f"Stock selector report: {txt_path}")
    print(f"Stock selector CSV: {csv_path}")
    if not rows:
        print("No eligible stock candidates found.")
        return 1
    for row in rows:
        print(
            f"{row.rank}. {row.symbol} score={row.score:.2f} "
            f"adv=${row.average_daily_dollar_volume:,.0f} "
            f"gap={row.opening_gap_pct * 100.0:.2f}% rel_vol={row.relative_volume:.2f} "
            f"atr={row.atr_proxy:.4f} source={row.source}"
        )
        if row.reasons:
            print(f"   reasons: {', '.join(row.reasons)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
