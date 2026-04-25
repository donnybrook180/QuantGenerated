from __future__ import annotations

from quant_system.research.common import (
    is_sparse_candidate,
    meets_monte_carlo_viability,
    metric_map_from_row,
    research_thresholds,
    row_value,
)


def meets_viability(row: object | dict[str, object], symbol: str) -> bool:
    thresholds = research_thresholds(symbol)
    realized_pnl = float(row_value(row, "realized_pnl", 0.0) or 0.0)
    profit_factor = float(row_value(row, "profit_factor", 0.0) or 0.0)
    validation_closed_trades = int(row_value(row, "validation_closed_trades", 0) or 0)
    test_closed_trades = int(row_value(row, "test_closed_trades", 0) or 0)
    validation_pnl = float(row_value(row, "validation_pnl", 0.0) or 0.0)
    test_pnl = float(row_value(row, "test_pnl", 0.0) or 0.0)
    validation_profit_factor = float(row_value(row, "validation_profit_factor", 0.0) or 0.0)
    test_profit_factor = float(row_value(row, "test_profit_factor", 0.0) or 0.0)
    walk_forward_windows = int(row_value(row, "walk_forward_windows", 0) or 0)
    walk_forward_pass_rate_pct = float(row_value(row, "walk_forward_pass_rate_pct", 0.0) or 0.0)
    walk_forward_avg_validation_pnl = float(row_value(row, "walk_forward_avg_validation_pnl", 0.0) or 0.0)
    walk_forward_avg_test_pnl = float(row_value(row, "walk_forward_avg_test_pnl", 0.0) or 0.0)
    component_count = int(row_value(row, "component_count", 1) or 1)
    combo_outperformance_score = float(row_value(row, "combo_outperformance_score", 0.0) or 0.0)
    combo_trade_overlap_pct = float(row_value(row, "combo_trade_overlap_pct", 0.0) or 0.0)
    best_regime = str(row_value(row, "best_regime", "") or "")
    best_regime_pnl = float(row_value(row, "best_regime_pnl", 0.0) or 0.0)
    regime_stability_score = float(row_value(row, "regime_stability_score", 0.0) or 0.0)
    regime_loss_ratio_raw = row_value(row, "regime_loss_ratio", 999.0)
    regime_loss_ratio = 999.0 if regime_loss_ratio_raw is None else float(regime_loss_ratio_raw)
    best_trade_share_pct = float(row_value(row, "best_trade_share_pct", 0.0) or 0.0)
    equity_quality_score = float(row_value(row, "equity_quality_score", 0.0) or 0.0)
    timeframe_label = str(row_value(row, "timeframe_label", "") or "")
    sparse_strategy = is_sparse_candidate(row, symbol)
    core_use_combined_splits = bool(thresholds.get("core_use_combined_splits", 0))
    core_combined_closed_trades = int(thresholds.get("core_combined_closed_trades", 0) or 0)
    core_allow_positive_validation_only = bool(thresholds.get("core_allow_positive_validation_only", 0))
    sparse_combined_closed_trades = validation_closed_trades + test_closed_trades
    sparse_pass_rate_threshold = (
        float(thresholds["sparse_walk_forward_min_pass_rate_pct"]) if sparse_strategy else float(thresholds["walk_forward_min_pass_rate_pct"])
    )
    sparse_window_pass_rate = float(row_value(row, "walk_forward_soft_pass_rate_pct", 0.0) or 0.0)
    if sparse_strategy:
        split_trade_requirement_met = sparse_combined_closed_trades >= int(thresholds["sparse_combined_closed_trades"])
        split_pnl_requirement_met = (validation_pnl + test_pnl) > 0.0
        split_pf_requirement_met = max(validation_profit_factor, test_profit_factor) >= float(thresholds["min_profit_factor"])
    elif core_use_combined_splits:
        combined_closed = validation_closed_trades + test_closed_trades
        combined_pnl = validation_pnl + test_pnl
        split_trade_requirement_met = combined_closed >= max(1, core_combined_closed_trades)
        split_pnl_requirement_met = validation_pnl > 0.0 if core_allow_positive_validation_only else combined_pnl > 0.0
        split_pf_requirement_met = max(validation_profit_factor, test_profit_factor, profit_factor) >= float(thresholds["min_profit_factor"])
    else:
        split_trade_requirement_met = (
            validation_closed_trades >= int(thresholds["validation_closed_trades"])
            and test_closed_trades >= int(thresholds["test_closed_trades"])
        )
        split_pnl_requirement_met = validation_pnl > 0.0 and test_pnl > 0.0
        split_pf_requirement_met = (
            validation_profit_factor >= float(thresholds["min_profit_factor"])
            and test_profit_factor >= float(thresholds["min_profit_factor"])
        )
    walk_forward_pass_requirement_met = (
        sparse_window_pass_rate >= sparse_pass_rate_threshold
        if sparse_strategy
        else walk_forward_pass_rate_pct >= float(thresholds["walk_forward_min_pass_rate_pct"])
    )
    viable = (
        realized_pnl > 0.0
        and profit_factor >= float(thresholds["min_profit_factor"])
        and split_trade_requirement_met
        and split_pnl_requirement_met
        and split_pf_requirement_met
        and walk_forward_windows >= int(thresholds["walk_forward_min_windows"])
        and walk_forward_pass_requirement_met
        and (walk_forward_avg_validation_pnl > 0.0 and (walk_forward_avg_test_pnl > 0.0 or core_allow_positive_validation_only))
        and bool(best_regime)
        and best_regime_pnl > 0.0
        and regime_stability_score >= 0.50
        and regime_loss_ratio <= 1.25
        and equity_quality_score >= 0.45
        and best_trade_share_pct <= 70.0
        and (component_count <= 1 or (combo_outperformance_score >= 0.0 and combo_trade_overlap_pct <= 80.0))
        and meets_monte_carlo_viability(row)
    )
    if not viable:
        return False
    if timeframe_label != "4h":
        return True
    combined_closed_trades = validation_closed_trades + test_closed_trades
    return (
        int(row_value(row, "closed_trades", 0) or 0) >= 4
        and combined_closed_trades >= 2
        and walk_forward_windows >= 1
        and regime_stability_score >= 0.60
        and equity_quality_score >= 0.50
        and best_trade_share_pct <= 80.0
    )


