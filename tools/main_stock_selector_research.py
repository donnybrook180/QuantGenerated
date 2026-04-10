from __future__ import annotations

import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from quant_system.artifacts import system_reports_dir
from quant_system.config import SystemConfig
from quant_system.research.app import run_symbol_research_app
from quant_system.research.stock_selector import select_top_stock_candidates, write_stock_selector_report


def main() -> int:
    config = SystemConfig()
    args = [item.strip().upper() for item in sys.argv[1:] if item.strip()]
    rows = select_top_stock_candidates(config, tuple(args) if args else None)
    selector_txt, selector_csv = write_stock_selector_report(rows)
    print(f"Stock selector report: {selector_txt}")
    print(f"Stock selector CSV: {selector_csv}")
    if not rows:
        print("No eligible stock candidates found.")
        return 1

    top_rows = rows[:3]
    report_lines = [
        "Stock Selector Research Batch",
        "",
        f"Selector report: {selector_txt}",
        f"Selector CSV: {selector_csv}",
        "",
    ]
    for row in top_rows:
        print(f"Running symbol research for {row.symbol}...")
        result_lines = run_symbol_research_app(row.symbol, row.broker_symbol)
        print("\n".join(result_lines))
        print("")
        report_lines.append(f"## {row.symbol}")
        report_lines.extend(result_lines)
        report_lines.append("")

    batch_report_path = system_reports_dir() / "stock_selector_research_batch.txt"
    batch_report_path.write_text("\n".join(report_lines).rstrip() + "\n", encoding="utf-8")
    print(f"Batch research report: {batch_report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
