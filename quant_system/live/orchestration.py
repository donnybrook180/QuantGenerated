from __future__ import annotations

from typing import Callable

from quant_system.integrations.mt5 import MT5Client
from quant_system.models import Side


def run_live_cycle(
    *,
    deployment,
    config,
    portfolio_weight: float,
    interpreter_state,
    relax_gates_for_mini_trades: bool,
    strategy_portfolio_weight_fn,
    build_strategy_config_fn,
    evaluate_strategy_fn,
    allocate_symbol_exposure_fn,
    reconcile_strategy_fn,
    net_quantity_fn,
    strategy_magic_fn,
    strategy_action_cls,
    allocator_score_fn,
    effective_risk_multiplier_fn,
    is_strategy_regime_blocked_fn,
    interpreter_block_reason_fn,
    evaluated_strategy_cls,
    live_run_result_cls,
    should_skip_duplicate: Callable | None = None,
):
    actions: list = []
    regime_snapshot = None
    evaluated: list = []
    client_cache: dict[str, MT5Client] = {}
    strategy_clients: dict[str, MT5Client] = {}

    def client_for_strategy(strategy):
        strategy_config = build_strategy_config_fn(strategy)
        cache_key = f"{strategy_config.mt5.symbol}|{strategy_config.mt5.timeframe}"
        client = client_cache.get(cache_key)
        if client is None:
            client = MT5Client(strategy_config.mt5)
            client.initialize()
            client_cache[cache_key] = client
        strategy_clients[strategy.candidate_name] = client
        return client

    try:
        bootstrap_client = client_for_strategy(deployment.strategies[0])
        account_mode_info = bootstrap_client.account_mode_info()
        account_snapshot = bootstrap_client.account_snapshot()
        if (
            account_mode_info is not None
            and not account_mode_info.strategy_isolation_supported
            and len(deployment.strategies) > 1
            and not config.mt5.allow_netting_multi_strategy
        ):
            for strategy in deployment.strategies:
                magic_number = strategy_magic_fn(config.mt5.magic_number, deployment.symbol, strategy.candidate_name)
                actions.append(
                    strategy_action_cls(
                        candidate_name=strategy.candidate_name,
                        signal_side=Side.FLAT,
                        signal_timestamp=None,
                        confidence=0.0,
                        current_quantity=0.0,
                        intended_action="netting_blocked_multi_strategy",
                        magic_number=magic_number,
                        regime_label="",
                        vol_percentile=0.0,
                        risk_multiplier=0.0,
                        allocation_fraction=0.0,
                        allocator_score=0.0,
                        portfolio_weight=strategy_portfolio_weight_fn(strategy),
                    )
                )
            return live_run_result_cls(
                symbol=deployment.symbol,
                broker_symbol=deployment.broker_symbol,
                account_mode_label=account_mode_info.margin_mode_label,
                strategy_isolation_supported=account_mode_info.strategy_isolation_supported,
                actions=actions,
                regime_snapshot=regime_snapshot,
                portfolio_weight=portfolio_weight,
            )

        for strategy in deployment.strategies:
            client = client_for_strategy(strategy)
            signal_side, confidence, signal_timestamp, snapshot, veto_reason, latest_feature = evaluate_strategy_fn(client, strategy)
            if interpreter_state.regime_snapshot is not None:
                snapshot = interpreter_state.regime_snapshot
            if regime_snapshot is None:
                regime_snapshot = snapshot
            interpreter_reason = interpreter_block_reason_fn(
                strategy,
                interpreter_state,
                relax_for_mini_trades=relax_gates_for_mini_trades,
            )
            blocked = is_strategy_regime_blocked_fn(
                deployment,
                strategy,
                snapshot,
                relax_for_mini_trades=relax_gates_for_mini_trades,
            ) or bool(interpreter_reason)
            score = 0.0 if blocked else allocator_score_fn(strategy, signal_side, confidence, snapshot)
            evaluated.append(
                evaluated_strategy_cls(
                    strategy=strategy,
                    signal_side=signal_side,
                    signal_timestamp=signal_timestamp,
                    confidence=confidence,
                    snapshot=snapshot,
                    allocator_score=score,
                    veto_reason=interpreter_reason or veto_reason,
                    latest_feature=latest_feature,
                )
            )

        allocate_symbol_exposure_fn(evaluated)

        for item in evaluated:
            client = strategy_clients[item.strategy.candidate_name]
            if item.signal_side != Side.FLAT and item.allocator_score > 0.0 and item.allocation_fraction <= 0.0:
                magic_number = strategy_magic_fn(config.mt5.magic_number, deployment.symbol, item.strategy.candidate_name)
                current_quantity = net_quantity_fn(client.list_positions(magic_number=magic_number))
                actions.append(
                    strategy_action_cls(
                        candidate_name=item.strategy.candidate_name,
                        signal_side=item.signal_side,
                        signal_timestamp=item.signal_timestamp,
                        confidence=item.confidence,
                        current_quantity=current_quantity,
                        intended_action="allocator_blocked_opposing_side",
                        magic_number=magic_number,
                        regime_label=item.snapshot.regime_label,
                        vol_percentile=item.snapshot.vol_percentile,
                        risk_multiplier=effective_risk_multiplier_fn(item.snapshot, item.strategy),
                        allocation_fraction=0.0,
                        allocator_score=item.allocator_score,
                        portfolio_weight=portfolio_weight,
                        promotion_tier=item.strategy.promotion_tier,
                        base_allocation_weight=item.strategy.base_allocation_weight,
                        effective_size_factor=0.0,
                        risk_budget_cash=0.0,
                        veto_reason=item.veto_reason,
                        interpreter_reason=interpreter_block_reason_fn(item.strategy, interpreter_state),
                        interpreter_bias=interpreter_state.directional_bias,
                        interpreter_confidence=interpreter_state.confidence,
                    )
                )
                continue
            action = reconcile_strategy_fn(
                client,
                item.strategy,
                item.signal_side,
                item.signal_timestamp,
                item.confidence,
                item.snapshot,
                item.allocation_fraction if item.allocation_fraction > 0.0 else item.strategy.allocation_weight,
                item.allocator_score,
                account_snapshot.equity,
                item.latest_feature,
                should_skip_duplicate,
            )
            action.veto_reason = item.veto_reason
            if not action.interpreter_reason:
                action.interpreter_reason = interpreter_block_reason_fn(
                    item.strategy,
                    interpreter_state,
                    relax_for_mini_trades=relax_gates_for_mini_trades,
                )
            action.interpreter_bias = interpreter_state.directional_bias
            action.interpreter_confidence = interpreter_state.confidence
            actions.append(action)
        return live_run_result_cls(
            symbol=deployment.symbol,
            broker_symbol=deployment.broker_symbol,
            account_mode_label=account_mode_info.margin_mode_label if account_mode_info is not None else "unknown",
            strategy_isolation_supported=account_mode_info.strategy_isolation_supported if account_mode_info is not None else False,
            actions=actions,
            regime_snapshot=regime_snapshot,
            portfolio_weight=portfolio_weight,
            interpreter_state=interpreter_state,
        )
    finally:
        for client in client_cache.values():
            try:
                client.shutdown()
            except Exception:
                pass