def meets_regime_specialist_viability(row: object | dict[str, object], symbol: str) -> bool:
    if meets_viability(row, symbol):
        return False
    thresholds = research_thresholds(symbol)
    realized_pnl = float(row_value(row, "realized_pnl", 0.0) or 0.0)
    profit_factor = float(row_value(row, "profit_factor", 0.0) or 0.0)
    validation_pnl = float(row_value(row, "validation_pnl", 0.0) or 0.0)
    test_pnl = float(row_value(row, "test_pnl", 0.0) or 0.0)
    validation_profit_factor = float(row_value(row, "validation_profit_factor", 0.0) or 0.0)
    test_profit_factor = float(row_value(row, "test_profit_factor", 0.0) or 0.0)
    walk_forward_windows = int(row_value(row, "walk_forward_windows", 0) or 0)
    walk_forward_pass_rate_pct = float(row_value(row, "walk_forward_pass_rate_pct", 0.0) or 0.0)
    walk_forward_soft_pass_rate_pct = float(row_value(row, "walk_forward_soft_pass_rate_pct", 0.0) or 0.0)
    best_regime = str(row_value(row, "best_regime", "") or "")
    best_regime_pnl = float(row_value(row, "best_regime_pnl", 0.0) or 0.0)
    regime_stability_score = float(row_value(row, "regime_stability_score", 0.0) or 0.0)
    regime_loss_ratio_raw = row_value(row, "regime_loss_ratio", 999.0)
    regime_loss_ratio = 999.0 if regime_loss_ratio_raw is None else float(regime_loss_ratio_raw)
    regime_trade_counts = metric_map_from_row(row, "regime_trade_count_by_label")
    regime_pf_by_label = metric_map_from_row(row, "regime_pf_by_label")
    best_regime_trade_count = int(regime_trade_counts.get(best_regime, 0.0))
    best_regime_pf = float(regime_pf_by_label.get(best_regime, 0.0))
    effective_pass_rate = max(walk_forward_pass_rate_pct, walk_forward_soft_pass_rate_pct)
    best_trade_share_pct = float(row_value(row, "best_trade_share_pct", 0.0) or 0.0)
    equity_quality_score = float(row_value(row, "equity_quality_score", 0.0) or 0.0)
    closed_trades = int(row_value(row, "closed_trades", 0) or 0)
    walk_forward_avg_validation_pnl = float(row_value(row, "walk_forward_avg_validation_pnl", 0.0) or 0.0)
    walk_forward_avg_test_pnl = float(row_value(row, "walk_forward_avg_test_pnl", 0.0) or 0.0)
    combined_closed_trades = int(row_value(row, "validation_closed_trades", 0) or 0) + int(row_value(row, "test_closed_trades", 0) or 0)
    regime_filter_label = str(row_value(row, "regime_filter_label", "") or "")
    payoff_ratio = float(row_value(row, "payoff_ratio", 0.0) or 0.0)
    mc_pnl_p05 = float(row_value(row, "mc_pnl_p05", 0.0) or 0.0)
    mc_loss_probability_pct = float(row_value(row, "mc_loss_probability_pct", 100.0) or 100.0)
    if symbol.upper() == "BTC":
        if (
            is_sparse_candidate(row, symbol)
            and realized_pnl > 0.0
            and profit_factor >= 1.25
            and closed_trades >= 5
            and bool(best_regime)
            and best_regime_pnl > 0.0
            and best_regime_trade_count >= 5
            and best_regime_pf >= 1.0
            and walk_forward_windows >= 1
            and walk_forward_avg_validation_pnl > 0.0
            and walk_forward_avg_test_pnl >= 0.0
            and effective_pass_rate >= 0.0
            and regime_stability_score >= 0.65
            and regime_loss_ratio <= 0.75
            and equity_quality_score >= 0.35
            and best_trade_share_pct <= 85.0
            and combined_closed_trades == 0
            and meets_monte_carlo_viability(row)
        ):
            return True
    if symbol.upper() == "USDJPY":
        if (
            regime_filter_label == "trend_flat"
            and best_regime == "trend_flat_vol_low"
            and realized_pnl > 0.0
            and profit_factor >= 5.0
            and closed_trades >= 40
            and best_regime_pnl > 0.0
            and best_regime_trade_count >= 30
            and best_regime_pf >= 1.2
            and walk_forward_windows >= 1
            and effective_pass_rate >= 50.0
            and walk_forward_avg_validation_pnl > 0.0
            and walk_forward_avg_test_pnl > 0.0
            and validation_profit_factor >= 0.4
            and test_profit_factor >= 0.9
            and validation_pnl >= -1_000.0
            and test_pnl >= -500.0
            and regime_stability_score >= 0.9
            and regime_loss_ratio <= 0.25
            and equity_quality_score >= 0.35
            and best_trade_share_pct <= 80.0
            and mc_pnl_p05 >= -500.0
            and mc_loss_probability_pct <= 10.0
        ):
            return True
    if symbol.upper() == "GBPUSD":
        if (
            best_regime == "trend_flat_vol_mid"
            and regime_filter_label == "trend_flat_vol_mid"
            and realized_pnl > 0.0
            and profit_factor >= 1.2
            and payoff_ratio >= 1.75
            and closed_trades >= 3
            and best_regime_trade_count >= 3
            and best_regime_pnl > 0.0
            and best_regime_pf >= 1.2
            and regime_stability_score >= 0.9
            and regime_loss_ratio <= 0.25
            and equity_quality_score >= 0.3
            and walk_forward_windows >= 1
            and combined_closed_trades == 0
        ):
            return True
    return (
        realized_pnl > 0.0
        and profit_factor >= float(thresholds["min_profit_factor"])
        and bool(best_regime)
        and best_regime_pnl > 0.0
        and best_regime_trade_count >= max(2, int(thresholds["sparse_combined_closed_trades"]))
        and combined_closed_trades >= max(2, int(thresholds["sparse_combined_closed_trades"]))
        and best_regime_pf >= float(thresholds["min_profit_factor"])
        and (validation_pnl > 0.0 or test_pnl > 0.0)
        and max(validation_profit_factor, test_profit_factor, best_regime_pf) >= float(thresholds["min_profit_factor"])
        and walk_forward_windows >= int(thresholds["walk_forward_min_windows"])
        and effective_pass_rate >= float(thresholds["sparse_walk_forward_min_pass_rate_pct"])
        and regime_stability_score >= 0.65
        and regime_loss_ratio <= 0.75
        and equity_quality_score >= 0.35
        and best_trade_share_pct <= 80.0
        and meets_monte_carlo_viability(row)
    )


