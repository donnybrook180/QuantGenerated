from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import unittest
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from quant_system.artifacts import DEPLOY_DIR, RESEARCH_DIR, SYSTEM_DIR, artifact_slug, ensure_dir, system_reports_dir


DEFAULT_SYMBOLS = ("EURUSD", "XAUUSD", "JP225")
DEDICATED_TEST_MODULES = [
    "quant_system.test_symbol_resolution",
    "quant_system.test_venues_registry",
    "quant_system.test_mt5_integration",
    "quant_system.test_evaluation_report",
    "quant_system.test_interpreter_engines",
    "quant_system.test_interpreter_app",
    "quant_system.test_live_deploy_runtime",
    "quant_system.test_live_deployment_contracts",
    "quant_system.test_symbol_research_selection",
    "quant_system.test_symbol_research_viability",
    "quant_system.test_symbol_research_exports",
    "quant_system.test_research_end_to_end",
    "quant_system.test_research_artifacts",
    "quant_system.test_research_failure_modes",
    "quant_system.test_symbol_research_regressions",
]


@dataclass
class RegressionFailure:
    label: str
    detail: str


@dataclass
class SymbolSnapshotSummary:
    symbol: str
    deployment_status: str
    strategy_names: list[str]
    top_ranked_candidates: list[str]
    tier_counts: str
    failures: list[RegressionFailure]


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _baseline_dir() -> Path:
    return SYSTEM_DIR / "baselines" / "refactor_step1"


def _report_path() -> Path:
    return system_reports_dir() / "refactor_regression_report.json"


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _run_unittest_modules(modules: list[str]) -> bool:
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite(loader.loadTestsFromName(module_name) for module_name in modules)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return bool(result.wasSuccessful())


def _run_functional_suite(repo_root: Path) -> bool:
    result = subprocess.run(
        [sys.executable, "tools/main_test_functional_suite.py"],
        cwd=repo_root,
        check=False,
    )
    return result.returncode == 0


def _compare_deployment(symbol: str, baseline_dir: Path) -> list[RegressionFailure]:
    failures: list[RegressionFailure] = []
    slug = artifact_slug(symbol)
    baseline_path = baseline_dir / "symbols" / slug / "deploy" / "live.json"
    current_path = DEPLOY_DIR / slug / "live.json"
    if not baseline_path.exists():
        return [RegressionFailure(f"{symbol} deployment", f"Missing baseline file: {baseline_path}")]
    if not current_path.exists():
        return [RegressionFailure(f"{symbol} deployment", f"Missing current file: {current_path}")]

    baseline = _load_json(baseline_path)
    current = _load_json(current_path)

    for key in (
        "profile_name",
        "symbol",
        "data_symbol",
        "broker_symbol",
        "research_run_id",
        "execution_set_id",
        "execution_validation_summary",
        "symbol_status",
    ):
        if baseline.get(key) != current.get(key):
            failures.append(
                RegressionFailure(
                    f"{symbol} deployment",
                    f"Field '{key}' changed: baseline={baseline.get(key)!r} current={current.get(key)!r}",
                )
            )

    baseline_strategies = baseline.get("strategies", [])
    current_strategies = current.get("strategies", [])
    if not isinstance(baseline_strategies, list) or not isinstance(current_strategies, list):
        failures.append(RegressionFailure(f"{symbol} deployment", "Strategies payload is not a list"))
        return failures

    if len(baseline_strategies) != len(current_strategies):
        failures.append(
            RegressionFailure(
                f"{symbol} deployment",
                f"Strategy count changed: baseline={len(baseline_strategies)} current={len(current_strategies)}",
            )
        )
        return failures

    strategy_keys = (
        "candidate_name",
        "code_path",
        "strategy_family",
        "direction_mode",
        "direction_role",
        "promotion_tier",
        "variant_label",
        "regime_filter_label",
        "allowed_regimes",
        "blocked_regimes",
    )
    for index, (baseline_strategy, current_strategy) in enumerate(zip(baseline_strategies, current_strategies, strict=False), start=1):
        if not isinstance(baseline_strategy, dict) or not isinstance(current_strategy, dict):
            failures.append(RegressionFailure(f"{symbol} deployment", f"Strategy {index} is not a JSON object"))
            continue
        for key in strategy_keys:
            if baseline_strategy.get(key) != current_strategy.get(key):
                failures.append(
                    RegressionFailure(
                        f"{symbol} deployment",
                        f"Strategy {index} field '{key}' changed: baseline={baseline_strategy.get(key)!r} current={current_strategy.get(key)!r}",
                    )
                )

    return failures


def _deployment_summary(symbol: str) -> tuple[str, list[str]]:
    slug = artifact_slug(symbol)
    path = DEPLOY_DIR / slug / "live.json"
    if not path.exists():
        return "missing", []
    payload = _load_json(path)
    strategies = payload.get("strategies", [])
    names: list[str] = []
    if isinstance(strategies, list):
        for item in strategies:
            if isinstance(item, dict):
                names.append(str(item.get("candidate_name", "")))
    return str(payload.get("symbol_status", "")), names


