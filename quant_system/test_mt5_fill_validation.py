from __future__ import annotations

import sys
import unittest
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

VALIDATOR_PATH = TOOLS_DIR / "main_validate_mt5_fill_capture.py"
VALIDATOR_SPEC = importlib.util.spec_from_file_location("main_validate_mt5_fill_capture", VALIDATOR_PATH)
assert VALIDATOR_SPEC is not None and VALIDATOR_SPEC.loader is not None
VALIDATOR_MODULE = importlib.util.module_from_spec(VALIDATOR_SPEC)
VALIDATOR_SPEC.loader.exec_module(VALIDATOR_MODULE)
_report_symbol = VALIDATOR_MODULE._report_symbol


class MT5FillValidationTests(unittest.TestCase):
    def test_report_symbol_returns_pass_when_all_fills_have_valid_prices(self) -> None:
        rows = [
            {
                "event_timestamp": "2026-04-21 08:00:00",
                "fill_price": 1.1050,
                "requested_price": 1.1048,
                "metadata": {"deal_ticket": 123, "order_ticket": 456, "fill_resolution_source": "deal_history"},
            }
        ]

        class FakeStore:
            def __init__(self, database_path: str, read_only: bool = False) -> None:
                self.database_path = database_path
                self.read_only = read_only

            def list_mt5_fill_events(self, broker_symbol: str):
                return rows

        with patch.object(
            VALIDATOR_MODULE,
            "SystemConfig",
            return_value=SimpleNamespace(ai=SimpleNamespace(experiment_database_path="fills.duckdb")),
        ), patch.object(
            VALIDATOR_MODULE,
            "ExperimentStore",
            FakeStore,
        ), patch.object(
            VALIDATOR_MODULE,
            "resolve_symbol_request",
            return_value=SimpleNamespace(profile_symbol="EURUSD", broker_symbol="EURUSD"),
        ):
            lines = _report_symbol("EURUSD")

        self.assertIn("Rows with fill_price > 0: 1", lines)
        self.assertIn("Rows with deal_ticket > 0: 1", lines)
        self.assertIn("Valid fill sources: deal_history=1", lines)
        self.assertIn("Status: PASS - all recorded fills have valid fill prices.", lines)

    def test_report_symbol_returns_mixed_when_old_invalid_rows_and_new_valid_rows_exist(self) -> None:
        rows = [
            {
                "event_timestamp": "2026-04-21 08:00:00",
                "fill_price": 0.0,
                "requested_price": 1.1048,
                "metadata": {"deal_ticket": 0, "order_ticket": 456, "fill_resolution_source": "unknown"},
            },
            {
                "event_timestamp": "2026-04-21 09:00:00",
                "fill_price": 1.1050,
                "requested_price": 1.1048,
                "metadata": {"deal_ticket": 0, "order_ticket": 789, "broker_position_id": 789},
            },
        ]

        class FakeStore:
            def __init__(self, database_path: str, read_only: bool = False) -> None:
                self.database_path = database_path
                self.read_only = read_only

            def list_mt5_fill_events(self, broker_symbol: str):
                return rows

        with patch.object(
            VALIDATOR_MODULE,
            "SystemConfig",
            return_value=SimpleNamespace(ai=SimpleNamespace(experiment_database_path="fills.duckdb")),
        ), patch.object(
            VALIDATOR_MODULE,
            "ExperimentStore",
            FakeStore,
        ), patch.object(
            VALIDATOR_MODULE,
            "resolve_symbol_request",
            return_value=SimpleNamespace(profile_symbol="JP225", broker_symbol="JP225.cash"),
        ):
            lines = _report_symbol("JP225")

        self.assertIn("Rows with fill_price > 0: 1", lines)
        self.assertIn("Rows with deal_ticket > 0: 0", lines)
        self.assertIn("Valid fill sources: position_open=1", lines)
        self.assertIn("Status: MIXED - new fill capture is working, but older invalid rows still exist.", lines)

    def test_report_symbol_returns_fail_when_only_invalid_rows_exist(self) -> None:
        rows = [
            {
                "event_timestamp": "2026-04-21 08:00:00",
                "fill_price": 0.0,
                "requested_price": 1.1048,
                "metadata": {"deal_ticket": 0, "order_ticket": 456, "fill_resolution_source": "unknown"},
            }
        ]

        class FakeStore:
            def __init__(self, database_path: str, read_only: bool = False) -> None:
                self.database_path = database_path
                self.read_only = read_only

            def list_mt5_fill_events(self, broker_symbol: str):
                return rows

        with patch.object(
            VALIDATOR_MODULE,
            "SystemConfig",
            return_value=SimpleNamespace(ai=SimpleNamespace(experiment_database_path="fills.duckdb")),
        ), patch.object(
            VALIDATOR_MODULE,
            "ExperimentStore",
            FakeStore,
        ), patch.object(
            VALIDATOR_MODULE,
            "resolve_symbol_request",
            return_value=SimpleNamespace(profile_symbol="UK100", broker_symbol="UK100.cash"),
        ):
            lines = _report_symbol("UK100")

        self.assertIn("Recorded fills: 1", lines)
        self.assertIn("Rows with fill_price > 0: 0", lines)
        self.assertIn("Rows with deal_ticket > 0: 0", lines)
        self.assertIn("Valid fill sources: none", lines)
        self.assertIn("Status: FAIL - fills exist but none have a valid fill_price yet.", lines)

    def test_report_symbol_returns_waiting_when_no_rows_exist(self) -> None:
        class FakeStore:
            def __init__(self, database_path: str, read_only: bool = False) -> None:
                self.database_path = database_path
                self.read_only = read_only

            def list_mt5_fill_events(self, broker_symbol: str):
                return []

        with patch.object(
            VALIDATOR_MODULE,
            "SystemConfig",
            return_value=SimpleNamespace(ai=SimpleNamespace(experiment_database_path="fills.duckdb")),
        ), patch.object(
            VALIDATOR_MODULE,
            "ExperimentStore",
            FakeStore,
        ), patch.object(
            VALIDATOR_MODULE,
            "resolve_symbol_request",
            return_value=SimpleNamespace(profile_symbol="US500", broker_symbol="US500.cash"),
        ):
            lines = _report_symbol("US500")

        self.assertIn("Recorded fills: 0", lines)
        self.assertIn("Rows with fill_price > 0: 0", lines)
        self.assertIn("Rows with deal_ticket > 0: 0", lines)
        self.assertIn("Valid fill sources: none", lines)
        self.assertIn("Status: WAITING - no fills recorded yet for this symbol.", lines)


if __name__ == "__main__":
    unittest.main()
