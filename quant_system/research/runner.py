from __future__ import annotations

import asyncio
import copy
from statistics import mean

from quant_system.execution.engine import ExecutionResult


def score_result(
    *,
    candidate_result_cls,
    sharpe_ratio_fn,
    sortino_ratio_fn,
    calmar_ratio_fn,
    monte_carlo_summary_fn,
    name: str,
    description: str,
    archetype: str,
    code_path: str,
    result: ExecutionResult,
    initial_cash: float,
):
    wins = [trade.pnl for trade in result.closed_trades if trade.pnl > 0]
    losses = [trade.pnl for trade in result.closed_trades if trade.pnl < 0]
    pnls = [trade.pnl for trade in result.closed_trades]
    expectancy = mean(result.closed_trade_pnls) if result.closed_trade_pnls else 0.0
    sharpe_ratio = sharpe_ratio_fn(result.closed_trade_pnls)
    sortino_ratio = sortino_ratio_fn(result.closed_trade_pnls)
    calmar_ratio = calmar_ratio_fn(result.realized_pnl, result.max_drawdown, initial_cash)
    monte_carlo = monte_carlo_summary_fn(result.closed_trade_pnls, initial_cash)
    avg_win = mean(wins) if wins else 0.0
    avg_loss = mean(losses) if losses else 0.0
    payoff_ratio = (avg_win / abs(avg_loss)) if avg_loss < 0 else (999.0 if avg_win > 0 else 0.0)
    avg_hold_bars = mean([trade.hold_bars for trade in result.closed_trades]) if result.closed_trades else 0.0
    gross_profit = sum(wins)
    best_trade_share_pct = (max(wins) / gross_profit * 100.0) if wins and gross_profit > 0.0 else 0.0
    equity = 0.0
    peak = 0.0
    new_high_count = 0
    current_loss_streak = 0
    max_consecutive_losses = 0
    for pnl in pnls:
        equity += pnl
        if equity >= peak:
            peak = equity
            new_high_count += 1
        if pnl < 0.0:
            current_loss_streak += 1
            max_consecutive_losses = max(max_consecutive_losses, current_loss_streak)
        else:
            current_loss_streak = 0
    trade_count = len(result.closed_trades)
    equity_new_high_share_pct = (new_high_count / trade_count * 100.0) if trade_count > 0 else 0.0
    quality_components = [
        min(max(payoff_ratio, 0.0), 3.0) / 3.0,
        min(max(equity_new_high_share_pct, 0.0), 100.0) / 100.0,
        1.0 - min(best_trade_share_pct, 100.0) / 100.0,
        1.0 - (max_consecutive_losses / trade_count if trade_count > 0 else 1.0),
    ]
    equity_quality_score = sum(quality_components) / float(len(quality_components)) if quality_components else 0.0
    exit_counts: dict[str, int] = {}
    for trade in result.closed_trades:
        exit_counts[trade.exit_reason] = exit_counts.get(trade.exit_reason, 0) + 1
    dominant_exit = max(exit_counts, key=exit_counts.get) if exit_counts else ""
    dominant_exit_share_pct = (
        (exit_counts[dominant_exit] / len(result.closed_trades) * 100.0) if dominant_exit and result.closed_trades else 0.0
    )
    return candidate_result_cls(
        name=name,
        description=description,
        archetype=archetype,
        code_path=code_path,
        realized_pnl=result.realized_pnl,
        closed_trades=len(result.closed_trades),
        win_rate_pct=result.win_rate_pct,
        profit_factor=result.profit_factor,
        max_drawdown_pct=result.max_drawdown * 100.0,
        total_costs=result.total_costs,
        expectancy=expectancy,
        sharpe_ratio=sharpe_ratio,
        sortino_ratio=sortino_ratio,
        calmar_ratio=calmar_ratio,
        avg_win=avg_win,
        avg_loss=avg_loss,
        payoff_ratio=payoff_ratio,
        avg_hold_bars=avg_hold_bars,
        best_trade_share_pct=best_trade_share_pct,
        equity_new_high_share_pct=equity_new_high_share_pct,
        max_consecutive_losses=max_consecutive_losses,
        equity_quality_score=equity_quality_score,
        dominant_exit=dominant_exit,
        dominant_exit_share_pct=dominant_exit_share_pct,
        mc_simulations=int(monte_carlo["mc_simulations"]),
        mc_pnl_median=monte_carlo["mc_pnl_median"],
        mc_pnl_p05=monte_carlo["mc_pnl_p05"],
        mc_pnl_p95=monte_carlo["mc_pnl_p95"],
        mc_max_drawdown_pct_median=monte_carlo["mc_max_drawdown_pct_median"],
        mc_max_drawdown_pct_p95=monte_carlo["mc_max_drawdown_pct_p95"],
        mc_loss_probability_pct=monte_carlo["mc_loss_probability_pct"],
    )


