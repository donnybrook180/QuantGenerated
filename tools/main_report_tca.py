from __future__ import annotations

import sys

import _bootstrap  # noqa: F401

from quant_system.config import SystemConfig
from quant_system.tca import generate_tca_report


def main() -> int:
    broker_symbol = sys.argv[1].strip() if len(sys.argv) > 1 and sys.argv[1].strip() else None
    report = generate_tca_report(SystemConfig(), broker_symbol=broker_symbol)
    if report.overview is None:
        print(f"TCA report: {report.report_path}")
        print("No fills found in mt5_fill_events.")
        return 0
    print(f"TCA report: {report.report_path}")
    print(
        "overview: "
        f"fills={report.overview.fill_count} "
        f"weighted_touch_slippage_bps={report.overview.weighted_touch_slippage_bps:.4f} "
        f"weighted_shortfall_bps={report.overview.weighted_shortfall_bps:.4f} "
        f"adverse_fill_rate_pct={report.overview.adverse_touch_fill_rate_pct:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
