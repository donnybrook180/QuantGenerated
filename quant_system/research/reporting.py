from __future__ import annotations

from pathlib import Path


def candidate_failure_reasons(
    row: object,
    symbol: str,
    *,
    meets_regime_specialist_viability_fn,
    research_thresholds_fn,
    is_sparse_candidate_fn,
) -> list[str]:
    reasons: list[str] = []
    specialist_viable = meets_regime_specialist_viability_fn(row, symbol)
    thresholds = research_thresholds_fn(symbol)
    validation_min = int(thresholds["validation_closed_trades"])
    test_min = int(thresholds["test_closed_trades"])
    wf_pass_min = float(thresholds["walk_forward_min_pass_rate_pct"])
    sparse_strategy = is_sparse_candidate_fn(row, symbol)

    mc_simulations = int(getattr(row, "mc_simulations", 0))
    if mc_simulations <= 0:
        reasons.append("monte carlo missing (no simulations recorded)")
    else:
        mc_pnl_p05 = float(getattr(row, "mc_pnl_p05", 0.0))
        mc_loss_probability_pct = float(getattr(row, "mc_loss_probability_pct", 0.0))
        if mc_pnl_p05 <= 0.0:
            reasons.append(f"monte carlo p05 pnl <= 0 ({mc_pnl_p05:.2f})")
        if mc_loss_probability_pct > 10.0:
            reasons.append(f"monte carlo loss probability too high ({mc_loss_probability_pct:.2f}% > 10.00%)")

    validation_closed_trades = int(getattr(row, "validation_closed_trades", 0))
    test_closed_trades = int(getattr(row, "test_closed_trades", 0))
    validation_pnl = float(getattr(row, "validation_pnl", 0.0))
    test_pnl = float(getattr(row, "test_pnl", 0.0))
    validation_profit_factor = float(getattr(row, "validation_profit_factor", 0.0))
    test_profit_factor = float(getattr(row, "test_profit_factor", 0.0))

    if sparse_strategy:
        combined_closed = validation_closed_trades + test_closed_trades
        combined_required = int(thresholds["sparse_combined_closed_trades"])
        if combined_closed < combined_required:
            reasons.append(f"combined validation/test trades too low ({combined_closed} < {combined_required})")
        if (validation_pnl + test_pnl) <= 0.0:
            reasons.append(f"combined validation/test pnl <= 0 ({validation_pnl + test_pnl:.2f})")
        if max(validation_profit_factor, test_profit_factor) < 1.0:
            reasons.append(
                f"combined validation/test PF too low ({max(validation_profit_factor, test_profit_factor):.2f} < 1.00)"
            )
        wf_pass_min = float(thresholds["sparse_walk_forward_min_pass_rate_pct"])
    else:
        if validation_closed_trades < validation_min:
            reasons.append(f"validation trades too low ({validation_closed_trades} < {validation_min})")
        if test_closed_trades < test_min:
            reasons.append(f"test trades too low ({test_closed_trades} < {test_min})")
        if validation_pnl <= 0.0:
            reasons.append(f"validation pnl <= 0 ({validation_pnl:.2f})")
        if test_pnl <= 0.0:
            reasons.append(f"test pnl <= 0 ({test_pnl:.2f})")
        if validation_profit_factor < 1.0:
            reasons.append(f"validation PF < 1.0 ({validation_profit_factor:.2f})")
        if test_profit_factor < 1.0:
            reasons.append(f"test PF < 1.0 ({test_profit_factor:.2f})")

    walk_forward_windows = int(getattr(row, "walk_forward_windows", 0))
    walk_forward_pass_rate_pct = float(getattr(row, "walk_forward_pass_rate_pct", 0.0))
    walk_forward_soft_pass_rate_pct = float(getattr(row, "walk_forward_soft_pass_rate_pct", 0.0))
    walk_forward_avg_validation_pnl = float(getattr(row, "walk_forward_avg_validation_pnl", 0.0))
    walk_forward_avg_test_pnl = float(getattr(row, "walk_forward_avg_test_pnl", 0.0))
    best_regime = str(getattr(row, "best_regime", "") or "")
    best_regime_pnl = float(getattr(row, "best_regime_pnl", 0.0))
    regime_stability_score = float(getattr(row, "regime_stability_score", 0.0))
    regime_loss_ratio = float(getattr(row, "regime_loss_ratio", 0.0))
    equity_quality_score = float(getattr(row, "equity_quality_score", 0.0))
    best_trade_share_pct = float(getattr(row, "best_trade_share_pct", 0.0))
    component_count = int(getattr(row, "component_count", 1))
    combo_outperformance_score = float(getattr(row, "combo_outperformance_score", 0.0))
    combo_trade_overlap_pct = float(getattr(row, "combo_trade_overlap_pct", 0.0))

    if walk_forward_windows < 1:
        reasons.append("no walk-forward windows")
    effective_pass_rate = walk_forward_soft_pass_rate_pct if sparse_strategy else walk_forward_pass_rate_pct
    if effective_pass_rate < wf_pass_min:
        reasons.append(f"walk-forward pass rate too low ({effective_pass_rate:.2f}% < {wf_pass_min:.0f}%)")
    if walk_forward_avg_validation_pnl <= 0.0:
        reasons.append(f"walk-forward avg validation pnl <= 0 ({walk_forward_avg_validation_pnl:.2f})")
    if walk_forward_avg_test_pnl <= 0.0:
        reasons.append(f"walk-forward avg test pnl <= 0 ({walk_forward_avg_test_pnl:.2f})")
    if not best_regime:
        reasons.append("no regime edge identified")
    if best_regime_pnl <= 0.0:
        reasons.append(f"best regime pnl <= 0 ({best_regime_pnl:.2f})")
    if regime_stability_score < 0.50:
        reasons.append(f"regime stability too low ({regime_stability_score:.2f} < 0.50)")
    if regime_loss_ratio > 1.25:
        reasons.append(f"regime loss ratio too high ({regime_loss_ratio:.2f} > 1.25)")
    if equity_quality_score < 0.45:
        reasons.append(f"equity quality too low ({equity_quality_score:.2f} < 0.45)")
    if best_trade_share_pct > 70.0:
        reasons.append(f"best trade concentration too high ({best_trade_share_pct:.2f}% > 70%)")
    if component_count > 1 and combo_outperformance_score < 0.0:
        reasons.append(f"combo underperformed components ({combo_outperformance_score:.2f})")
    if component_count > 1 and combo_trade_overlap_pct > 80.0:
        reasons.append(f"combo overlap too high ({combo_trade_overlap_pct:.2f}% > 80%)")
    if reasons and specialist_viable:
        reasons.append("broad viability failed, but candidate qualifies as a regime specialist")
    return reasons


