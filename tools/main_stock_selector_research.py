from __future__ import annotations

import sys

import _bootstrap  # noqa: F401

from quant_system.ai.storage import ExperimentStore
from quant_system.artifacts import symbol_profile_name, system_reports_dir
from quant_system.config import SystemConfig
from quant_system.research.app import run_symbol_research_app
from quant_system.research.stock_playbooks import allow_candidate_for_playbook, classify_stock_playbook
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
    playbook_rows = [classify_stock_playbook(row) for row in top_rows]
    report_lines = [
        "Stock Selector Research Batch",
        "",
        f"Selector report: {selector_txt}",
        f"Selector CSV: {selector_csv}",
        "",
    ]
    store = ExperimentStore(config.ai.experiment_database_path, read_only=True)
    for row in playbook_rows:
        print(f"Running symbol research for {row.symbol} ({row.playbook})...")
        result_lines = run_symbol_research_app(
            row.symbol,
            row.broker_symbol,
            candidate_name_prefixes=row.allowed_agent_prefixes,
        )
        print("\n".join(result_lines))
        print("")
        report_lines.append(f"## {row.symbol}")
        report_lines.append(f"Playbook: {row.playbook}")
        report_lines.append(f"Reasons: {', '.join(row.reasons)}")
        report_lines.extend(result_lines)
        profile_name = symbol_profile_name(row.symbol, str(config.mt5.prop_broker))
        candidates = store.list_latest_symbol_research_candidates(profile_name)
        allowed = [str(candidate["candidate_name"]) for candidate in candidates if allow_candidate_for_playbook(str(candidate["candidate_name"]), row)]
        report_lines.append("Playbook-allowed candidates: " + (", ".join(allowed[:15]) if allowed else "none"))
        report_lines.append("")

    batch_report_path = system_reports_dir() / "stock_selector_research_batch.txt"
    batch_report_path.write_text("\n".join(report_lines).rstrip() + "\n", encoding="utf-8")
    print(f"Batch research report: {batch_report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
