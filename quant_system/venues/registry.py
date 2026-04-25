from __future__ import annotations

from quant_system.venues.blue_guardian import BLUE_GUARDIAN_VENUE
from quant_system.venues.ftmo import FTMO_VENUE
from quant_system.venues.fundednext import FUNDEDNEXT_VENUE
from quant_system.venues.generic import GENERIC_VENUE
from quant_system.venues.models import VenueProfile


_VENUES: dict[str, VenueProfile] = {
    GENERIC_VENUE.key: GENERIC_VENUE,
    FTMO_VENUE.key: FTMO_VENUE,
    FUNDEDNEXT_VENUE.key: FUNDEDNEXT_VENUE,
    BLUE_GUARDIAN_VENUE.key: BLUE_GUARDIAN_VENUE,
}

_VENUE_ALIASES: dict[str, str] = {
    "generic": "generic",
    "ftmo": "ftmo",
    "fundednext": "fundednext",
    "blue_guardian": "blue_guardian",
    "blueguardian": "blue_guardian",
    "blue guardian": "blue_guardian",
}


def normalize_venue_key(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return "generic"
    return _VENUE_ALIASES.get(raw, raw.replace("-", "_").replace(" ", "_"))


def infer_venue_key(*, server: str | None = None, company: str | None = None, explicit: str | None = None) -> str:
    normalized_explicit = normalize_venue_key(explicit)
    if normalized_explicit != "generic":
        return normalized_explicit
    joined = f"{server or ''} {company or ''}".strip().lower()
    if "ftmo" in joined:
        return "ftmo"
    if "fundednext" in joined:
        return "fundednext"
    if "blue guardian" in joined or "blueguardian" in joined:
        return "blue_guardian"
    return "generic"


def get_venue_profile(key: str | None) -> VenueProfile:
    normalized = normalize_venue_key(key)
    return _VENUES.get(normalized, GENERIC_VENUE)


def resolve_venue_profile(key: str | None) -> VenueProfile:
    return get_venue_profile(key)