def export_viability_autopsy(
    symbol: str,
    rows: list[object],
    execution_validation_summary: str,
    *,
    reports_dir_fn,
    promotion_tier_for_row_fn,
    candidate_failure_reasons_fn,
) -> Path:
    path = reports_dir_fn(symbol) / "viability_autopsy.txt"
    ranked = sorted(
        rows,
        key=lambda item: (
            float(getattr(item, "realized_pnl", 0.0)),
            float(getattr(item, "profit_factor", 0.0)),
            int(getattr(item, "closed_trades", 0)),
        ),
        reverse=True,
    )
    counts: dict[str, int] = {}
    near_misses: list[tuple[object, list[str]]] = []
    tier_counts = {"core": 0, "specialist": 0, "reject": 0}
    for row in ranked:
        tier = promotion_tier_for_row_fn(row, symbol)
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        reasons = candidate_failure_reasons_fn(row, symbol)
        for reason in reasons:
            counts[reason] = counts.get(reason, 0) + 1
        if reasons:
            near_misses.append((row, reasons))

    lines = [
        f"Viability autopsy: {symbol}",
        f"Execution validation summary: {execution_validation_summary}",
        f"Tier counts: core={tier_counts['core']} specialist={tier_counts['specialist']} reject={tier_counts['reject']}",
        "",
        "Top blockers",
    ]
    for reason, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:8]:
        lines.append(f"- {reason}: {count}")
    lines.extend(["", "Top near-misses"])
    for row, reasons in near_misses[:8]:
        tier = promotion_tier_for_row_fn(row, symbol)
        lines.append(
            f"- {getattr(row, 'name', 'unknown')} [{tier}]: pnl={float(getattr(row, 'realized_pnl', 0.0)):.2f} "
            f"pf={float(getattr(row, 'profit_factor', 0.0)):.2f} "
            f"val={float(getattr(row, 'validation_pnl', 0.0)):.2f}/{float(getattr(row, 'validation_profit_factor', 0.0)):.2f}/{int(getattr(row, 'validation_closed_trades', 0))} "
            f"test={float(getattr(row, 'test_pnl', 0.0)):.2f}/{float(getattr(row, 'test_profit_factor', 0.0)):.2f}/{int(getattr(row, 'test_closed_trades', 0))} "
            f"wf={float(getattr(row, 'walk_forward_pass_rate_pct', 0.0)):.2f}%"
        )
        lines.append(f"  reasons: {', '.join(reasons)}")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
