from __future__ import annotations

import copy
import logging

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
