from __future__ import annotations

from quant_system.venues.models import VenueCostSpec


FUNDEDNEXT_COSTS = VenueCostSpec(
    metals_slippage_bps=1.0,
    btc_slippage_bps=2.0,
    eth_slippage_bps=4.5,
    forex_slippage_bps=0.35,
)