def specialist_live_gate(row: object | dict[str, object], symbol: str) -> tuple[bool, list[str]]:
    specialist_viable = bool(row.get("regime_specialist_viable", False)) if isinstance(row, dict) else meets_regime_specialist_viability(row, symbol)
    if not specialist_viable:
        return False, ["not_regime_specialist_viable"]
    closed_trades = int(row_value(row, "closed_trades", 0) or 0)
    profit_factor = float(row_value(row, "profit_factor", 0.0) or 0.0)
    validation_pnl = float(row_value(row, "validation_pnl", 0.0) or 0.0)
    test_pnl = float(row_value(row, "test_pnl", 0.0) or 0.0)
    validation_closed_trades = int(row_value(row, "validation_closed_trades", 0) or 0)
    test_closed_trades = int(row_value(row, "test_closed_trades", 0) or 0)
    dominant_regime_share_pct = float(row_value(row, "dominant_regime_share_pct", 0.0) or 0.0)
    equity_quality_score = float(row_value(row, "equity_quality_score", 0.0) or 0.0)
    walk_forward_pass_rate_pct = float(row_value(row, "walk_forward_pass_rate_pct", 0.0) or 0.0)
    walk_forward_soft_pass_rate_pct = float(row_value(row, "walk_forward_soft_pass_rate_pct", 0.0) or 0.0)
    best_regime = str(row_value(row, "best_regime", "") or "").strip()
    reasons: list[str] = []
    if closed_trades < 8:
        reasons.append(f"specialist_closed_trades_too_low({closed_trades}<8)")
    if profit_factor < 1.75:
        reasons.append(f"specialist_profit_factor_too_low({profit_factor:.2f}<1.75)")
    if dominant_regime_share_pct < 55.0:
        reasons.append(f"specialist_regime_niche_too_broad({dominant_regime_share_pct:.1f}<55.0)")
    if equity_quality_score < 0.55:
        reasons.append(f"specialist_equity_quality_too_low({equity_quality_score:.2f}<0.55)")
    effective_pass_rate = max(walk_forward_pass_rate_pct, walk_forward_soft_pass_rate_pct)
    if effective_pass_rate <= 0.0:
        reasons.append("specialist_walk_forward_confirmation_missing")
    if validation_closed_trades + test_closed_trades < 3:
        reasons.append(f"specialist_out_of_sample_trades_too_low({validation_closed_trades + test_closed_trades}<3)")
    if validation_pnl < 0.0 and test_pnl <= 0.0:
        reasons.append(f"specialist_negative_out_of_sample(validation={validation_pnl:.2f},test={test_pnl:.2f})")
    if not best_regime:
        reasons.append("specialist_best_regime_missing")
    return not reasons, reasons


def promotion_tier_for_row(row: object | dict[str, object], symbol: str) -> str:
    if meets_viability(row, symbol):
        return "core"
    if meets_regime_specialist_viability(row, symbol):
        return "specialist"
    return "reject"
