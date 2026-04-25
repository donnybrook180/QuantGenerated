from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable

from quant_system.models import OrderRequest, Side


def net_quantity(positions: list[object]) -> float:
    quantity = 0.0
    for position in positions:
        quantity += position.quantity if position.side == Side.BUY else -position.quantity
    return quantity


def reconcile_strategy(
    *,
    client,
    strategy,
    deployment,
    config,
    interpreter_state,
    relax_gates_for_mini_trades: bool,
    signal_side: Side,
    signal_timestamp,
    confidence: float,
    snapshot,
    allocation_fraction: float,
    allocator_score: float,
    account_equity: float,
    latest_feature,
    strategy_portfolio_weight: float,
    strategy_magic_fn,
    strategy_action_cls,
    effective_risk_multiplier_fn,
    is_weekend_entry_block_fn,
    should_force_weekend_flatten_fn,
    interpreter_block_reason_fn,
    is_strategy_regime_blocked_fn,
    build_strategy_config_fn,
    compute_order_size_fn,
    protective_order_prices_fn,
    bars_timestamp_now_fn,
    should_skip_duplicate: Callable[[object], bool] | None = None,
):
    magic_number = strategy_magic_fn(config.mt5.magic_number, deployment.symbol, strategy.candidate_name)
    positions = client.list_positions(magic_number=magic_number)
    current_quantity = net_quantity(positions)
    comment = strategy.candidate_name[:31]
    now_utc = datetime.now(UTC)
    weekend_entry_block = is_weekend_entry_block_fn(config, now_utc)
    force_weekend_flatten = should_force_weekend_flatten_fn(config, now_utc)

    candidate_action = strategy_action_cls(
        strategy.candidate_name,
        signal_side,
        signal_timestamp,
        confidence,
        current_quantity,
        "hold",
        magic_number,
        regime_label=snapshot.regime_label,
        vol_percentile=snapshot.vol_percentile,
        risk_multiplier=effective_risk_multiplier_fn(snapshot, strategy),
        allocation_fraction=allocation_fraction,
        allocator_score=allocator_score,
        portfolio_weight=strategy_portfolio_weight,
        promotion_tier=strategy.promotion_tier,
        base_allocation_weight=strategy.base_allocation_weight,
        risk_budget_cash=0.0,
        veto_reason="",
        interpreter_reason="",
        interpreter_bias=interpreter_state.directional_bias,
        interpreter_confidence=interpreter_state.confidence,
    )
    if current_quantity != 0.0 and force_weekend_flatten:
        close_side = Side.SELL if current_quantity > 0 else Side.BUY
        candidate_action.intended_action = "force_flatten_weekend"
        if config.execution.live_trading_enabled:
            for position in positions:
                client.send_market_order(
                    OrderRequest(
                        timestamp=bars_timestamp_now_fn(),
                        symbol=deployment.broker_symbol,
                        side=Side.SELL if position.side == Side.BUY else Side.BUY,
                        quantity=position.quantity,
                        reason=f"weekend_flatten_{strategy.candidate_name}",
                        confidence=confidence,
                        metadata={"strategy": strategy.candidate_name, "forced_exit": "weekend_flatten"},
                    ),
                    magic_number=magic_number,
                    comment=comment,
                    position_ticket=position.ticket,
                )
        else:
            candidate_action.intended_action = "dry_run_force_flatten_weekend"
        candidate_action.signal_side = close_side
        return candidate_action

    if signal_side == Side.FLAT:
        if current_quantity != 0.0 and weekend_entry_block:
            candidate_action.intended_action = "weekend_hold_detected"
        return candidate_action

    if current_quantity == 0.0 and weekend_entry_block:
        candidate_action.intended_action = "weekend_entry_blocked"
        return candidate_action

    interpreter_reason = interpreter_block_reason_fn(
        strategy,
        interpreter_state,
        relax_for_mini_trades=relax_gates_for_mini_trades,
    )
    if current_quantity == 0.0 and interpreter_reason:
        candidate_action.intended_action = f"policy_blocked::{interpreter_reason}"
        candidate_action.interpreter_reason = interpreter_reason
        return candidate_action

    if current_quantity == 0.0 and is_strategy_regime_blocked_fn(
        deployment,
        strategy,
        snapshot,
        relax_for_mini_trades=relax_gates_for_mini_trades,
    ):
        candidate_action.intended_action = f"regime_blocked::{snapshot.regime_label}"
        return candidate_action

    desired_side = signal_side
    strategy_config = build_strategy_config_fn(strategy)
    market_snapshot = client.market_snapshot()
    reference_price = market_snapshot.ask if desired_side == Side.BUY else market_snapshot.bid
    order_size, effective_size_factor, risk_budget_cash, _stop_distance, _risk_pct = compute_order_size_fn(
        strategy_config,
        relax_gates_for_mini_trades=relax_gates_for_mini_trades,
        allocation_fraction=allocation_fraction,
        risk_multiplier=candidate_action.risk_multiplier,
        portfolio_weight=candidate_action.portfolio_weight,
        account_equity=account_equity,
        latest_feature=latest_feature,
        reference_price=reference_price,
    )
    candidate_action.effective_size_factor = effective_size_factor
    candidate_action.risk_budget_cash = risk_budget_cash
    stop_loss_price, take_profit_price = protective_order_prices_fn(
        strategy_config,
        latest_feature,
        reference_price,
        desired_side,
    )

    if order_size <= 0.0:
        candidate_action.intended_action = "skip_zero_size"
        return candidate_action

    if current_quantity > 0 and desired_side == Side.BUY:
        candidate_action.intended_action = "hold_long"
        return candidate_action
    if current_quantity < 0 and desired_side == Side.SELL:
        candidate_action.intended_action = "hold_short"
        return candidate_action

    action_label = "open_long" if desired_side == Side.BUY else "open_short"
    candidate_action.intended_action = action_label
    if should_skip_duplicate is not None and should_skip_duplicate(candidate_action):
        candidate_action.intended_action = f"duplicate_skipped::{action_label}"
        return candidate_action

    for position in positions:
        if (position.side == Side.BUY and desired_side == Side.SELL) or (position.side == Side.SELL and desired_side == Side.BUY):
            if config.execution.live_trading_enabled:
                client.send_market_order(
                    OrderRequest(
                        timestamp=bars_timestamp_now_fn(),
                        symbol=deployment.broker_symbol,
                        side=Side.SELL if position.side == Side.BUY else Side.BUY,
                        quantity=position.quantity,
                        reason=f"close_{strategy.candidate_name}",
                        confidence=confidence,
                    ),
                    magic_number=magic_number,
                    comment=comment,
                    position_ticket=position.ticket,
                )

    if config.execution.live_trading_enabled:
        client.send_market_order(
            OrderRequest(
                timestamp=bars_timestamp_now_fn(),
                symbol=deployment.broker_symbol,
                side=desired_side,
                quantity=order_size,
                reason=strategy.candidate_name,
                confidence=confidence,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                metadata={"strategy": strategy.candidate_name},
            ),
            magic_number=magic_number,
            comment=comment,
        )
    else:
        candidate_action.intended_action = f"dry_run_{action_label}"
    return candidate_action
