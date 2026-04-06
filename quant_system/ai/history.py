from __future__ import annotations

from quant_system.ai.models import ComparisonPackage, ExperimentSnapshot


def _format_experiment_line(snapshot: ExperimentSnapshot) -> str:
    return (
        f"#{snapshot.experiment_id} {snapshot.created_at}: "
        f"pnl={snapshot.realized_pnl:.2f} "
        f"closed={snapshot.closed_trades} "
        f"pf={snapshot.profit_factor:.2f} "
        f"win_rate={snapshot.win_rate_pct:.2f}% "
        f"dd={snapshot.max_drawdown_pct:.2f}% "
        f"ftmo_pass={snapshot.ftmo_passed}"
    )


def _format_delta(name: str, current: float, previous: float, precision: int = 2, suffix: str = "") -> str:
    delta = current - previous
    sign = "+" if delta >= 0 else ""
    return f"{name}: {current:.{precision}f}{suffix} ({sign}{delta:.{precision}f}{suffix} vs previous)"


def build_experiment_memory_report(
    *,
    profile_name: str,
    recent_runs: list[ExperimentSnapshot],
    best_run: ExperimentSnapshot | None,
    current_run: ExperimentSnapshot | None,
    previous_run: ExperimentSnapshot | None,
) -> ComparisonPackage:
    history_lines = [f"Profile: {profile_name}", "Recent experiments", ""]
    if not recent_runs:
        history_lines.append("No prior experiments recorded.")
    else:
        history_lines.extend(_format_experiment_line(run) for run in recent_runs)
        if best_run is not None:
            history_lines.extend(
                [
                    "",
                    "Best recorded run",
                    _format_experiment_line(best_run),
                ]
            )

    comparison_lines = [f"Profile: {profile_name}", "Run comparison", ""]
    if current_run is None:
        comparison_lines.append("No current run found in experiment memory.")
    elif previous_run is None:
        comparison_lines.append("No previous run available yet; compare after the next run.")
        comparison_lines.append(_format_experiment_line(current_run))
    else:
        comparison_lines.append(_format_delta("Realized PnL", current_run.realized_pnl, previous_run.realized_pnl))
        comparison_lines.append(_format_delta("Closed trades", float(current_run.closed_trades), float(previous_run.closed_trades), precision=0))
        comparison_lines.append(_format_delta("Profit factor", current_run.profit_factor, previous_run.profit_factor))
        comparison_lines.append(_format_delta("Win rate", current_run.win_rate_pct, previous_run.win_rate_pct, suffix="%"))
        comparison_lines.append(_format_delta("Max drawdown", current_run.max_drawdown_pct, previous_run.max_drawdown_pct, suffix="%"))
        comparison_lines.extend(
            [
                "",
                "Current run",
                _format_experiment_line(current_run),
                "",
                "Previous run",
                _format_experiment_line(previous_run),
            ]
        )

    return ComparisonPackage(
        history_summary="\n".join(history_lines),
        comparison_summary="\n".join(comparison_lines),
    )
