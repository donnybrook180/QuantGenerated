from __future__ import annotations

import csv
from pathlib import Path


def _top_reason_counts(candidate_rows: list[dict[str, object]], key: str, *, limit: int = 5) -> str:
    counts: dict[str, int] = {}
    for row in candidate_rows:
        for reason in row.get(key, ()) or ():
            normalized = str(reason).strip()
            if not normalized:
                continue
            counts[normalized] = counts.get(normalized, 0) + 1
    if not counts:
        return "none"
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return "; ".join(f"{reason}({count})" for reason, count in ranked[:limit])


def _estimated_gross_pnl_before_swap(row: object) -> float:
    realized_pnl = float(getattr(row, "realized_pnl", 0.0) or 0.0)
    estimated_swap_drag_total = float(getattr(row, "estimated_swap_drag_total", 0.0) or 0.0)
    return realized_pnl + estimated_swap_drag_total


def _summarize_blue_guardian_sections(
    rows: list[object],
    candidate_rows: list[dict[str, object]],
) -> list[str]:
    if not rows:
        return [
            "",
            "swap_drag_summary",
            "  no_candidates",
            "",
            "execution_stress_summary",
            "  no_candidates",
            "",
            "prop_fit_summary",
            "  no_candidates",
            "",
            "interpreter_fit_summary",
            "  no_candidates",
            "",
            "why_promoted_for_blue_guardian",
            "  none",
            "",
            "why_rejected_for_blue_guardian",
            "  none",
        ]

    swap_available_count = sum(1 for row in rows if bool(getattr(row, "broker_swap_available", False)))
    swap_negative_count = sum(1 for row in rows if float(getattr(row, "swap_adjusted_expectancy", 0.0) or 0.0) <= 0.0)
    estimated_swap_drag_total = sum(float(getattr(row, "estimated_swap_drag_total", 0.0) or 0.0) for row in rows)
    stress_break_count = sum(
        1
        for row in rows
        if (
            float(getattr(row, "stress_expectancy_mild", 0.0) or 0.0) <= 0.0
            or float(getattr(row, "stress_expectancy_medium", 0.0) or 0.0) <= 0.0
            or float(getattr(row, "stress_pf_mild", 0.0) or 0.0) < 1.0
            or float(getattr(row, "stress_pf_medium", 0.0) or 0.0) < 1.0
        )
    )
    caution_or_fail_prop_fit = sum(1 for row in rows if str(getattr(row, "prop_fit_label", "fail") or "fail") != "pass")
    elevated_interpreter_risk = sum(1 for row in rows if float(getattr(row, "blocked_by_interpreter_risk", 0.0) or 0.0) >= 0.45)

    promoted_lines = ["  none"]
    rejected_lines = ["  none"]
    promoted = [
        row
        for row in candidate_rows
        if bool(row.get("prop_viability_pass", False))
    ]
    rejected = [
        row
        for row in candidate_rows
        if not bool(row.get("prop_viability_pass", False))
    ]
    if promoted:
        promoted_lines = [
            "  "
            + f"{row.get('candidate_name', 'unknown')}: "
            + (
                "; ".join(str(reason) for reason in (row.get("prop_viability_reasons", ()) or ()))
                if (row.get("prop_viability_reasons", ()) or ())
                else f"label={row.get('prop_viability_label', 'pass')} signal_quality={float(row.get('signal_quality_score', 0.0) or 0.0):.2f}"
            )
            for row in promoted[:5]
        ]
    if rejected:
        rejected_lines = [
            "  "
            + f"{row.get('candidate_name', 'unknown')}: "
            + (
                "; ".join(str(reason) for reason in (row.get("prop_viability_reasons", ()) or ()))
                if (row.get("prop_viability_reasons", ()) or ())
                else f"label={row.get('prop_viability_label', 'fail')}"
            )
            for row in rejected[:5]
        ]

    return [
        "",
        "swap_drag_summary",
        f"  broker_swap_available_candidates: {swap_available_count}/{len(rows)}",
        f"  swap_adjusted_expectancy_non_positive_candidates: {swap_negative_count}",
        f"  estimated_total_swap_drag: {estimated_swap_drag_total:.4f}",
        f"  top_swap_drag_reasons: {_top_reason_counts(candidate_rows, 'prop_viability_reasons')}",
        "",
        "execution_stress_summary",
        f"  mild_or_medium_stress_break_candidates: {stress_break_count}",
        f"  top_execution_stress_reasons: {_top_reason_counts(candidate_rows, 'prop_viability_reasons')}",
        "",
        "prop_fit_summary",
        f"  caution_or_fail_candidates: {caution_or_fail_prop_fit}",
        f"  top_prop_fit_reasons: {_top_reason_counts(candidate_rows, 'prop_fit_reasons')}",
        "",
        "interpreter_fit_summary",
        f"  elevated_interpreter_risk_candidates: {elevated_interpreter_risk}",
        f"  top_interpreter_fit_reasons: {_top_reason_counts(candidate_rows, 'interpreter_fit_reasons')}",
        "",
        "why_promoted_for_blue_guardian",
        *promoted_lines,
        "",
        "why_rejected_for_blue_guardian",
        *rejected_lines,
    ]


