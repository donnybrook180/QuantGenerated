from __future__ import annotations

from quant_system.venues.models import VenueRules


BLUE_GUARDIAN_RULES = VenueRules(
    fill_resolution_routes=("history_deals", "open_position", "history_orders"),
    daily_drawdown_limit_pct=0.04,
    total_drawdown_limit_pct=0.08,
    daily_drawdown_limit_mode="fixed_from_starting_balance",
    total_drawdown_limit_mode="relative_to_reference",
    daily_drawdown_reference="day_start_highest_balance_or_equity",
    total_drawdown_reference="starting_balance",
    daily_reset_timezone="America/New_York",
    daily_reset_hour=17,
    profit_target_pct=0.08,
    min_trading_days=5,
)
