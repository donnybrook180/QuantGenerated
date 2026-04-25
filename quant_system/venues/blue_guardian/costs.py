from __future__ import annotations

from quant_system.venues.models import VenueCostSpec


BLUE_GUARDIAN_COSTS = VenueCostSpec(
    metals_commission_notional_pct=0.0008,
    index_slippage_bps=0.75,
    forex_commission_per_lot=3.0,
)
