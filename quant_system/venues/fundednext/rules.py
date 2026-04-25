from __future__ import annotations

from quant_system.venues.models import VenueRules


FUNDEDNEXT_RULES = VenueRules(
    fill_resolution_routes=("history_deals", "open_position", "history_orders"),
)
