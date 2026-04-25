from __future__ import annotations

import csv
from pathlib import Path


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
) -> tuple[Path, Path]:
    reports_dir = reports_dir_fn(symbol)
    csv_path = reports_dir / "symbol_research.csv"
    txt_path = reports_dir / "symbol_research.txt"

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "name", "description", "archetype", "variant_label", "timeframe_label", "session_label",
            "strategy_family", "direction_mode", "direction_role", "realized_pnl", "closed_trades", "win_rate_pct",
            "profit_factor", "max_drawdown_pct", "total_costs", "expectancy", "sharpe_ratio", "sortino_ratio",
            "calmar_ratio", "avg_win", "avg_loss", "payoff_ratio", "avg_hold_bars", "dominant_exit",
            "dominant_exit_share_pct", "component_count", "combo_outperformance_score", "combo_trade_overlap_pct",
            "best_regime", "best_unified_regime", "best_regime_pnl", "worst_regime", "worst_unified_regime",
            "worst_regime_pnl", "dominant_regime_share_pct", "regime_stability_score", "regime_loss_ratio",
            "regime_trade_count_by_label", "regime_pnl_by_label", "regime_pf_by_label", "regime_win_rate_by_label",
            "regime_filter_label", "broker_swap_available", "broker_swap_long", "broker_swap_short",
            "broker_preferred_carry_side", "broker_carry_spread", "mc_simulations", "mc_pnl_median", "mc_pnl_p05",
            "mc_pnl_p95", "mc_max_drawdown_pct_median", "mc_max_drawdown_pct_p95", "mc_loss_probability_pct",
            "walk_forward_windows", "walk_forward_pass_rate_pct", "walk_forward_avg_validation_pnl",
            "walk_forward_avg_test_pnl", "walk_forward_avg_validation_pf", "walk_forward_avg_test_pf", "train_pnl",
            "validation_pnl", "validation_profit_factor", "validation_closed_trades", "test_pnl",
            "test_profit_factor", "test_closed_trades", "trade_log_path", "trade_analysis_path",
        ])
        for row in rows:
            writer.writerow([
                row.name, row.description, row.archetype, row.variant_label, row.timeframe_label, row.session_label,
                strategy_family_fn(row), direction_mode_fn(row), direction_role_fn(row),
                f"{row.realized_pnl:.5f}", row.closed_trades, f"{row.win_rate_pct:.5f}", f"{row.profit_factor:.5f}",
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
                row.broker_preferred_carry_side, f"{row.broker_carry_spread:.5f}", row.mc_simulations,
                f"{row.mc_pnl_median:.5f}", f"{row.mc_pnl_p05:.5f}", f"{row.mc_pnl_p95:.5f}",
                f"{row.mc_max_drawdown_pct_median:.5f}", f"{row.mc_max_drawdown_pct_p95:.5f}",
                f"{row.mc_loss_probability_pct:.5f}", row.walk_forward_windows, f"{row.walk_forward_pass_rate_pct:.5f}",
                f"{row.walk_forward_avg_validation_pnl:.5f}", f"{row.walk_forward_avg_test_pnl:.5f}",
                f"{row.walk_forward_avg_validation_pf:.5f}", f"{row.walk_forward_avg_test_pf:.5f}",
                f"{row.train_pnl:.5f}", f"{row.validation_pnl:.5f}", f"{row.validation_profit_factor:.5f}",
                row.validation_closed_trades, f"{row.test_pnl:.5f}", f"{row.test_profit_factor:.5f}",
                row.test_closed_trades, row.trade_log_path, row.trade_analysis_path,
            ])

    ranked = sorted(rows, key=lambda item: (item.realized_pnl, item.profit_factor, item.closed_trades), reverse=True)
    lines = [f"Symbol research: {symbol}", f"Broker symbol: {broker_symbol}", f"Data source: {data_source}", "", "Ranked candidates"]
    for row in ranked:
        candidate_row = execution_candidate_row_from_result_fn(symbol, row)
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
        lines.append(f"  unified_regimes: best={row.best_unified_regime or 'none'} worst={row.worst_unified_regime or 'none'}")
        lines.append(f"  regime_trade_counts: {row.regime_trade_count_by_label}")
        lines.append(f"  regime_pnls: {row.regime_pnl_by_label}")
        lines.append(
            f"  funding: available={'yes' if row.broker_swap_available else 'no'} "
            f"swap_long={row.broker_swap_long:.5f} swap_short={row.broker_swap_short:.5f} "
            f"preferred_side={row.broker_preferred_carry_side or 'none'} carry_spread={row.broker_carry_spread:.5f}"
        )
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
    winners = [row for row in ranked if meets_viability_fn(row, symbol)]
    lines.extend(["", "Top candidate-level winners"])
    if winners:
        for row in winners[:3]:
            tier = promotion_tier_for_row_fn(row, symbol)
            lines.append(f"- {row.name} [{tier}] ({row.description})")
    else:
        lines.append("No candidate met the positive-PnL and PF>=1.0 threshold.")
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, txt_path