def _extract_text_line(text: str, prefix: str) -> str:
    for line in text.splitlines():
        if line.startswith(prefix):
            return line.strip()
    return ""


def _extract_top_candidate_names(report_text: str, limit: int = 5) -> list[str]:
    names: list[str] = []
    in_ranked_candidates = False
    for raw_line in report_text.splitlines():
        line = raw_line.strip()
        if line == "Ranked candidates":
            in_ranked_candidates = True
            continue
        if line == "Top candidate-level winners":
            break
        if not in_ranked_candidates or not line or raw_line.startswith("  "):
            continue
        name = line.split(" [", 1)[0].strip()
        if name:
            names.append(name)
        if len(names) >= limit:
            break
    return names


def _compare_symbol_research_text(symbol: str, baseline_dir: Path) -> list[RegressionFailure]:
    failures: list[RegressionFailure] = []
    slug = artifact_slug(symbol)
    baseline_path = baseline_dir / "symbols" / slug / "reports" / "symbol_research.txt"
    current_path = RESEARCH_DIR / slug / "reports" / "symbol_research.txt"
    if not baseline_path.exists():
        return [RegressionFailure(f"{symbol} symbol_research.txt", f"Missing baseline file: {baseline_path}")]
    if not current_path.exists():
        return [RegressionFailure(f"{symbol} symbol_research.txt", f"Missing current file: {current_path}")]

    baseline_text = baseline_path.read_text(encoding="utf-8")
    current_text = current_path.read_text(encoding="utf-8")

    for prefix in ("Symbol research:", "Broker symbol:", "Data source:"):
        if _extract_text_line(baseline_text, prefix) != _extract_text_line(current_text, prefix):
            failures.append(
                RegressionFailure(
                    f"{symbol} symbol_research.txt",
                    f"Header line for '{prefix}' changed",
                )
            )

    baseline_names = _extract_top_candidate_names(baseline_text)
    current_names = _extract_top_candidate_names(current_text)
    if baseline_names != current_names:
        failures.append(
            RegressionFailure(
                f"{symbol} symbol_research.txt",
                f"Top ranked candidate names changed: baseline={baseline_names} current={current_names}",
            )
        )

    baseline_winners = _extract_text_line(baseline_text, "No candidate met the positive-PnL and PF>=1.0 threshold.")
    current_winners = _extract_text_line(current_text, "No candidate met the positive-PnL and PF>=1.0 threshold.")
    if bool(baseline_winners) != bool(current_winners):
        failures.append(
            RegressionFailure(
                f"{symbol} symbol_research.txt",
                "Top-winner summary shape changed",
            )
        )

    return failures


def _compare_symbol_research_csv(symbol: str, baseline_dir: Path) -> list[RegressionFailure]:
    failures: list[RegressionFailure] = []
    slug = artifact_slug(symbol)
    baseline_path = baseline_dir / "symbols" / slug / "reports" / "symbol_research.csv"
    current_path = RESEARCH_DIR / slug / "reports" / "symbol_research.csv"
    if not baseline_path.exists():
        return [RegressionFailure(f"{symbol} symbol_research.csv", f"Missing baseline file: {baseline_path}")]
    if not current_path.exists():
        return [RegressionFailure(f"{symbol} symbol_research.csv", f"Missing current file: {current_path}")]

    baseline_rows = _load_csv_rows(baseline_path)
    current_rows = _load_csv_rows(current_path)
    baseline_header = list(baseline_rows[0].keys()) if baseline_rows else []
    current_header = list(current_rows[0].keys()) if current_rows else []
    if baseline_header != current_header:
        failures.append(
            RegressionFailure(
                f"{symbol} symbol_research.csv",
                "CSV header changed",
            )
        )

    if len(baseline_rows) != len(current_rows):
        failures.append(
            RegressionFailure(
                f"{symbol} symbol_research.csv",
                f"Row count changed: baseline={len(baseline_rows)} current={len(current_rows)}",
            )
        )

    baseline_names = [row.get("name", "") for row in baseline_rows[:5]]
    current_names = [row.get("name", "") for row in current_rows[:5]]
    if baseline_names != current_names:
        failures.append(
            RegressionFailure(
                f"{symbol} symbol_research.csv",
                f"Top CSV names changed: baseline={baseline_names} current={current_names}",
            )
        )
    return failures


def _compare_viability_autopsy(symbol: str, baseline_dir: Path) -> list[RegressionFailure]:
    failures: list[RegressionFailure] = []
    slug = artifact_slug(symbol)
    baseline_path = baseline_dir / "symbols" / slug / "reports" / "viability_autopsy.txt"
    current_path = RESEARCH_DIR / slug / "reports" / "viability_autopsy.txt"
    if not baseline_path.exists():
        return [RegressionFailure(f"{symbol} viability_autopsy.txt", f"Missing baseline file: {baseline_path}")]
    if not current_path.exists():
        return [RegressionFailure(f"{symbol} viability_autopsy.txt", f"Missing current file: {current_path}")]

    baseline_text = baseline_path.read_text(encoding="utf-8")
    current_text = current_path.read_text(encoding="utf-8")
    for prefix in ("Execution validation summary:", "Tier counts:"):
        if _extract_text_line(baseline_text, prefix) != _extract_text_line(current_text, prefix):
            failures.append(
                RegressionFailure(
                    f"{symbol} viability_autopsy.txt",
                    f"Line for '{prefix}' changed",
                )
            )
    return failures


