from __future__ import annotations

import sys

import _bootstrap  # noqa: F401

from quant_system.allocator import build_portfolio_allocation


def main() -> int:
    requested = [item.strip() for item in sys.argv[1:] if item.strip()]
    allocations, report_path = build_portfolio_allocation(requested or None)
    print(f"Allocation report: {report_path}")
    if not allocations:
        print("No eligible symbol execution sets were found.")
        return 1

    for row in allocations:
        variant = row.variant_label or "default"
        if row.regime_filter_label:
            variant = f"{variant}|{row.regime_filter_label}"
        print(f"{row.symbol}: {row.weight_pct:.2f}%")
        print(f"  candidate: {row.candidate_name}")
        print(f"  variant: {variant}")
        print(
            "  robustness: "
            f"score={row.score:.4f} wf_pass={row.walk_forward_pass_rate_pct:.2f}% "
            f"val_pf={row.validation_profit_factor:.2f} test_pf={row.test_profit_factor:.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
