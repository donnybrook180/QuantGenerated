from __future__ import annotations

import unittest

from quant_system.symbols import resolve_symbol_request


class SymbolResolutionTests(unittest.TestCase):
    def test_resolve_symbol_request_maps_profile_data_and_broker_symbol(self) -> None:
        resolved = resolve_symbol_request("EURUSD")

        self.assertEqual(resolved.profile_symbol, "EURUSD")
        self.assertEqual(resolved.data_symbol, "C:EURUSD")
        self.assertEqual(resolved.broker_symbol, "EURUSD")

    def test_resolve_symbol_request_handles_index_cash_aliases(self) -> None:
        resolved = resolve_symbol_request("JP225.cash")

        self.assertEqual(resolved.profile_symbol, "JP225")
        self.assertEqual(resolved.data_symbol, "JP225")
        self.assertEqual(resolved.broker_symbol, "JP225.cash")

    def test_resolve_symbol_request_handles_crypto_symbols_consistently(self) -> None:
        resolved = resolve_symbol_request("BTCUSD")

        self.assertEqual(resolved.profile_symbol, "BTC")
        self.assertEqual(resolved.data_symbol, "X:BTCUSD")
        self.assertEqual(resolved.broker_symbol, "BTCUSD")


if __name__ == "__main__":
    unittest.main()
