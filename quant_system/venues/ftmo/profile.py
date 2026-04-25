from __future__ import annotations

from quant_system.venues.ftmo.costs import FTMO_COSTS
from quant_system.venues.ftmo.rules import FTMO_RULES
from quant_system.venues.models import VenueProfile


FTMO_VENUE = VenueProfile(
    key="ftmo",
    display_name="FTMO",
    rules=FTMO_RULES,
    costs=FTMO_COSTS,
)
