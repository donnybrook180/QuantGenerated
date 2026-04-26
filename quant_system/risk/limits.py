from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from quant_system.config import RiskConfig
from quant_system.models import OrderRequest, PortfolioSnapshot
from quant_system.venues import get_venue_profile
from quant_system.venues.models import VenueRules


@dataclass(slots=True)
class RiskManager:
    config: RiskConfig
    starting_equity: float
    venue_key: str = "generic"
    venue_rules: VenueRules | None = None
    peak_equity: float | None = None
    peak_balance: float | None = None
    current_day: date | None = None
    day_start_equity: float | None = None
    day_start_balance: float | None = None
    locked_until: object = None
    last_breach_reason: str = ""

    def __post_init__(self) -> None:
        if self.venue_rules is None:
            self.venue_rules = get_venue_profile(self.venue_key).rules

    def _risk_day(self, snapshot: PortfolioSnapshot) -> date:
        timezone_name = self.venue_rules.daily_reset_timezone if self.venue_rules is not None else "UTC"
        reset_hour = int(self.venue_rules.daily_reset_hour if self.venue_rules is not None else 0)
        localized = snapshot.timestamp.astimezone(ZoneInfo(timezone_name))
        return (localized - timedelta(hours=reset_hour)).date()

    def _resolve_reference_value(self, snapshot: PortfolioSnapshot, reference: str) -> float:
        normalized = str(reference or "").strip().lower()
        if normalized == "starting_balance":
            return self.starting_equity
        if normalized == "starting_equity":
            return self.starting_equity
        if normalized == "day_start_balance":
            return float(self.day_start_balance if self.day_start_balance is not None else snapshot.cash)
        if normalized == "day_start_equity":
            return float(self.day_start_equity if self.day_start_equity is not None else snapshot.equity)
        if normalized == "day_start_highest_balance_or_equity":
            return max(
                float(self.day_start_balance if self.day_start_balance is not None else snapshot.cash),
                float(self.day_start_equity if self.day_start_equity is not None else snapshot.equity),
            )
        if normalized == "peak_balance":
            return float(self.peak_balance if self.peak_balance is not None else max(self.starting_equity, snapshot.cash))
        if normalized in {"peak_equity", "trailing_peak_equity"}:
            return float(self.peak_equity if self.peak_equity is not None else max(self.starting_equity, snapshot.equity))
        return snapshot.equity

    def _daily_limit_pct(self) -> float | None:
        if self.venue_rules is not None and self.venue_rules.daily_drawdown_limit_pct is not None:
            return float(self.venue_rules.daily_drawdown_limit_pct)
        return float(self.config.max_daily_loss_pct)

    def _total_limit_pct(self) -> float | None:
        if self.venue_rules is not None and self.venue_rules.total_drawdown_limit_pct is not None:
            return float(self.venue_rules.total_drawdown_limit_pct)
        return float(self.config.max_total_drawdown_pct)

    def _drawdown_floor(self, *, reference_value: float, limit_pct: float, mode: str) -> float:
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode == "fixed_from_starting_balance":
            return reference_value - (self.starting_equity * limit_pct)
        return reference_value * (1.0 - limit_pct)

    def _drawdown_breach_reason(self, snapshot: PortfolioSnapshot) -> str:
        daily_limit_pct = self._daily_limit_pct()
        if daily_limit_pct is not None:
            daily_reference = self._resolve_reference_value(
                snapshot,
                self.venue_rules.daily_drawdown_reference if self.venue_rules is not None else "day_start_equity",
            )
            daily_floor = self._drawdown_floor(
                reference_value=daily_reference,
                limit_pct=daily_limit_pct,
                mode=self.venue_rules.daily_drawdown_limit_mode if self.venue_rules is not None else "relative_to_reference",
            )
            if snapshot.equity <= daily_floor:
                return (
                    f"daily_drawdown_breached: equity={snapshot.equity:.2f} "
                    f"floor={daily_floor:.2f} ref={daily_reference:.2f}"
                )
        total_limit_pct = self._total_limit_pct()
        if total_limit_pct is not None:
            total_reference = self._resolve_reference_value(
                snapshot,
                self.venue_rules.total_drawdown_reference if self.venue_rules is not None else "starting_equity",
            )
            total_floor = self._drawdown_floor(
                reference_value=total_reference,
                limit_pct=total_limit_pct,
                mode=self.venue_rules.total_drawdown_limit_mode if self.venue_rules is not None else "relative_to_reference",
            )
            if snapshot.equity <= total_floor:
                return (
                    f"total_drawdown_breached: equity={snapshot.equity:.2f} "
                    f"floor={total_floor:.2f} ref={total_reference:.2f}"
                )
        return ""

    def check_order(self, order: OrderRequest, snapshot: PortfolioSnapshot) -> bool:
        if self.locked_until and snapshot.timestamp < self.locked_until:
            return False
        if abs(order.quantity) > self.config.max_position_size:
            return False
        if snapshot.equity <= self.starting_equity * self.config.min_equity_buffer_pct:
            return False
        if self._drawdown_breach_reason(snapshot):
            return False
        return True

    def on_snapshot(self, snapshot: PortfolioSnapshot) -> bool:
        snapshot_day = self._risk_day(snapshot)
        if self.current_day != snapshot_day:
            self.current_day = snapshot_day
            self.day_start_equity = snapshot.equity
            self.day_start_balance = snapshot.cash
        self.peak_equity = max(self.peak_equity or snapshot.equity, snapshot.equity)
        self.peak_balance = max(self.peak_balance or snapshot.cash, snapshot.cash)

        if self.day_start_equity is None:
            self.day_start_equity = snapshot.equity
        if self.day_start_balance is None:
            self.day_start_balance = snapshot.cash

        breach_reason = self._drawdown_breach_reason(snapshot)
        if breach_reason:
            self.last_breach_reason = breach_reason
            self.locked_until = snapshot.timestamp + timedelta(hours=self.config.cooldown_hours)
            return True
        return False