def export_results(
    symbol: str,
    broker_symbol: str,
    data_source: str,
    rows: list[object],
    *,
    reports_dir_fn,
    strategy_family_fn,
    direction_mode_fn,
    direction_role_fn,
    execution_candidate_row_from_result_fn,
    build_execution_policy_from_candidate_row_fn,
    summarize_unified_regime_fn,
    meets_viability_fn,
    promotion_tier_for_row_fn,
    broker_data_summary: dict[str, object] | None = None,
) -> tuple[Path, Path]:
    reports_dir = reports_dir_fn(symbol)
    csv_path = reports_dir / "symbol_research.csv"
    txt_path = reports_dir / "symbol_research.txt"

    candidate_rows = [execution_candidate_row_from_result_fn(symbol, row) for row in rows]

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "name", "description", "archetype", "variant_label", "timeframe_label", "session_label",
            "strategy_family", "direction_mode", "direction_role", "realized_pnl", "estimated_gross_pnl_before_swap",
            "estimated_net_pnl_delta_from_swap", "closed_trades", "win_rate_pct",
            "profit_factor", "max_drawdown_pct", "total_costs", "expectancy", "sharpe_ratio", "sortino_ratio",
            "calmar_ratio", "avg_win", "avg_loss", "payoff_ratio", "avg_hold_bars", "dominant_exit",
            "dominant_exit_share_pct", "component_count", "combo_outperformance_score", "combo_trade_overlap_pct",
            "best_regime", "best_unified_regime", "best_regime_pnl", "worst_regime", "worst_unified_regime",
            "worst_regime_pnl", "dominant_regime_share_pct", "regime_stability_score", "regime_loss_ratio",
            "regime_trade_count_by_label", "regime_pnl_by_label", "regime_pf_by_label", "regime_win_rate_by_label",
            "regime_filter_label", "broker_swap_available", "broker_swap_long", "broker_swap_short",
            "broker_preferred_carry_side", "broker_carry_spread", "avg_hold_hours", "estimated_swap_drag_total",
            "estimated_swap_drag_per_trade", "swap_adjusted_expectancy", "carry_preferred_side",
            "stress_expectancy_mild", "stress_expectancy_medium", "stress_expectancy_harsh",
            "stress_pf_mild", "stress_pf_medium", "stress_pf_harsh", "stress_survival_score",
            "prop_fit_score", "prop_fit_label", "prop_fit_reasons", "news_window_trade_share", "sub_short_hold_share",
            "micro_target_risk_flag", "execution_dependency_flag",
            "interpreter_fit_score", "common_live_regime_fit", "blocked_by_interpreter_risk", "interpreter_fit_reasons",
            "mc_simulations", "mc_pnl_median", "mc_pnl_p05",
            "mc_pnl_p95", "mc_max_drawdown_pct_median", "mc_max_drawdown_pct_p95", "mc_loss_probability_pct",
            "walk_forward_windows", "walk_forward_pass_rate_pct", "walk_forward_avg_validation_pnl",
            "walk_forward_avg_test_pnl", "walk_forward_avg_validation_pf", "walk_forward_avg_test_pf", "train_pnl",
            "validation_pnl", "validation_profit_factor", "validation_closed_trades", "test_pnl",
            "test_profit_factor", "test_closed_trades", "signal_quality_score", "prop_viability_score",
            "prop_viability_label", "prop_viability_pass", "prop_viability_reasons", "trade_log_path", "trade_analysis_path",
        ])
        for row, candidate_row in zip(rows, candidate_rows):
            estimated_swap_drag_total = float(row.estimated_swap_drag_total or 0.0)
            estimated_gross_pnl_before_swap = row.realized_pnl + estimated_swap_drag_total
            writer.writerow([
                row.name, row.description, row.archetype, row.variant_label, row.timeframe_label, row.session_label,
                strategy_family_fn(row), direction_mode_fn(row), direction_role_fn(row),
                f"{row.realized_pnl:.5f}", f"{estimated_gross_pnl_before_swap:.5f}", f"{estimated_swap_drag_total:.5f}",
                row.closed_trades, f"{row.win_rate_pct:.5f}", f"{row.profit_factor:.5f}",
                f"{row.max_drawdown_pct:.5f}", f"{row.total_costs:.5f}", f"{row.expectancy:.5f}",
                f"{row.sharpe_ratio:.5f}", f"{row.sortino_ratio:.5f}", f"{row.calmar_ratio:.5f}",
                f"{row.avg_win:.5f}", f"{row.avg_loss:.5f}", f"{row.payoff_ratio:.5f}", f"{row.avg_hold_bars:.5f}",
                row.dominant_exit, f"{row.dominant_exit_share_pct:.5f}", row.component_count,
                f"{row.combo_outperformance_score:.5f}", f"{row.combo_trade_overlap_pct:.5f}", row.best_regime,
                row.best_unified_regime, f"{row.best_regime_pnl:.5f}", row.worst_regime, row.worst_unified_regime,
                f"{row.worst_regime_pnl:.5f}", f"{row.dominant_regime_share_pct:.5f}",
                f"{row.regime_stability_score:.5f}", f"{row.regime_loss_ratio:.5f}", row.regime_trade_count_by_label,
                row.regime_pnl_by_label, row.regime_pf_by_label, row.regime_win_rate_by_label, row.regime_filter_label,
                int(row.broker_swap_available), f"{row.broker_swap_long:.5f}", f"{row.broker_swap_short:.5f}",
                row.broker_preferred_carry_side, f"{row.broker_carry_spread:.5f}", f"{row.avg_hold_hours:.5f}",
                f"{row.estimated_swap_drag_total:.5f}", f"{row.estimated_swap_drag_per_trade:.5f}",
                f"{row.swap_adjusted_expectancy:.5f}", row.carry_preferred_side,
                f"{row.stress_expectancy_mild:.5f}", f"{row.stress_expectancy_medium:.5f}", f"{row.stress_expectancy_harsh:.5f}",
                f"{row.stress_pf_mild:.5f}", f"{row.stress_pf_medium:.5f}", f"{row.stress_pf_harsh:.5f}",
                f"{row.stress_survival_score:.5f}", f"{row.prop_fit_score:.5f}", row.prop_fit_label,
                "; ".join(str(item) for item in row.prop_fit_reasons), f"{row.news_window_trade_share:.5f}",
                f"{row.sub_short_hold_share:.5f}", int(row.micro_target_risk_flag), int(row.execution_dependency_flag),
                f"{row.interpreter_fit_score:.5f}", f"{row.common_live_regime_fit:.5f}",
                f"{row.blocked_by_interpreter_risk:.5f}", "; ".join(str(item) for item in row.interpreter_fit_reasons),
                row.mc_simulations,
                f"{row.mc_pnl_median:.5f}", f"{row.mc_pnl_p05:.5f}", f"{row.mc_pnl_p95:.5f}",
                f"{row.mc_max_drawdown_pct_median:.5f}", f"{row.mc_max_drawdown_pct_p95:.5f}",
                f"{row.mc_loss_probability_pct:.5f}", row.walk_forward_windows, f"{row.walk_forward_pass_rate_pct:.5f}",
                f"{row.walk_forward_avg_validation_pnl:.5f}", f"{row.walk_forward_avg_test_pnl:.5f}",
                f"{row.walk_forward_avg_validation_pf:.5f}", f"{row.walk_forward_avg_test_pf:.5f}",
                f"{row.train_pnl:.5f}", f"{row.validation_pnl:.5f}", f"{row.validation_profit_factor:.5f}",
                row.validation_closed_trades, f"{row.test_pnl:.5f}", f"{row.test_profit_factor:.5f}",
                row.test_closed_trades,
                f"{float(candidate_row.get('signal_quality_score', 0.0) or 0.0):.5f}",
                f"{float(candidate_row.get('prop_viability_score', 0.0) or 0.0):.5f}",
                str(candidate_row.get("prop_viability_label", "") or ""),
                int(bool(candidate_row.get("prop_viability_pass", False))),
                "; ".join(str(item) for item in candidate_row.get("prop_viability_reasons", ()) or ()),
                row.trade_log_path,
                row.trade_analysis_path,
            ])

    ranked = sorted(zip(rows, candidate_rows), key=lambda pair: (pair[0].realized_pnl, pair[0].profit_factor, pair[0].closed_trades), reverse=True)
    lines = [f"Symbol research: {symbol}", f"Broker symbol: {broker_symbol}", f"Data source: {data_source}"]
    if broker_data_summary:
        missing_bar_warnings = [str(item) for item in broker_data_summary.get("missing_bar_warnings", ()) or ()]
        lines.extend(
            [
                "",
                "broker_data_summary",
                f"  broker_data_source: {broker_data_summary.get('broker_data_source', data_source)}",
                f"  broker_symbol: {broker_data_summary.get('broker_symbol', broker_symbol)}",
                f"  history_bars_loaded: {int(broker_data_summary.get('history_bars_loaded', 0) or 0)}",
                f"  history_window_start: {broker_data_summary.get('history_window_start', '') or 'unknown'}",
                f"  history_window_end: {broker_data_summary.get('history_window_end', '') or 'unknown'}",
                f"  missing_bar_warnings: {'; '.join(missing_bar_warnings) if missing_bar_warnings else 'none'}",
                f"  session_alignment_notes: {broker_data_summary.get('session_alignment_notes', '') or 'none'}",
                f"  contract_spec_notes: {broker_data_summary.get('contract_spec_notes', '') or 'none'}",
            ]
        )
    lines.extend(_summarize_blue_guardian_sections(rows, candidate_rows))
    lines.extend(["", "Ranked candidates"])
    for row, candidate_row in ranked:
        policy = build_execution_policy_from_candidate_row_fn(candidate_row)
        lines.append(
            f"{row.name} [{row.archetype}|{policy['promotion_tier']}]: pnl={row.realized_pnl:.2f} closed={row.closed_trades} "
            f"pf={row.profit_factor:.2f} win_rate={row.win_rate_pct:.2f}% dd={row.max_drawdown_pct:.2f}%"
        )
        lines.append(f"  tier: {policy['promotion_tier']}")
        lines.append(
            f"  trade_metrics: expectancy={row.expectancy:.2f} sharpe={row.sharpe_ratio:.2f} "
            f"sortino={row.sortino_ratio:.2f} calmar={row.calmar_ratio:.2f} avg_win={row.avg_win:.2f} "
            f"avg_loss={row.avg_loss:.2f} payoff={row.payoff_ratio:.2f} avg_hold={row.avg_hold_bars:.1f}"
        )
        lines.append(f"  exits: dominant={row.dominant_exit or 'none'} share={row.dominant_exit_share_pct:.2f}%")
        lines.append(
            f"  regimes: best={summarize_unified_regime_fn(row.best_regime) if row.best_regime else 'none'} pnl={row.best_regime_pnl:.2f} "
            f"worst={summarize_unified_regime_fn(row.worst_regime) if row.worst_regime else 'none'} pnl={row.worst_regime_pnl:.2f} "
            f"dominant_share={row.dominant_regime_share_pct:.2f}% stability={row.regime_stability_score:.2f} loss_ratio={row.regime_loss_ratio:.2f}"
        )
        lines.append(
            f"  strategy_scope: family={row.strategy_family or 'none'} direction={row.direction_mode or 'none'} role={row.direction_role or 'none'}"
        )
        lines.append(
            f"  blue_guardian: signal_quality={float(candidate_row.get('signal_quality_score', 0.0) or 0.0):.2f} "
            f"prop_viability={float(candidate_row.get('prop_viability_score', 0.0) or 0.0):.2f} "
            f"label={candidate_row.get('prop_viability_label', 'fail')} "
            f"pass={'yes' if candidate_row.get('prop_viability_pass', False) else 'no'}"
        )
        prop_viability_reasons = [str(item) for item in candidate_row.get("prop_viability_reasons", ()) or ()]
        if prop_viability_reasons:
            lines.append("  blue_guardian_reasons: " + "; ".join(prop_viability_reasons))
        lines.append(f"  unified_regimes: best={row.best_unified_regime or 'none'} worst={row.worst_unified_regime or 'none'}")
        lines.append(f"  regime_trade_counts: {row.regime_trade_count_by_label}")
        lines.append(f"  regime_pnls: {row.regime_pnl_by_label}")
        lines.append(
            f"  funding: available={'yes' if row.broker_swap_available else 'no'} "
            f"swap_long={row.broker_swap_long:.5f} swap_short={row.broker_swap_short:.5f} "
            f"preferred_side={row.broker_preferred_carry_side or 'none'} carry_spread={row.broker_carry_spread:.5f}"
        )
        lines.append(
            f"  pnl_netting: net_realized_pnl={row.realized_pnl:.4f} "
            f"estimated_gross_before_swap={_estimated_gross_pnl_before_swap(row):.4f} "
            f"estimated_swap_delta={row.estimated_swap_drag_total:.4f}"
        )
        lines.append(
            f"  swap_drag: avg_hold_hours={row.avg_hold_hours:.2f} drag_per_trade={row.estimated_swap_drag_per_trade:.4f} "
            f"drag_total={row.estimated_swap_drag_total:.4f} swap_adjusted_expectancy={row.swap_adjusted_expectancy:.4f} "
            f"carry_side={row.carry_preferred_side or 'none'}"
        )
        lines.append(
            f"  execution_stress: mild_expectancy={row.stress_expectancy_mild:.4f} medium_expectancy={row.stress_expectancy_medium:.4f} "
            f"harsh_expectancy={row.stress_expectancy_harsh:.4f} mild_pf={row.stress_pf_mild:.3f} "
            f"medium_pf={row.stress_pf_medium:.3f} harsh_pf={row.stress_pf_harsh:.3f} "
            f"survival_score={row.stress_survival_score:.2f}"
        )
        lines.append(
            f"  prop_fit: score={row.prop_fit_score:.2f} label={row.prop_fit_label or 'fail'} "
            f"news_window_trade_share={row.news_window_trade_share:.2%} sub_short_hold_share={row.sub_short_hold_share:.2%} "
            f"micro_target_risk={'yes' if row.micro_target_risk_flag else 'no'} "
            f"execution_dependency={'yes' if row.execution_dependency_flag else 'no'}"
        )
        if row.prop_fit_reasons:
            lines.append("  prop_fit_reasons: " + "; ".join(row.prop_fit_reasons))
        lines.append(
            f"  interpreter_fit: score={row.interpreter_fit_score:.2f} common_live_regime_fit={row.common_live_regime_fit:.2%} "
            f"blocked_risk={row.blocked_by_interpreter_risk:.2%}"
        )
        if row.interpreter_fit_reasons:
            lines.append("  interpreter_fit_reasons: " + "; ".join(row.interpreter_fit_reasons))
        lines.append(
            f"  monte_carlo: sims={row.mc_simulations} pnl_median={row.mc_pnl_median:.2f} p05={row.mc_pnl_p05:.2f} p95={row.mc_pnl_p95:.2f} "
            f"dd_median={row.mc_max_drawdown_pct_median:.2f}% dd_p95={row.mc_max_drawdown_pct_p95:.2f}% loss_prob={row.mc_loss_probability_pct:.2f}%"
        )
        lines.append(f"  live_policy: {policy['policy_summary']}")
        if row.regime_filter_label:
            lines.append(f"  regime_filter: {row.regime_filter_label}")
        lines.append(
            f"  walk_forward: windows={row.walk_forward_windows} pass_rate={row.walk_forward_pass_rate_pct:.2f}% "
            f"avg_val_pnl={row.walk_forward_avg_validation_pnl:.2f} avg_test_pnl={row.walk_forward_avg_test_pnl:.2f} "
            f"avg_val_pf={row.walk_forward_avg_validation_pf:.2f} avg_test_pf={row.walk_forward_avg_test_pf:.2f}"
        )
        if row.sparse_strategy:
            lines.append(f"  sparse_strategy: soft_pass_rate={row.walk_forward_soft_pass_rate_pct:.2f}%")
        if row.component_count > 1:
            lines.append(
                f"  combo_validation: components={row.component_count} outperformance={row.combo_outperformance_score:.2f} "
                f"trade_overlap={row.combo_trade_overlap_pct:.2f}%"
            )
        lines.append(
            f"  splits: train_pnl={row.train_pnl:.2f} val_pnl={row.validation_pnl:.2f} val_pf={row.validation_profit_factor:.2f} "
            f"val_closed={row.validation_closed_trades} test_pnl={row.test_pnl:.2f} test_pf={row.test_profit_factor:.2f} test_closed={row.test_closed_trades}"
        )
        lines.append(f"  trades: {row.trade_log_path}")
        lines.append(f"  analysis: {row.trade_analysis_path}")
    winners = [row for row, _candidate_row in ranked if meets_viability_fn(row, symbol)]
    lines.extend(["", "Top candidate-level winners"])
    if winners:
        for row in winners[:3]:
            tier = promotion_tier_for_row_fn(row, symbol)
            lines.append(f"- {row.name} [{tier}] ({row.description})")
    else:
        lines.append("No candidate met the positive-PnL and PF>=1.0 threshold.")
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, txt_path
