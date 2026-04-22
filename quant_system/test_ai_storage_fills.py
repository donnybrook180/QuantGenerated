from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from quant_system.ai.storage import ExperimentStore


class AIStorageFillsTests(unittest.TestCase):
    def _make_store(self) -> tuple[tempfile.TemporaryDirectory[str], ExperimentStore]:
        temp_dir = tempfile.TemporaryDirectory()
        store = ExperimentStore(f"{temp_dir.name}\\fills.duckdb")
        store._use_postgres_mt5_fill_events = False
        return temp_dir, store

    def _record_fill(
        self,
        store: ExperimentStore,
        *,
        broker_symbol: str,
        requested_symbol: str,
        fill_price: float,
        offset_minutes: int = 0,
    ) -> None:
        store.record_mt5_fill_event(
            event_timestamp=datetime(2026, 4, 21, tzinfo=UTC) + timedelta(minutes=offset_minutes),
            broker_symbol=broker_symbol,
            requested_symbol=requested_symbol,
            side="BUY",
            quantity=1.0,
            requested_price=100.0,
            fill_price=fill_price,
            bid=99.9,
            ask=100.1,
            spread_points=2.0,
            slippage_points=0.5,
            slippage_bps=1.25,
            costs=0.4,
            reason="test",
            confidence=0.8,
            metadata={"source": "test"},
            magic_number=7,
            comment="test",
            position_ticket=42,
        )

    def test_mt5_fill_symbol_variants_match_cash_suffix_aliases(self) -> None:
        temp_dir, store = self._make_store()
        self.addCleanup(temp_dir.cleanup)

        variants = store._mt5_fill_symbol_variants("JP225")

        self.assertIn("JP225", variants)
        self.assertIn("JP225.cash", variants)

    def test_load_mt5_fill_summary_merges_broker_symbol_aliases(self) -> None:
        temp_dir, store = self._make_store()
        self.addCleanup(temp_dir.cleanup)
        self._record_fill(store, broker_symbol="JP225.cash", requested_symbol="JP225", fill_price=100.2)
        self._record_fill(store, broker_symbol="JP225", requested_symbol="JP225", fill_price=100.4, offset_minutes=1)

        summary = store.load_mt5_fill_summary("JP225")

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["fill_count"], 2)

    def test_load_mt5_fill_calibration_ignores_fill_price_zero_rows(self) -> None:
        temp_dir, store = self._make_store()
        self.addCleanup(temp_dir.cleanup)
        for index in range(4):
            self._record_fill(store, broker_symbol="EURUSD", requested_symbol="EURUSD", fill_price=0.0, offset_minutes=index)
        for index in range(5):
            self._record_fill(store, broker_symbol="EURUSD", requested_symbol="EURUSD", fill_price=1.10 + index, offset_minutes=10 + index)

        calibration = store.load_mt5_fill_calibration("EURUSD")

        self.assertIsNotNone(calibration)
        assert calibration is not None
        self.assertEqual(calibration["count"], 5.0)

    def test_fill_summary_handles_partial_rows_without_crashing(self) -> None:
        temp_dir, store = self._make_store()
        self.addCleanup(temp_dir.cleanup)
        self._record_fill(store, broker_symbol="UK100.cash", requested_symbol="UK100", fill_price=0.0)

        summary = store.load_mt5_fill_summary("UK100")

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["fill_count"], 1)

    def test_list_mt5_fill_events_returns_expected_symbol_alias_rows(self) -> None:
        temp_dir, store = self._make_store()
        self.addCleanup(temp_dir.cleanup)
        self._record_fill(store, broker_symbol="EU50.cash", requested_symbol="EU50", fill_price=5010.5)

        rows = store.list_mt5_fill_events("EU50")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["broker_symbol"], "EU50.cash")
        self.assertEqual(rows[0]["requested_symbol"], "EU50")

    def test_load_mt5_fill_calibration_returns_none_when_postgres_temporarily_unavailable(self) -> None:
        temp_dir, store = self._make_store()
        self.addCleanup(temp_dir.cleanup)
        store._use_postgres_mt5_fill_events = True

        with patch.object(store, "_pg_connect", side_effect=RuntimeError("timeout")):
            calibration = store.load_mt5_fill_calibration("EURUSD")

        self.assertIsNone(calibration)


if __name__ == "__main__":
    unittest.main()
