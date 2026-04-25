from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VenueRules:
    fill_resolution_routes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VenueCostSpec:
    metals_slippage_bps: float = 0.8
    metals_commission_notional_pct: float = 0.0007
    btc_slippage_bps: float = 1.5
    eth_slippage_bps: float = 4.0
    index_slippage_bps: float = 0.5
    forex_slippage_bps: float = 0.25
    forex_commission_per_lot: float = 2.5


@dataclass(frozen=True, slots=True)
class VenueProfile:
    key: str
    display_name: str
    rules: VenueRules
    costs: VenueCostSpec

