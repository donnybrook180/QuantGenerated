from __future__ import annotations

from quant_system.config import SystemConfig
from quant_system.models import Side


def estimated_stop_distance(strategy_config: SystemConfig, latest_feature, reference_price: float) -> float:
    if latest_feature is None:
        return 0.0
    atr_proxy = float(latest_feature.values.get("atr_proxy", 0.0) or 0.0)
    stop_multiple = float(strategy_config.execution.stop_loss_atr_multiple or 0.0)
    if atr_proxy <= 0.0 or stop_multiple <= 0.0 or reference_price <= 0.0:
        return 0.0
    return reference_price * atr_proxy * stop_multiple


def protective_order_prices(
    strategy_config: SystemConfig,
    latest_feature,
    reference_price: float,
    side: Side,
) -> tuple[float, float]:
    if latest_feature is None or reference_price <= 0.0:
        return 0.0, 0.0
    atr_proxy = float(latest_feature.values.get("atr_proxy", 0.0) or 0.0)
    if atr_proxy <= 0.0:
        return 0.0, 0.0
    stop_distance = reference_price * atr_proxy * float(strategy_config.execution.stop_loss_atr_multiple or 0.0)
    target_distance = reference_price * atr_proxy * float(strategy_config.execution.take_profit_atr_multiple or 0.0)
    if side == Side.BUY:
        stop_price = reference_price - stop_distance if stop_distance > 0.0 else 0.0
        target_price = reference_price + target_distance if target_distance > 0.0 else 0.0
    else:
        stop_price = reference_price + stop_distance if stop_distance > 0.0 else 0.0
        target_price = reference_price - target_distance if target_distance > 0.0 else 0.0
    return stop_price, target_price


def compute_order_size(
    strategy_config: SystemConfig,
    *,
    relax_gates_for_mini_trades: bool,
    allocation_fraction: float,
    risk_multiplier: float,
    portfolio_weight: float,
    account_equity: float,
    latest_feature,
    reference_price: float,
) -> tuple[float, float, float, float, float]:
    effective_size_factor = portfolio_weight * allocation_fraction * risk_multiplier
    risk_pct = strategy_config.execution.risk_per_trade_pct
    if relax_gates_for_mini_trades:
        risk_pct = min(risk_pct, strategy_config.execution.mini_trades_risk_per_trade_pct)
    risk_budget_cash = account_equity * max(risk_pct, 0.0) * effective_size_factor
    stop_distance = estimated_stop_distance(strategy_config, latest_feature, reference_price)
    order_size = 0.0
    if risk_budget_cash > 0.0 and stop_distance > 0.0 and strategy_config.execution.contract_size > 0.0:
        order_size = risk_budget_cash / (stop_distance * strategy_config.execution.contract_size)
        if relax_gates_for_mini_trades:
            order_size = min(order_size, strategy_config.execution.mini_trades_order_size)
    else:
        order_size = strategy_config.execution.order_size * effective_size_factor
    return order_size, effective_size_factor, risk_budget_cash, stop_distance, risk_pct
