from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from quant_system.config import MT5Config
from quant_system.integrations.mt5 import MT5Client, MT5DealCost
from quant_system.models import OrderRequest, Side


class MT5IntegrationTests(unittest.TestCase):
    def test_lookup_deal_cost_polls_history_deals_until_fill_details_available(self) -> None:
        client = MT5Client(MT5Config(symbol="EURUSD"))
        result = SimpleNamespace(deal=321, order=654)
        matching_deal = SimpleNamespace(
            ticket=321,
            order=654,
            symbol="EURUSD",
            price=1.105,
            commission=-1.5,
            swap=0.0,
            fee=-0.2,
            position_id=77,
        )

        with patch("quant_system.integrations.mt5.mt5.history_deals_get", side_effect=[[], [matching_deal]]), patch(
            "quant_system.integrations.mt5.time.sleep"
        ) as sleep_mock:
            deal_cost = client._lookup_deal_cost(result, "EURUSD")

        self.assertEqual(deal_cost.deal_ticket, 321)
        self.assertEqual(deal_cost.order_ticket, 654)
        self.assertEqual(deal_cost.position_id, 77)
        self.assertEqual(deal_cost.fill_price, 1.105)
        self.assertAlmostEqual(deal_cost.total_cost, 1.7)
        sleep_mock.assert_called_once()

    def test_lookup_deal_cost_matches_order_ticket_even_when_broker_symbol_differs(self) -> None:
        client = MT5Client(MT5Config(symbol="JP225.cash"))
        result = SimpleNamespace(deal=0, order=654)
        matching_deal = SimpleNamespace(
            ticket=321,
            order=654,
            symbol="JP225",
            price=40101.5,
            commission=-1.0,
            swap=0.0,
            fee=-0.2,
            position_id=99,
        )

        with patch("quant_system.integrations.mt5.mt5.history_deals_get", return_value=[matching_deal]), patch(
            "quant_system.integrations.mt5.time.sleep"
        ) as sleep_mock:
            deal_cost = client._lookup_deal_cost(result, "JP225.cash")

        self.assertEqual(deal_cost.deal_ticket, 321)
        self.assertEqual(deal_cost.order_ticket, 654)
        self.assertEqual(deal_cost.position_id, 99)
        self.assertEqual(deal_cost.fill_price, 40101.5)
        self.assertAlmostEqual(deal_cost.total_cost, 1.2)
        sleep_mock.assert_not_called()

    def test_send_market_order_returns_zero_fill_fields_when_no_deal_is_found_in_time(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = MT5Config(symbol="EURUSD", database_path=f"{temp_dir}\\fills.duckdb")
            client = MT5Client(config)
            client.resolved_symbol = "EURUSD"
            order = OrderRequest(
                timestamp=datetime(2026, 4, 21, tzinfo=UTC),
                symbol="EURUSD",
                side=Side.BUY,
                quantity=0.1,
                reason="test_buy",
                confidence=0.75,
            )
            persisted: dict[str, object] = {}

            class FakeStore:
                def __init__(self, database_path: str) -> None:
                    self.database_path = database_path

                def record_mt5_fill_event(self, **kwargs):
                    persisted.update(kwargs)
                    return 1

            with patch("quant_system.integrations.mt5.mt5.symbol_info", return_value=SimpleNamespace(
                volume_step=0.01,
                volume_min=0.01,
                digits=5,
                point=0.00001,
                trade_stops_level=0,
                trade_mode=0,
            )), patch(
                "quant_system.integrations.mt5.mt5.account_info",
                return_value=SimpleNamespace(trade_allowed=True, login=1, server="demo"),
            ), patch(
                "quant_system.integrations.mt5.mt5.terminal_info",
                return_value=SimpleNamespace(trade_allowed=True),
            ), patch(
                "quant_system.integrations.mt5.mt5.order_send",
                return_value=SimpleNamespace(retcode=10009, price=0.0, deal=0, order=123),
            ), patch(
                "quant_system.integrations.mt5.mt5.TRADE_RETCODE_DONE",
                10009,
            ), patch(
                "quant_system.integrations.mt5.mt5.ORDER_TYPE_BUY",
                0,
            ), patch(
                "quant_system.integrations.mt5.mt5.ORDER_TYPE_SELL",
                1,
            ), patch(
                "quant_system.integrations.mt5.mt5.TRADE_ACTION_DEAL",
                1,
            ), patch(
                "quant_system.integrations.mt5.mt5.ORDER_TIME_GTC",
                0,
            ), patch(
                "quant_system.integrations.mt5.mt5.ORDER_FILLING_IOC",
                1,
            ), patch.object(
                MT5Client,
                "market_snapshot",
                return_value=SimpleNamespace(symbol="EURUSD", bid=1.1000, ask=1.1002, point=0.00001, spread_points=0.0002),
            ), patch.object(
                MT5Client,
                "_lookup_deal_cost",
                return_value=MT5DealCost(0, 123, 0, 0.0, 0.0, 0.0, 0.0, 0.0),
            ), patch(
                "quant_system.integrations.mt5.ExperimentStore",
                FakeStore,
            ):
                fill = client.send_market_order(order)

        self.assertEqual(fill.price, 0.0)
        self.assertEqual(persisted["fill_price"], 0.0)
        self.assertEqual(persisted["metadata"]["fill_price_valid"], False)
        self.assertEqual(persisted["metadata"]["deal_ticket"], 0)

    def test_send_market_order_persists_fill_with_real_deal_ticket_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = MT5Config(symbol="JP225.cash", database_path=f"{temp_dir}\\fills.duckdb")
            client = MT5Client(config)
            client.resolved_symbol = "JP225.cash"
            order = OrderRequest(
                timestamp=datetime(2026, 4, 21, tzinfo=UTC),
                symbol="JP225",
                side=Side.SELL,
                quantity=1.0,
                reason="test_short",
                confidence=0.65,
            )
            persisted: dict[str, object] = {}

            class FakeStore:
                def __init__(self, database_path: str) -> None:
                    self.database_path = database_path

                def record_mt5_fill_event(self, **kwargs):
                    persisted.update(kwargs)
                    return 1

            with patch("quant_system.integrations.mt5.mt5.symbol_info", return_value=SimpleNamespace(
                volume_step=0.1,
                volume_min=0.1,
                digits=1,
                point=0.1,
                trade_stops_level=0,
                trade_mode=0,
            )), patch(
                "quant_system.integrations.mt5.mt5.account_info",
                return_value=SimpleNamespace(trade_allowed=True, login=1, server="demo"),
            ), patch(
                "quant_system.integrations.mt5.mt5.terminal_info",
                return_value=SimpleNamespace(trade_allowed=True),
            ), patch(
                "quant_system.integrations.mt5.mt5.order_send",
                return_value=SimpleNamespace(retcode=10009, price=0.0, deal=321, order=654),
            ), patch(
                "quant_system.integrations.mt5.mt5.TRADE_RETCODE_DONE",
                10009,
            ), patch(
                "quant_system.integrations.mt5.mt5.ORDER_TYPE_BUY",
                0,
            ), patch(
                "quant_system.integrations.mt5.mt5.ORDER_TYPE_SELL",
                1,
            ), patch(
                "quant_system.integrations.mt5.mt5.TRADE_ACTION_DEAL",
                1,
            ), patch(
                "quant_system.integrations.mt5.mt5.ORDER_TIME_GTC",
                0,
            ), patch(
                "quant_system.integrations.mt5.mt5.ORDER_FILLING_IOC",
                1,
            ), patch.object(
                MT5Client,
                "market_snapshot",
                return_value=SimpleNamespace(symbol="JP225.cash", bid=40100.0, ask=40102.0, point=0.1, spread_points=2.0),
            ), patch.object(
                MT5Client,
                "_lookup_deal_cost",
                return_value=MT5DealCost(321, 654, 99, 40101.5, 1.0, 0.0, 0.2, 1.2),
            ), patch(
                "quant_system.integrations.mt5.ExperimentStore",
                FakeStore,
            ):
                fill = client.send_market_order(order, magic_number=77)

        self.assertEqual(fill.price, 40101.5)
        self.assertEqual(fill.metadata["deal_ticket"], 321)
        self.assertEqual(fill.metadata["broker_position_id"], 99)
        self.assertEqual(persisted["broker_symbol"], "JP225.cash")
        self.assertEqual(persisted["requested_symbol"], "JP225")
        self.assertEqual(persisted["fill_price"], 40101.5)
        self.assertEqual(persisted["metadata"]["fill_price_valid"], True)


if __name__ == "__main__":
    unittest.main()
