from __future__ import annotations

from quant_system.venues.models import VenueRules


GENERIC_RULES = VenueRules(
    fill_resolution_routes=("history_deals", "history_orders", "open_position"),
)
