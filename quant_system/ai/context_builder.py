from __future__ import annotations

from quant_system.ai.models import ExperimentSnapshot


def build_experiment_context(profile_name: str, recent_runs: list[ExperimentSnapshot], best_run: ExperimentSnapshot | None) -> str:
    lines = [f"Profile: {profile_name}"]
    if best_run is not None:
        lines.append(
            "Best run: "
            f"pnl={best_run.realized_pnl:.2f}, closed_trades={best_run.closed_trades}, "
            f"profit_factor={best_run.profit_factor:.2f}, win_rate={best_run.win_rate_pct:.2f}%, "
            f"max_drawdown={best_run.max_drawdown_pct:.2f}%"
        )
    if recent_runs:
        lines.append("Recent runs:")
        for run in recent_runs:
            lines.append(
                f"- id={run.experiment_id} pnl={run.realized_pnl:.2f} closed={run.closed_trades} "
                f"pf={run.profit_factor:.2f} win_rate={run.win_rate_pct:.2f}% dd={run.max_drawdown_pct:.2f}%"
            )
    else:
        lines.append("Recent runs: none")
    return "\n".join(lines)
