from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VenueRules:
    fill_resolution_routes: tuple[str, ...]
    daily_drawdown_limit_pct: float | None = None
    total_drawdown_limit_pct: float | None = None
    daily_drawdown_limit_mode: str = "relative_to_reference"
    total_drawdown_limit_mode: str = "relative_to_reference"
    daily_drawdown_reference: str = "day_start_equity"
    total_drawdown_reference: str = "starting_equity"
    daily_reset_timezone: str = "UTC"
    daily_reset_hour: int = 0
    lockout_mode: str = "cooldown"
    profit_target_pct: float | None = None
    min_trading_days: int = 0
    allows_weekend_holds: bool = True


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
