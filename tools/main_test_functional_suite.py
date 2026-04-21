from __future__ import annotations

import sys
import unittest


TEST_MODULES = [
    "quant_system.test_evaluation_report",
    "quant_system.test_optimization_walk_forward",
    "quant_system.test_market_data_duckdb",
    "quant_system.test_ai_storage_fills",
    "quant_system.test_symbol_resolution",
    "quant_system.test_mt5_integration",
    "quant_system.test_live_deploy_runtime",
    "quant_system.test_interpreter_engines",
    "quant_system.test_interpreter_app",
    "quant_system.test_interpreter_reporting",
    "quant_system.test_symbol_research_selection",
    "quant_system.test_symbol_research_viability",
    "quant_system.test_symbol_research_exports",
    "quant_system.test_research_end_to_end",
    "quant_system.test_research_artifacts",
    "quant_system.test_symbol_threshold_profiles",
    "quant_system.test_research_failure_modes",
]


def main() -> int:
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite(loader.loadTestsFromName(module_name) for module_name in TEST_MODULES)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