def run_candidate(
    config,
    features,
    spec,
    archetype: str,
    artifact_prefix: str,
    *,
    with_execution_overrides_fn,
    with_session_gate_fn,
    build_engine_fn,
    export_closed_trade_artifacts_fn,
    score_result_fn,
    spec_strategy_family_fn,
    spec_direction_mode_fn,
    spec_direction_role_fn,
    annotate_regime_metrics_fn,
    annotate_funding_context_fn,
):
    candidate_config = with_execution_overrides_fn(config, spec.execution_overrides)
    symbol = features[0].symbol if features else ""
    agents = with_session_gate_fn(copy.deepcopy(spec.agents), spec.session_label, symbol)
    engine = build_engine_fn(candidate_config, agents)
    result = asyncio.run(engine.run(features, sleep_seconds=0.0))
    trades_path, analysis_path = export_closed_trade_artifacts_fn(
        result.closed_trades,
        result.realized_pnl,
        artifact_prefix,
    )
    scored = score_result_fn(spec.name, spec.description, archetype, spec.code_path, result, candidate_config.execution.initial_cash)
    scored.trade_log_path = str(trades_path)
    scored.trade_analysis_path = str(analysis_path)
    scored.variant_label = spec.variant_label
    scored.timeframe_label = spec.timeframe_label
    scored.session_label = spec.session_label
    scored.strategy_family = spec_strategy_family_fn(spec)
    scored.direction_mode = spec_direction_mode_fn(spec)
    scored.direction_role = spec_direction_role_fn(spec)
    scored.regime_filter_label = spec.regime_filter_label
    scored.cross_filter_label = spec.cross_filter_label
    scored.execution_overrides = copy.deepcopy(spec.execution_overrides)
    annotate_regime_metrics_fn(scored, features, result.closed_trades)
    annotate_funding_context_fn(scored, features, result.closed_trades)
    return scored


def run_candidate_with_splits(
    config,
    features,
    spec,
    archetype: str,
    artifact_prefix: str,
    *,
    run_candidate_fn,
    research_thresholds_fn,
    is_sparse_candidate_fn,
    with_execution_overrides_fn,
    with_session_gate_fn,
    build_engine_fn,
    walk_forward_slices_fn,
    aggregate_profit_factor_fn,
):
    scored = run_candidate_fn(config, features, spec, archetype, artifact_prefix)
    symbol = features[0].symbol if features else ""
    thresholds = research_thresholds_fn(symbol)
    scored.sparse_strategy = is_sparse_candidate_fn(scored, symbol)

    def _eval_slice(slice_features) -> ExecutionResult | None:
        if len(slice_features) < 10:
            return None
        candidate_config = with_execution_overrides_fn(config, spec.execution_overrides)
        local_symbol = slice_features[0].symbol if slice_features else ""
        agents = with_session_gate_fn(copy.deepcopy(spec.agents), spec.session_label, local_symbol)
        engine = build_engine_fn(candidate_config, agents)
        return asyncio.run(engine.run(slice_features, sleep_seconds=0.0))

    windows = walk_forward_slices_fn(features, symbol)
    validation_pnls: list[float] = []
    test_pnls: list[float] = []
    validation_pfs: list[float] = []
    test_pfs: list[float] = []
    pass_count = 0
    soft_pass_count = 0
    last_train_result: ExecutionResult | None = None
    last_validation_result: ExecutionResult | None = None
    last_test_result: ExecutionResult | None = None

    for train_features, validation_features, test_features in windows:
        train_result = _eval_slice(train_features)
        validation_result = _eval_slice(validation_features)
        test_result = _eval_slice(test_features)
        if validation_result is None or test_result is None:
            continue
        last_train_result = train_result
        last_validation_result = validation_result
        last_test_result = test_result
        validation_pnls.append(validation_result.realized_pnl)
        test_pnls.append(test_result.realized_pnl)
        validation_pfs.append(validation_result.profit_factor)
        test_pfs.append(test_result.profit_factor)
        combined_closed_trades = len(validation_result.closed_trades) + len(test_result.closed_trades)
        combined_pnl = validation_result.realized_pnl + test_result.realized_pnl
        combined_pf = aggregate_profit_factor_fn(validation_result.closed_trade_pnls, test_result.closed_trade_pnls)
        if (
            len(validation_result.closed_trades) >= int(thresholds["validation_closed_trades"])
            and len(test_result.closed_trades) >= int(thresholds["test_closed_trades"])
            and validation_result.realized_pnl > 0.0
            and test_result.realized_pnl > 0.0
            and validation_result.profit_factor >= float(thresholds["min_profit_factor"])
            and test_result.profit_factor >= float(thresholds["min_profit_factor"])
        ):
            pass_count += 1
        if (
            scored.sparse_strategy
            and combined_closed_trades >= int(thresholds["sparse_combined_closed_trades"])
            and combined_pnl > 0.0
            and combined_pf >= float(thresholds["min_profit_factor"])
        ):
            soft_pass_count += 1

    if last_train_result is not None:
        scored.train_pnl = last_train_result.realized_pnl
    if last_validation_result is not None:
        scored.validation_pnl = last_validation_result.realized_pnl
        scored.validation_profit_factor = last_validation_result.profit_factor
        scored.validation_closed_trades = len(last_validation_result.closed_trades)
    if last_test_result is not None:
        scored.test_pnl = last_test_result.realized_pnl
        scored.test_profit_factor = last_test_result.profit_factor
        scored.test_closed_trades = len(last_test_result.closed_trades)
    scored.walk_forward_windows = len(validation_pnls)
    if validation_pnls:
        scored.walk_forward_avg_validation_pnl = mean(validation_pnls)
        scored.walk_forward_avg_validation_pf = mean(validation_pfs)
    if test_pnls:
        scored.walk_forward_avg_test_pnl = mean(test_pnls)
        scored.walk_forward_avg_test_pf = mean(test_pfs)
    if scored.walk_forward_windows > 0:
        scored.walk_forward_pass_rate_pct = pass_count / scored.walk_forward_windows * 100.0
        scored.walk_forward_soft_pass_rate_pct = soft_pass_count / scored.walk_forward_windows * 100.0

    return scored
