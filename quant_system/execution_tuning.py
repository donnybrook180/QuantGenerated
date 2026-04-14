from __future__ import annotations

from quant_system.config import SystemConfig


def apply_execution_mode_overrides(config: SystemConfig) -> None:
    if not config.execution.mini_trades_enabled:
        return
    config.execution.order_size = min(
        config.execution.order_size,
        config.execution.mini_trades_order_size,
    )
    config.execution.risk_per_trade_pct = min(
        config.execution.risk_per_trade_pct,
        config.execution.mini_trades_risk_per_trade_pct,
    )
    config.execution.min_bars_between_trades = min(
        config.execution.min_bars_between_trades,
        config.execution.mini_trades_min_bars_between_trades,
    )
    if config.execution.max_holding_bars <= 0:
        config.execution.max_holding_bars = config.execution.mini_trades_max_holding_bars
    else:
        config.execution.max_holding_bars = min(
            config.execution.max_holding_bars,
            config.execution.mini_trades_max_holding_bars,
        )
    config.execution.take_profit_atr_multiple = min(
        config.execution.take_profit_atr_multiple,
        config.execution.mini_trades_take_profit_atr_multiple,
    )
    config.execution.break_even_atr_multiple = min(
        config.execution.break_even_atr_multiple,
        config.execution.mini_trades_break_even_atr_multiple,
    )
    config.execution.trailing_stop_atr_multiple = min(
        config.execution.trailing_stop_atr_multiple,
        config.execution.mini_trades_trailing_stop_atr_multiple,
    )
    config.execution.stale_breakout_bars = min(
        config.execution.stale_breakout_bars,
        config.execution.mini_trades_stale_breakout_bars,
    )
    config.execution.stale_breakout_atr_fraction = min(
        config.execution.stale_breakout_atr_fraction,
        config.execution.mini_trades_stale_breakout_atr_fraction,
    )
    config.execution.structure_exit_bars = min(
        config.execution.structure_exit_bars,
        config.execution.mini_trades_structure_exit_bars,
    )
