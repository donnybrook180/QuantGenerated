from __future__ import annotations

import unittest
from unittest.mock import patch

import duckdb

from quant_system.symbol_research import run_symbol_research
from quant_system.test_fixtures import make_feature


class ResearchFailureModesTests(unittest.TestCase):
    def test_run_symbol_research_raises_clear_error_when_no_feature_variants_exist(self) -> None:
        with patch(
            "quant_system.symbol_research._build_symbol_feature_variants",
            return_value=({"default": []}, "test", "full"),
        ):
            with self.assertRaises(RuntimeError) as exc:
                run_symbol_research("EURUSD")

        self.assertIn("No usable feature variants were generated for EURUSD", str(exc.exception))

    def test_run_symbol_research_propagates_duckdb_lock_during_store_init(self) -> None:
        with patch(
            "quant_system.symbol_research._build_symbol_feature_variants",
            return_value=({"15m_overlap": [make_feature(index=0, symbol="EURUSD")]}, "test", "full"),
        ), patch(
            "quant_system.symbol_research._candidate_specs",
            return_value=[],
        ), patch(
            "quant_system.symbol_research._near_miss_local_optimizer",
            return_value=([], []),
        ), patch(
            "quant_system.symbol_research._combined_specs",
            return_value=[],
        ), patch(
            "quant_system.symbol_research.plot_symbol_research",
            return_value=[],
        ), patch(
            "quant_system.symbol_research.ExperimentStore",
            side_effect=duckdb.IOException("database is locked"),
        ):
            with self.assertRaises(duckdb.IOException) as exc:
                run_symbol_research("EURUSD")

        self.assertIn("locked", str(exc.exception).lower())

    def test_run_symbol_research_rejects_empty_default_features_before_store_write(self) -> None:
        with patch(
            "quant_system.symbol_research._build_symbol_feature_variants",
            return_value=({}, "test", "full"),
        ):
            with self.assertRaises(RuntimeError) as exc:
                run_symbol_research("US100")

        self.assertIn("No usable feature variants were generated for US100", str(exc.exception))


if __name__ == "__main__":
    unittest.main()
