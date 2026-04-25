from __future__ import annotations

from quant_system.venues.blue_guardian.costs import BLUE_GUARDIAN_COSTS
from quant_system.venues.blue_guardian.rules import BLUE_GUARDIAN_RULES
from quant_system.venues.models import VenueProfile


BLUE_GUARDIAN_VENUE = VenueProfile(
    key="blue_guardian",
    display_name="Blue Guardian",
    rules=BLUE_GUARDIAN_RULES,
    costs=BLUE_GUARDIAN_COSTS,
)
