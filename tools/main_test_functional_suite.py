from __future__ import annotations

import sys
import unittest


TEST_MODULES = [
    "quant_system.test_evaluation_report",
    "quant_system.test_optimization_walk_forward",
    "quant_system.test_interpreter_engines",
    "quant_system.test_interpreter_app",
    "quant_system.test_interpreter_reporting",
    "quant_system.test_symbol_research_selection",
    "quant_system.test_symbol_research_viability",
    "quant_system.test_symbol_research_exports",
]


def main() -> int:
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite(loader.loadTestsFromName(module_name) for module_name in TEST_MODULES)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
