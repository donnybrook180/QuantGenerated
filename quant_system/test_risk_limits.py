from __future__ import annotations

import unittest
from datetime import UTC, datetime

from quant_system.config import RiskConfig
from quant_system.models import OrderRequest, PortfolioSnapshot, Side
from quant_system.risk.limits import RiskManager


def _snapshot(*, timestamp: datetime, balance: float, equity: float) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        timestamp=timestamp,
        cash=balance,
        equity=equity,
        unrealized_pnl=equity - balance,
        realized_pnl=balance - 100_000.0,
        drawdown=max(0.0, (100_000.0 - equity) / 100_000.0),
    )


def _order(timestamp: datetime) -> OrderRequest:
    return OrderRequest(
        timestamp=timestamp,
        symbol="EURUSD",
        side=Side.BUY,
        quantity=0.1,
        reason="test",
    )


class RiskLimitsTests(unittest.TestCase):
    def test_ftmo_daily_drawdown_uses_day_start_balance_minus_fixed_initial_loss(self) -> None:
        manager = RiskManager(config=RiskConfig(), starting_equity=100_000.0, venue_key="ftmo")
        day_start = _snapshot(timestamp=datetime(2026, 1, 1, 0, 5, tzinfo=UTC), balance=102_000.0, equity=102_000.0)
        manager.on_snapshot(day_start)

        within_limit = _snapshot(timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC), balance=102_000.0, equity=97_100.0)
        breached = _snapshot(timestamp=datetime(2026, 1, 1, 12, 5, tzinfo=UTC), balance=102_000.0, equity=96_900.0)

        self.assertFalse(manager.on_snapshot(within_limit))
        self.assertTrue(manager.on_snapshot(breached))
        self.assertIn("daily_drawdown_breached", manager.last_breach_reason)

    def test_blue_guardian_daily_drawdown_uses_higher_of_balance_or_equity_at_reset(self) -> None:
        manager = RiskManager(config=RiskConfig(), starting_equity=100_000.0, venue_key="blue_guardian")
        reset_snapshot = _snapshot(timestamp=datetime(2026, 1, 1, 22, 5, tzinfo=UTC), balance=100_000.0, equity=102_000.0)
        manager.on_snapshot(reset_snapshot)

        breached = _snapshot(timestamp=datetime(2026, 1, 1, 23, 0, tzinfo=UTC), balance=100_000.0, equity=97_900.0)

        self.assertTrue(manager.on_snapshot(breached))
        self.assertIn("floor=98000.00", manager.last_breach_reason)

    def test_trailing_peak_equity_reference_blocks_orders_after_peak_drawdown_breach(self) -> None:
        config = RiskConfig(max_daily_loss_pct=1.0, max_total_drawdown_pct=0.10)
        manager = RiskManager(config=config, starting_equity=100_000.0, venue_key="generic")
        manager.venue_rules = manager.venue_rules.__class__(
            fill_resolution_routes=manager.venue_rules.fill_resolution_routes,
            total_drawdown_limit_pct=0.10,
            total_drawdown_reference="peak_equity",
        )
        manager.on_snapshot(_snapshot(timestamp=datetime(2026, 1, 1, 10, 0, tzinfo=UTC), balance=100_000.0, equity=100_000.0))
        manager.on_snapshot(_snapshot(timestamp=datetime(2026, 1, 1, 11, 0, tzinfo=UTC), balance=100_000.0, equity=110_000.0))
        breach_snapshot = _snapshot(timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC), balance=100_000.0, equity=98_900.0)

        self.assertTrue(manager.on_snapshot(breach_snapshot))
        self.assertFalse(manager.check_order(_order(breach_snapshot.timestamp), breach_snapshot))
        self.assertIn("total_drawdown_breached", manager.last_breach_reason)


if __name__ == "__main__":
    unittest.main()
