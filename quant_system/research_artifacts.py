from __future__ import annotations

import csv
from pathlib import Path

from quant_system.artifacts import ARTIFACTS_DIR, research_candidates_dir


def _safe_artifact_stem(value: str, max_length: int = 120) -> str:
    stem = "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")
    if len(stem) <= max_length:
        return stem
    return stem[:max_length].rstrip("_")


def export_closed_trade_artifacts(closed_trades, realized_pnl: float, artifact_prefix: str) -> tuple[Path, Path]:
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    symbol = artifact_prefix.split("_", 1)[0]
    safe_prefix = _safe_artifact_stem(artifact_prefix)
    file_stem = safe_prefix[len(symbol) + 1 :] if safe_prefix.startswith(f"{symbol}_") else safe_prefix
    file_stem = _safe_artifact_stem(file_stem, max_length=110)
    candidate_dir = research_candidates_dir(symbol)
    trades_path = candidate_dir / f"{file_stem}_trades.csv"
    analysis_path = candidate_dir / f"{file_stem}_analysis.txt"

    with trades_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "symbol",
                "entry_timestamp",
                "exit_timestamp",
                "entry_hour",
                "exit_hour",
                "entry_reason",
                "exit_reason",
                "entry_price",
                "exit_price",
                "quantity",
                "gross_pnl",
                "pnl",
                "costs",
                "fee_cost",
                "commission_cost",
                "swap_value",
                "hold_bars",
                "entry_confidence",
                "entry_metadata",
            ]
        )
        for trade in closed_trades:
            writer.writerow(
                [
                    trade.symbol,
                    trade.entry_timestamp.isoformat(),
                    trade.exit_timestamp.isoformat(),
                    trade.entry_hour,
                    trade.exit_hour,
                    trade.entry_reason,
                    trade.exit_reason,
                    f"{trade.entry_price:.5f}",
                    f"{trade.exit_price:.5f}",
                    f"{trade.quantity:.5f}",
                    f"{float(getattr(trade, 'gross_pnl', 0.0) or 0.0):.5f}",
                    f"{trade.pnl:.5f}",
                    f"{trade.costs:.5f}",
                    f"{float(getattr(trade, 'fee_cost', 0.0) or 0.0):.5f}",
                    f"{float(getattr(trade, 'commission_cost', 0.0) or 0.0):.5f}",
                    f"{float(getattr(trade, 'swap_value', 0.0) or 0.0):.5f}",
                    trade.hold_bars,
                    f"{trade.entry_confidence:.5f}",
                    trade.entry_metadata,
                ]
            )

    by_hour: dict[int, list[float]] = {}
    by_setup: dict[str, list[float]] = {}
    by_exit: dict[str, list[float]] = {}
    for trade in closed_trades:
        by_hour.setdefault(trade.entry_hour, []).append(trade.pnl)
        by_setup.setdefault(trade.entry_reason, []).append(trade.pnl)
        by_exit.setdefault(trade.exit_reason, []).append(trade.pnl)

    def render_bucket(title: str, buckets: dict[object, list[float]]) -> list[str]:
        lines = [title]
        for key, pnls in sorted(buckets.items(), key=lambda item: (sum(item[1]), len(item[1]))):
            wins = sum(1 for pnl in pnls if pnl > 0)
            lines.append(
                f"{key}: trades={len(pnls)} pnl={sum(pnls):.2f} avg={sum(pnls)/len(pnls):.2f} win_rate={wins/len(pnls)*100.0:.2f}%"
            )
        return lines

    analysis_lines = [
        f"Artifact: {file_stem}",
        f"Closed trades: {len(closed_trades)}",
        f"Realized pnl: {realized_pnl:.2f}",
        f"Applied swap total: {sum(float(getattr(trade, 'swap_value', 0.0) or 0.0) for trade in closed_trades):.2f}",
        "",
    ]
    analysis_lines.extend(render_bucket("By entry hour", by_hour))
    analysis_lines.append("")
    analysis_lines.extend(render_bucket("By entry setup", by_setup))
    analysis_lines.append("")
    analysis_lines.extend(render_bucket("By exit reason", by_exit))
    analysis_path.write_text("\n".join(analysis_lines), encoding="utf-8")
    return trades_path, analysis_path
