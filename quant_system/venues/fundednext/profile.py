from __future__ import annotations

from quant_system.venues.fundednext.costs import FUNDEDNEXT_COSTS
from quant_system.venues.fundednext.rules import FUNDEDNEXT_RULES
from quant_system.venues.models import VenueProfile


FUNDEDNEXT_VENUE = VenueProfile(
    key="fundednext",
    display_name="FundedNext",
    rules=FUNDEDNEXT_RULES,
    costs=FUNDEDNEXT_COSTS,
)
