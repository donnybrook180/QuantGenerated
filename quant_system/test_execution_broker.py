from __future__ import annotations

from datetime import UTC, datetime
import unittest

from quant_system.execution.broker import SimulatedBroker
from quant_system.models import OrderRequest, Side


class SimulatedBrokerSwapTests(unittest.TestCase):
    def test_long_trade_books_negative_swap_into_net_pnl(self) -> None:
        broker = SimulatedBroker(
            initial_cash=10_000.0,
            fee_bps=0.0,
            commission_per_unit=0.0,
            slippage_bps=0.0,
            swap_long_per_lot_day=-2.5,
        )
        broker.submit_order(
            OrderRequest(
                timestamp=datetime(2026, 4, 20, 10, 0, tzinfo=UTC),
                symbol="EURUSD",
                side=Side.BUY,
                quantity=1.0,
                reason="entry",
            ),
            100.0,
        )
        broker.submit_order(
            OrderRequest(
                timestamp=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
                symbol="EURUSD",
                side=Side.SELL,
                quantity=1.0,
                reason="exit",
            ),
            105.0,
        )
        closed_trade = broker.get_closed_trades()[0]
        self.assertEqual(closed_trade.pnl, 0.0)
        self.assertEqual(closed_trade.costs, 5.0)
        self.assertEqual(broker.realized_pnl, 0.0)

    def test_short_trade_books_positive_swap_credit_into_net_pnl(self) -> None:
        broker = SimulatedBroker(
            initial_cash=10_000.0,
            fee_bps=0.0,
            commission_per_unit=0.0,
            slippage_bps=0.0,
            swap_short_per_lot_day=1.5,
        )
        broker.submit_order(
            OrderRequest(
                timestamp=datetime(2026, 4, 20, 10, 0, tzinfo=UTC),
                symbol="EURUSD",
                side=Side.SELL,
                quantity=1.0,
                reason="entry",
            ),
            100.0,
        )
        broker.submit_order(
            OrderRequest(
                timestamp=datetime(2026, 4, 21, 10, 0, tzinfo=UTC),
                symbol="EURUSD",
                side=Side.BUY,
                quantity=1.0,
                reason="exit",
            ),
            100.0,
        )
        closed_trade = broker.get_closed_trades()[0]
        self.assertEqual(closed_trade.pnl, 1.5)
        self.assertEqual(closed_trade.costs, -1.5)
        self.assertEqual(broker.realized_pnl, 1.5)

    def test_triple_rollover_day_applies_three_days_of_swap(self) -> None:
        broker = SimulatedBroker(
            initial_cash=10_000.0,
            fee_bps=0.0,
            commission_per_unit=0.0,
            slippage_bps=0.0,
            swap_long_per_lot_day=-1.0,
            swap_rollover3days=3,
        )
        broker.submit_order(
            OrderRequest(
                timestamp=datetime(2026, 4, 21, 10, 0, tzinfo=UTC),
                symbol="EURUSD",
                side=Side.BUY,
                quantity=1.0,
                reason="entry",
            ),
            100.0,
        )
        broker.submit_order(
            OrderRequest(
                timestamp=datetime(2026, 4, 24, 10, 0, tzinfo=UTC),
                symbol="EURUSD",
                side=Side.SELL,
                quantity=1.0,
                reason="exit",
            ),
            100.0,
        )
        closed_trade = broker.get_closed_trades()[0]
        self.assertEqual(closed_trade.pnl, -5.0)
        self.assertEqual(closed_trade.costs, 5.0)


if __name__ == "__main__":
    unittest.main()