def _extract_tier_counts(symbol: str) -> str:
    slug = artifact_slug(symbol)
    current_path = RESEARCH_DIR / slug / "reports" / "viability_autopsy.txt"
    if not current_path.exists():
        return "missing"
    text = current_path.read_text(encoding="utf-8")
    return _extract_text_line(text, "Tier counts:") or "missing"


def _compare_snapshot_outputs(symbols: list[str], baseline_dir: Path) -> tuple[list[RegressionFailure], list[SymbolSnapshotSummary]]:
    failures: list[RegressionFailure] = []
    summaries: list[SymbolSnapshotSummary] = []
    for symbol in symbols:
        symbol_failures: list[RegressionFailure] = []
        symbol_failures.extend(_compare_deployment(symbol, baseline_dir))
        symbol_failures.extend(_compare_symbol_research_text(symbol, baseline_dir))
        symbol_failures.extend(_compare_symbol_research_csv(symbol, baseline_dir))
        symbol_failures.extend(_compare_viability_autopsy(symbol, baseline_dir))
        failures.extend(symbol_failures)
        status, strategy_names = _deployment_summary(symbol)
        report_path = RESEARCH_DIR / artifact_slug(symbol) / "reports" / "symbol_research.txt"
        top_ranked_candidates: list[str] = []
        if report_path.exists():
            top_ranked_candidates = _extract_top_candidate_names(report_path.read_text(encoding="utf-8"))
        summaries.append(
            SymbolSnapshotSummary(
                symbol=symbol,
                deployment_status=status,
                strategy_names=strategy_names,
                top_ranked_candidates=top_ranked_candidates,
                tier_counts=_extract_tier_counts(symbol),
                failures=symbol_failures,
            )
        )
    return failures, summaries


def _print_symbol_summaries(summaries: list[SymbolSnapshotSummary]) -> None:
    print("\nSymbol snapshot summary:")
    for summary in summaries:
        strategy_summary = ", ".join(summary.strategy_names) if summary.strategy_names else "none"
        candidate_summary = ", ".join(summary.top_ranked_candidates[:3]) if summary.top_ranked_candidates else "none"
        verdict = "ok" if not summary.failures else f"drift={len(summary.failures)}"
        print(
            f"- {summary.symbol}: status={summary.deployment_status} "
            f"strategies={strategy_summary} top_candidates={candidate_summary} "
            f"{summary.tier_counts} verdict={verdict}"
        )


def _write_report(
    *,
    baseline_dir: Path,
    symbols: list[str],
    dedicated_ok: bool,
    functional_ok: bool,
    skipped_functional_suite: bool,
    snapshot_failures: list[RegressionFailure],
    summaries: list[SymbolSnapshotSummary],
) -> Path:
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "baseline_dir": str(baseline_dir),
        "symbols": symbols,
        "dedicated_suite_ok": dedicated_ok,
        "functional_suite_ok": functional_ok,
        "skipped_functional_suite": skipped_functional_suite,
        "snapshot_ok": not snapshot_failures,
        "overall_ok": dedicated_ok and functional_ok and not snapshot_failures,
        "symbol_summaries": [
            {
                **asdict(summary),
                "failures": [asdict(failure) for failure in summary.failures],
            }
            for summary in summaries
        ],
        "snapshot_failures": [asdict(failure) for failure in snapshot_failures],
    }
    path = _report_path()
    ensure_dir(path.parent)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run refactor regression tests and compare snapshot outputs.")
    parser.add_argument("--baseline-dir", default=str(_baseline_dir()))
    parser.add_argument("--skip-functional-suite", action="store_true")
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    args = parser.parse_args()

    baseline_dir = Path(args.baseline_dir)
    if not baseline_dir.exists():
        print(f"Baseline directory does not exist: {baseline_dir}")
        return 1

    repo_root = _repo_root()
    dedicated_ok = _run_unittest_modules(DEDICATED_TEST_MODULES)
    functional_ok = True
    if not args.skip_functional_suite:
        functional_ok = _run_functional_suite(repo_root)

    symbols = list(args.symbols)
    snapshot_failures, summaries = _compare_snapshot_outputs(symbols, baseline_dir)
    _print_symbol_summaries(summaries)
    report_path = _write_report(
        baseline_dir=baseline_dir,
        symbols=symbols,
        dedicated_ok=dedicated_ok,
        functional_ok=functional_ok,
        skipped_functional_suite=args.skip_functional_suite,
        snapshot_failures=snapshot_failures,
        summaries=summaries,
    )
    print(f"\nRegression report: {report_path}")
    if snapshot_failures:
        print("\nSnapshot comparison failures:")
        for failure in snapshot_failures:
            print(f"- {failure.label}: {failure.detail}")

    success = dedicated_ok and functional_ok and not snapshot_failures
    if success:
        print("\nRefactor regressions passed.")
        return 0

    print("\nRefactor regressions failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
