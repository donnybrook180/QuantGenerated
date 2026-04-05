from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from quant_system.config import RiskConfig
from quant_system.models import OrderRequest, PortfolioSnapshot


@dataclass(slots=True)
class RiskManager:
    config: RiskConfig
    starting_equity: float
    peak_equity: float | None = None
    current_day: date | None = None
    day_start_equity: float | None = None
    locked_until: object = None

    def check_order(self, order: OrderRequest, snapshot: PortfolioSnapshot) -> bool:
        if self.locked_until and snapshot.timestamp < self.locked_until:
            return False
        if abs(order.quantity) > self.config.max_position_size:
            return False
        if snapshot.equity <= self.starting_equity * self.config.min_equity_buffer_pct:
            return False
        if self.day_start_equity is not None:
            daily_floor = self.day_start_equity * (1.0 - self.config.max_daily_loss_pct)
            if snapshot.equity <= daily_floor:
                return False
        total_floor = self.starting_equity * (1.0 - self.config.max_total_drawdown_pct)
        if snapshot.equity <= total_floor:
            return False
        return True

    def on_snapshot(self, snapshot: PortfolioSnapshot) -> bool:
        snapshot_day = snapshot.timestamp.date()
        if self.current_day != snapshot_day:
            self.current_day = snapshot_day
            self.day_start_equity = snapshot.equity
        self.peak_equity = max(self.peak_equity or snapshot.equity, snapshot.equity)

        if self.day_start_equity is None:
            self.day_start_equity = snapshot.equity

        daily_pnl_pct = (snapshot.equity / self.day_start_equity) - 1.0
        total_pnl_pct = (snapshot.equity / self.starting_equity) - 1.0
        if daily_pnl_pct <= -self.config.max_daily_loss_pct or total_pnl_pct <= -self.config.max_total_drawdown_pct:
            self.locked_until = snapshot.timestamp + timedelta(hours=self.config.cooldown_hours)
            return True
        return False
