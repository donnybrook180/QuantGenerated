from __future__ import annotations

from quant_system.venues.generic.costs import GENERIC_COSTS
from quant_system.venues.generic.rules import GENERIC_RULES
from quant_system.venues.models import VenueProfile


GENERIC_VENUE = VenueProfile(
    key="generic",
    display_name="Generic prop",
    rules=GENERIC_RULES,
    costs=GENERIC_COSTS,
)
