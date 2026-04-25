from __future__ import annotations

import unittest

from quant_system.venues import get_venue_profile, infer_venue_key, normalize_venue_key


class VenueRegistryTests(unittest.TestCase):
    def test_normalize_venue_key_maps_blue_guardian_aliases(self) -> None:
        self.assertEqual(normalize_venue_key("Blue Guardian"), "blue_guardian")
        self.assertEqual(normalize_venue_key("blueguardian"), "blue_guardian")

    def test_infer_venue_key_prefers_explicit_non_generic_value(self) -> None:
        inferred = infer_venue_key(server="FTMO-Demo", company="FTMO Global Markets", explicit="fundednext")
        self.assertEqual(inferred, "fundednext")

    def test_infer_venue_key_detects_company_hint(self) -> None:
        inferred = infer_venue_key(server="demo", company="Blue Guardian")
        self.assertEqual(inferred, "blue_guardian")

    def test_get_venue_profile_returns_expected_fill_routes(self) -> None:
        generic = get_venue_profile("generic")
        blue_guardian = get_venue_profile("blue_guardian")

        self.assertEqual(generic.rules.fill_resolution_routes, ("history_deals", "history_orders", "open_position"))
        self.assertEqual(blue_guardian.rules.fill_resolution_routes, ("history_deals", "open_position", "history_orders"))
        self.assertEqual(blue_guardian.display_name, "Blue Guardian")


if __name__ == "__main__":
    unittest.main()
