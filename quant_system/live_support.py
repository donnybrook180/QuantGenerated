from __future__ import annotations

import logging

from quant_system.config import SystemConfig
from quant_system.costs import apply_ftmo_cost_profile
from quant_system.integrations.stock_events import fetch_stock_event_flags
from quant_system.models import FeatureVector, MarketBar
from quant_system.research.cross_asset import apply_cross_asset_context, supports_cross_asset_context
from quant_system.research.features import build_feature_library
from quant_system.symbols import is_stock_symbol


LOGGER = logging.getLogger(__name__)


def configure_symbol_execution(config: SystemConfig, symbol: str, broker_symbol: str | None = None) -> None:
    upper = symbol.upper()
    if "XAU" in upper:
        config.execution.min_bars_between_trades = 30
        config.execution.max_holding_bars = 18
        config.execution.stop_loss_atr_multiple = 1.4
        config.execution.take_profit_atr_multiple = 2.4
        config.execution.break_even_atr_multiple = 0.45
        config.execution.trailing_stop_atr_multiple = 0.85
        config.execution.stale_breakout_bars = 6
        config.execution.stale_breakout_atr_fraction = 0.2
        config.execution.structure_exit_bars = 4
    elif "BTC" in upper or "ETH" in upper:
        config.execution.min_bars_between_trades = 18
        config.execution.max_holding_bars = 30
        config.execution.stop_loss_atr_multiple = 1.6
        config.execution.take_profit_atr_multiple = 3.0
        config.execution.break_even_atr_multiple = 0.7
        config.execution.trailing_stop_atr_multiple = 1.1
        config.execution.stale_breakout_bars = 8
        config.execution.stale_breakout_atr_fraction = 0.18
        config.execution.structure_exit_bars = 5
    elif upper.endswith("USD") or upper.endswith("JPY") or upper.startswith("EUR") or upper.startswith("GBP") or upper.startswith("AUD"):
        config.execution.min_bars_between_trades = 10
        config.execution.max_holding_bars = 26
        config.execution.stop_loss_atr_multiple = 1.1
        config.execution.take_profit_atr_multiple = 2.1
        config.execution.break_even_atr_multiple = 0.6
        config.execution.trailing_stop_atr_multiple = 0.8
        config.execution.stale_breakout_bars = 6
        config.execution.stale_breakout_atr_fraction = 0.12
        config.execution.structure_exit_bars = 4
    elif is_stock_symbol(symbol):
        config.execution.min_bars_between_trades = 10
        config.execution.max_holding_bars = 18
        config.execution.stop_loss_atr_multiple = 1.25
        config.execution.take_profit_atr_multiple = 2.5
        config.execution.break_even_atr_multiple = 0.8
        config.execution.trailing_stop_atr_multiple = 0.95
        config.execution.stale_breakout_bars = 5
        config.execution.stale_breakout_atr_fraction = 0.12
        config.execution.structure_exit_bars = 3
    else:
        config.execution.min_bars_between_trades = 12
        config.execution.max_holding_bars = 24
        config.execution.stop_loss_atr_multiple = 1.2
        config.execution.take_profit_atr_multiple = 2.4
        config.execution.break_even_atr_multiple = 0.8
        config.execution.trailing_stop_atr_multiple = 1.0
        config.execution.stale_breakout_bars = 5
        config.execution.stale_breakout_atr_fraction = 0.1
        config.execution.structure_exit_bars = 3
    apply_ftmo_cost_profile(config, symbol, broker_symbol)


def build_features_with_events(config: SystemConfig, data_symbol: str, bars: list[MarketBar]) -> list[FeatureVector]:
    if not bars:
        return []
    if not is_stock_symbol(data_symbol):
        features = build_feature_library(bars)
        if supports_cross_asset_context(data_symbol):
            multiplier, timespan = _infer_bars_timeframe(bars)
            features = apply_cross_asset_context(
                features,
                config.mt5.database_path,
                data_symbol,
                multiplier,
                timespan,
            )
        return features
    try:
        event_flags = fetch_stock_event_flags(
            data_symbol,
            start_day=bars[0].timestamp.date(),
            end_day=bars[-1].timestamp.date(),
        )
        features = build_feature_library(bars, event_flags)
    except RuntimeError as exc:
        LOGGER.warning("Stock event enrichment failed for %s; continuing without event flags: %s", data_symbol, exc)
        features = build_feature_library(bars)
    if supports_cross_asset_context(data_symbol):
        multiplier, timespan = _infer_bars_timeframe(bars)
        features = apply_cross_asset_context(
            features,
            config.mt5.database_path,
            data_symbol,
            multiplier,
            timespan,
        )
    return features


def _infer_bars_timeframe(bars: list[MarketBar]) -> tuple[int, str]:
    if len(bars) < 2:
        return 5, "minute"
    delta_seconds = int((bars[1].timestamp - bars[0].timestamp).total_seconds())
    if delta_seconds <= 0:
        return 5, "minute"
    return max(delta_seconds // 60, 1), "minute"
