from __future__ import annotations

import unittest
from types import SimpleNamespace

from quant_system.config import SystemConfig
from quant_system.research.data_sources import build_broker_data_sanity_summary
from quant_system.test_fixtures import make_feature, make_feature_series


class _FakeMT5Client:
    def __init__(self, config) -> None:
        self.config = config
        self.resolved_symbol = "EURUSD.bg"
        self.initialized = False
        self.shutdown_called = False

    def initialize(self) -> None:
        self.initialized = True

    def funding_info(self):
        return SimpleNamespace(
            point=0.00001,
            contract_size=100000.0,
            swap_long=-2.4,
            swap_short=0.5,
        )

    def market_snapshot(self):
        return SimpleNamespace(spread_points=0.00012)

    def shutdown(self) -> None:
        self.shutdown_called = True


class _BrokenMT5Client(_FakeMT5Client):
    def funding_info(self):
        raise RuntimeError("funding unavailable")


class ResearchDataSourcesTests(unittest.TestCase):
    def test_build_broker_data_sanity_summary_marks_blue_guardian_mt5_and_contract_specs(self) -> None:
        config = SystemConfig()
        config.mt5.prop_broker = "blue_guardian"
        features = make_feature_series(3, symbol="EURUSD")

        summary = build_broker_data_sanity_summary(
            config,
            "EURUSD",
            "C:EURUSD",
            "EURUSD",
            "mt5",
            features,
            mt5_client_cls=_FakeMT5Client,
        )

        self.assertEqual(summary["broker_data_source"], "blue_guardian_mt5")
        self.assertEqual(summary["broker_symbol"], "EURUSD.bg")
        self.assertEqual(summary["history_bars_loaded"], 3)
        self.assertEqual(summary["missing_bar_warnings"], ())
        self.assertIn("broker-backed research path", str(summary["session_alignment_notes"]))
        self.assertIn("resolved_symbol=EURUSD.bg", str(summary["contract_spec_notes"]))
        self.assertIn("spread_points=0.00012000", str(summary["contract_spec_notes"]))
        self.assertIn("swap_long=-2.4000", str(summary["contract_spec_notes"]))

    def test_build_broker_data_sanity_summary_reports_timestamp_gaps(self) -> None:
        config = SystemConfig()
        features = [
            make_feature(index=0, symbol="JP225"),
            make_feature(index=1, symbol="JP225"),
            make_feature(index=5, symbol="JP225"),
        ]

        summary = build_broker_data_sanity_summary(
            config,
            "JP225",
            "JP225",
            "JP225.cash",
            "duckdb_cache",
            features,
        )

        self.assertEqual(summary["broker_data_source"], "duckdb_cache")
        self.assertIn("detected_1_timestamp_gaps_gt_5m", summary["missing_bar_warnings"])
        self.assertEqual(summary["contract_spec_notes"], "not_available")

    def test_build_broker_data_sanity_summary_records_contract_lookup_failures(self) -> None:
        config = SystemConfig()
        config.mt5.prop_broker = "blue_guardian"
        features = make_feature_series(1, symbol="XAUUSD")

        summary = build_broker_data_sanity_summary(
            config,
            "XAUUSD",
            "XAUUSD",
            "XAUUSD",
            "mt5",
            features,
            mt5_client_cls=_BrokenMT5Client,
        )

        self.assertEqual(summary["broker_data_source"], "mt5")
        self.assertTrue(any(str(item).startswith("contract_spec_lookup_failed:") for item in summary["missing_bar_warnings"]))
        self.assertEqual(summary["contract_spec_notes"], "not_available")


if __name__ == "__main__":
    unittest.main()
