from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from quant_system.ai.models import AnalysisPackage, ProfileArtifacts
from quant_system.ai.prompts import build_analysis_prompt
from quant_system.ai.service import AIService
from quant_system.config import AIConfig


def _load_rows(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _best_shadow_setup(rows: list[dict[str, str]]) -> tuple[str, float] | None:
    if not rows:
        return None
    ranked = sorted(
        rows,
        key=lambda row: (float(row.get("realized_pnl", "0") or 0.0), float(row.get("profit_factor", "0") or 0.0)),
        reverse=True,
    )
    winner = ranked[0]
    return winner.get("setup_name", "unknown"), float(winner.get("realized_pnl", "0") or 0.0)


def _weakest_bucket(rows: list[dict[str, str]], key: str, value_key: str) -> tuple[str, float] | None:
    if not rows:
        return None
    buckets: dict[str, float] = defaultdict(float)
    for row in rows:
        buckets[row.get(key, "unknown")] += float(row.get(value_key, "0") or 0.0)
    weakest_key, weakest_value = min(buckets.items(), key=lambda item: item[1])
    return weakest_key, weakest_value


def _best_bucket(rows: list[dict[str, str]], key: str, value_key: str) -> tuple[str, float] | None:
    if not rows:
        return None
    buckets: dict[str, float] = defaultdict(float)
    for row in rows:
        buckets[row.get(key, "unknown")] += float(row.get(value_key, "0") or 0.0)
    best_key, best_value = max(buckets.items(), key=lambda item: item[1])
    return best_key, best_value


def _next_experiments(profile_name: str, trade_rows: list[dict[str, str]], signal_rows: list[dict[str, str]], shadow_rows: list[dict[str, str]]) -> list[str]:
    suggestions: list[str] = []

    weak_exit = _weakest_bucket(trade_rows, "exit_reason", "pnl")
    if weak_exit is not None and weak_exit[1] < 0:
        suggestions.append(f"Reduce the '{weak_exit[0]}' loss bucket in {profile_name}; it is the weakest realized exit.")

    weak_hour = _weakest_bucket(trade_rows, "entry_hour", "pnl")
    if weak_hour is not None and weak_hour[1] < 0:
        suggestions.append(f"Review or isolate hour {weak_hour[0]} for {profile_name}; realized PnL there is negative.")

    best_shadow = _best_shadow_setup(shadow_rows)
    if best_shadow is not None and best_shadow[0] not in {"", "unknown"}:
        suggestions.append(f"Prioritize the shadow candidate '{best_shadow[0]}' for {profile_name}; it is currently the best unused setup.")

    if not suggestions and signal_rows:
        best_signal_hour = _best_bucket(signal_rows, "hour", "forward_return_6_pct")
        if best_signal_hour is not None:
            suggestions.append(f"Expand testing around signal hour {best_signal_hour[0]} for {profile_name}; forward returns are strongest there.")

    if len(trade_rows) < 10:
        suggestions.append(f"Increase evaluation sample size for {profile_name}; current closed-trade count is still small.")

    return suggestions[:3]


def build_profile_analysis(
    *,
    profile,
    result,
    report,
    artifacts: ProfileArtifacts,
    ai_config: AIConfig,
) -> AnalysisPackage:
    trade_rows = _load_rows(artifacts.trade_log)
    signal_rows = _load_rows(artifacts.signal_log)
    shadow_rows = _load_rows(artifacts.shadow_log)

    strongest_setup = _best_bucket(trade_rows, "entry_reason", "pnl")
    weakest_exit = _weakest_bucket(trade_rows, "exit_reason", "pnl")
    best_signal_hour = _best_bucket(signal_rows, "hour", "forward_return_6_pct")
    best_shadow = _best_shadow_setup(shadow_rows)
    next_experiments = _next_experiments(profile.name, trade_rows, signal_rows, shadow_rows)

    local_summary_lines = [
        f"Profile: {profile.name}",
        f"Description: {profile.description}",
        f"Data symbol: {profile.data_symbol}",
        f"Broker symbol: {profile.broker_symbol}",
        f"Ending equity: {result.ending_equity:.2f}",
        f"Realized PnL: {result.realized_pnl:.2f}",
        f"Closed trades: {report.closed_trades}",
        f"Win rate: {report.win_rate_pct:.2f}%",
        f"Profit factor: {report.profit_factor:.2f}",
        f"Max drawdown: {report.max_drawdown_pct:.2f}%",
        f"FTMO pass: {report.passed}",
        f"FTMO reasons: {', '.join(report.reasons) if report.reasons else 'none'}",
    ]
    if strongest_setup is not None:
        local_summary_lines.append(f"Strongest realized setup: {strongest_setup[0]} ({strongest_setup[1]:.2f} pnl)")
    if weakest_exit is not None:
        local_summary_lines.append(f"Weakest realized exit: {weakest_exit[0]} ({weakest_exit[1]:.2f} pnl)")
    if best_signal_hour is not None:
        local_summary_lines.append(f"Best signal hour: {best_signal_hour[0]} ({best_signal_hour[1]:.3f}% 6-bar forward return)")
    if best_shadow is not None:
        local_summary_lines.append(f"Best shadow setup: {best_shadow[0]} ({best_shadow[1]:.2f} pnl)")

    local_summary = "\n".join(local_summary_lines)
    ai_summary: str | None = None

    ai_service = AIService(ai_config)
    if ai_service.available:
        prompt = build_analysis_prompt(profile.name, local_summary[: ai_config.max_context_chars], next_experiments)
        ai_summary = ai_service.summarize(prompt)

    return AnalysisPackage(
        local_summary=local_summary,
        next_experiments=next_experiments,
        ai_summary=ai_summary,
    )
