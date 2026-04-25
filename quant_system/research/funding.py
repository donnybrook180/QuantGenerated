from __future__ import annotations

import copy
import logging
from statistics import median

from quant_system.config import SystemConfig
from quant_system.integrations.mt5 import MT5Client, MT5Error
from quant_system.models import FeatureVector


LOGGER = logging.getLogger(__name__)


def empty_broker_funding_context() -> dict[str, float]:
    return {
        "broker_swap_available": 0.0,
        "broker_swap_long": 0.0,
        "broker_swap_short": 0.0,
        "broker_swap_rollover3days": 0.0,
        "broker_contract_size": 0.0,
        "broker_point": 0.0,
        "broker_positive_carry_long": 0.0,
        "broker_positive_carry_short": 0.0,
        "broker_preferred_carry_side": 0.0,
        "broker_carry_spread": 0.0,
        "broker_funding_rate": 0.0,
    }


def load_broker_funding_context(
    config: SystemConfig,
    symbol: str,
    broker_symbol: str | None = None,
) -> dict[str, float]:
    target_symbol = (broker_symbol or config.mt5.symbol or symbol).strip()
    if not target_symbol:
        return empty_broker_funding_context()

    mt5_config = copy.deepcopy(config.mt5)
    mt5_config.symbol = target_symbol
    client = MT5Client(mt5_config)
    try:
        client.initialize()
        funding = client.funding_info()
    except MT5Error as exc:
        LOGGER.warning("Broker funding context unavailable for %s: %s", target_symbol, exc)
        return empty_broker_funding_context()
    finally:
        try:
            client.shutdown()
        except Exception:
            pass

    preferred_side = 0.0
    if funding.swap_long > funding.swap_short and funding.swap_long > 0.0:
        preferred_side = 1.0
    elif funding.swap_short > funding.swap_long and funding.swap_short > 0.0:
        preferred_side = -1.0

    return {
        "broker_swap_available": 1.0,
        "broker_swap_long": funding.swap_long,
        "broker_swap_short": funding.swap_short,
        "broker_swap_rollover3days": float(funding.swap_rollover3days),
        "broker_contract_size": funding.contract_size,
        "broker_point": funding.point,
        "broker_positive_carry_long": 1.0 if funding.swap_long > 0.0 else 0.0,
        "broker_positive_carry_short": 1.0 if funding.swap_short > 0.0 else 0.0,
        "broker_preferred_carry_side": preferred_side,
        "broker_carry_spread": funding.swap_long - funding.swap_short,
        "broker_funding_rate": 0.0,
    }


def apply_broker_funding_context(features: list[FeatureVector], funding_context: dict[str, float] | None) -> list[FeatureVector]:
    context = dict(empty_broker_funding_context())
    if funding_context:
        context.update({key: float(value) for key, value in funding_context.items()})
    enriched: list[FeatureVector] = []
    for feature in features:
        values = dict(feature.values)
        values.update(context)
        enriched.append(FeatureVector(timestamp=feature.timestamp, symbol=feature.symbol, values=values))
    return enriched


def infer_feature_bar_hours(features: list[FeatureVector]) -> float:
    if len(features) < 2:
        return 0.0
    deltas = [
        (features[index].timestamp - features[index - 1].timestamp).total_seconds() / 3600.0
        for index in range(1, len(features))
        if features[index].timestamp > features[index - 1].timestamp
    ]
    if not deltas:
        return 0.0
    return max(0.0, float(median(deltas)))


def estimate_swap_drag(
    *,
    avg_hold_bars: float,
    closed_trades: int,
    expectancy: float,
    direction_mode: str,
    broker_swap_long: float,
    broker_swap_short: float,
    broker_preferred_carry_side: str,
    bar_hours: float,
) -> dict[str, float | str]:
    avg_hold_hours = max(0.0, avg_hold_bars) * max(0.0, bar_hours)
    hold_days = avg_hold_hours / 24.0 if avg_hold_hours > 0.0 else 0.0
    carry_preferred_side = broker_preferred_carry_side or "none"
    if direction_mode == "long_only":
        selected_swap = broker_swap_long
        applied_side = "long"
    elif direction_mode == "short_only":
        selected_swap = broker_swap_short
        applied_side = "short"
    elif carry_preferred_side == "long":
        selected_swap = broker_swap_long
        applied_side = "long"
    elif carry_preferred_side == "short":
        selected_swap = broker_swap_short
        applied_side = "short"
    else:
        selected_swap = min(broker_swap_long, broker_swap_short)
        applied_side = "worst_case"
    estimated_swap_drag_per_trade = abs(selected_swap) * hold_days if selected_swap < 0.0 else 0.0
    estimated_swap_drag_total = estimated_swap_drag_per_trade * max(closed_trades, 0)
    swap_adjusted_expectancy = expectancy - estimated_swap_drag_per_trade
    return {
        "avg_hold_hours": avg_hold_hours,
        "estimated_swap_drag_per_trade": estimated_swap_drag_per_trade,
        "estimated_swap_drag_total": estimated_swap_drag_total,
        "swap_adjusted_expectancy": swap_adjusted_expectancy,
        "carry_preferred_side": carry_preferred_side,
        "swap_applied_side": applied_side,
    }
