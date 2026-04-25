from __future__ import annotations

from types import SimpleNamespace

from quant_system.config import SystemConfig
from quant_system.live.order_sizing import compute_order_size, protective_order_prices
from quant_system.models import Side


def test_protective_order_prices_builds_buy_bracket() -> None:
    config = SystemConfig()
    feature = SimpleNamespace(values={"atr_proxy": 0.01})
    stop_price, target_price = protective_order_prices(config, feature, 100.0, Side.BUY)
    assert stop_price < 100.0
    assert target_price > 100.0


def test_compute_order_size_returns_positive_size_for_valid_stop_distance() -> None:
    config = SystemConfig()
    config.execution.contract_size = 1.0
    config.execution.risk_per_trade_pct = 0.01
    feature = SimpleNamespace(values={"atr_proxy": 0.01})
    order_size, effective_size_factor, risk_budget_cash, stop_distance, _risk_pct = compute_order_size(
        config,
        relax_gates_for_mini_trades=False,
        allocation_fraction=1.0,
        risk_multiplier=1.0,
        portfolio_weight=1.0,
        account_equity=100000.0,
        latest_feature=feature,
        reference_price=100.0,
    )
    assert order_size > 0.0
    assert effective_size_factor == 1.0
    assert risk_budget_cash > 0.0
    assert stop_distance > 0.0
