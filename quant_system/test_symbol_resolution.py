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

    def test_resolve_symbol_request_uses_blue_guardian_broker_override_for_jp225(self) -> None:
        resolved = resolve_symbol_request("JP225", venue_key="blue_guardian")

        self.assertEqual(resolved.profile_symbol, "JP225")
        self.assertEqual(resolved.data_symbol, "JP225")
        self.assertEqual(resolved.broker_symbol, "JPN225")

    def test_resolve_symbol_request_uses_blue_guardian_overrides_for_major_indices_and_crypto(self) -> None:
        self.assertEqual(resolve_symbol_request("US500", venue_key="blue_guardian").broker_symbol, "SPX500")
        self.assertEqual(resolve_symbol_request("US100", venue_key="blue_guardian").broker_symbol, "NAS100")
        self.assertEqual(resolve_symbol_request("BTC", venue_key="blue_guardian").broker_symbol, "BTCUSD")
        self.assertEqual(resolve_symbol_request("ETH", venue_key="blue_guardian").broker_symbol, "ETHUSD")

    def test_resolve_symbol_request_uses_fundednext_overrides(self) -> None:
        self.assertEqual(resolve_symbol_request("US500", venue_key="fundednext").broker_symbol, "SPX500")
        self.assertEqual(resolve_symbol_request("US100", venue_key="fundednext").broker_symbol, "NDX100")
        self.assertEqual(resolve_symbol_request("JP225", venue_key="fundednext").broker_symbol, "JP225")
        self.assertEqual(resolve_symbol_request("BRENT", venue_key="fundednext").broker_symbol, "UKOUSD")
        self.assertEqual(resolve_symbol_request("WTI", venue_key="fundednext").broker_symbol, "USOUSD")

    def test_resolve_symbol_request_uses_ftmo_overrides(self) -> None:
        self.assertEqual(resolve_symbol_request("US500", venue_key="ftmo").broker_symbol, "US500.cash")
        self.assertEqual(resolve_symbol_request("US100", venue_key="ftmo").broker_symbol, "US100.cash")
        self.assertEqual(resolve_symbol_request("JP225", venue_key="ftmo").broker_symbol, "JP225.cash")
        self.assertEqual(resolve_symbol_request("BRENT", venue_key="ftmo").broker_symbol, "UKOIL.cash")

    def test_resolve_symbol_request_maps_oil_aliases_to_canonical_symbols(self) -> None:
        self.assertEqual(resolve_symbol_request("UKOUSD").profile_symbol, "BRENT")
        self.assertEqual(resolve_symbol_request("UKOIL.cash").profile_symbol, "BRENT")
        self.assertEqual(resolve_symbol_request("USOUSD").profile_symbol, "WTI")

    def test_resolve_symbol_request_handles_crypto_symbols_consistently(self) -> None:
        resolved = resolve_symbol_request("BTCUSD")

        self.assertEqual(resolved.profile_symbol, "BTC")
        self.assertEqual(resolved.data_symbol, "X:BTCUSD")
        self.assertEqual(resolved.broker_symbol, "BTCUSD")


if __name__ == "__main__":
    unittest.main()
