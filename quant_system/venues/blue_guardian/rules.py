from __future__ import annotations

from quant_system.venues.models import VenueRules


BLUE_GUARDIAN_RULES = VenueRules(
    fill_resolution_routes=("history_deals", "open_position", "history_orders"),
)
