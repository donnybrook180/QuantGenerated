from __future__ import annotations

from quant_system.venues.models import VenueRules


GENERIC_RULES = VenueRules(
    fill_resolution_routes=("history_deals", "history_orders", "open_position"),
    daily_drawdown_limit_pct=None,
    total_drawdown_limit_pct=None,
    daily_drawdown_limit_mode="relative_to_reference",
    total_drawdown_limit_mode="relative_to_reference",
    daily_drawdown_reference="day_start_equity",
    total_drawdown_reference="starting_equity",
)
