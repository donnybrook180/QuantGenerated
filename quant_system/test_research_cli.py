from __future__ import annotations

import unittest
from unittest.mock import patch

from quant_system.config import SystemConfig
from quant_system.research.cli import (
    resolve_symbol_research_request,
    run_live_research_cli,
    run_symbol_research_cli,
    symbol_research_usage,
)


class ResearchCliTests(unittest.TestCase):
    def test_resolve_symbol_research_request_uses_cli_args_first(self) -> None:
        config = SystemConfig()
        config.symbol_research.symbol = "IGNORED"

        data_symbol, broker_symbol = resolve_symbol_research_request(["EURUSD", "EURUSD"], config)

        self.assertEqual(data_symbol, "EURUSD")
        self.assertEqual(broker_symbol, "EURUSD")

    def test_resolve_symbol_research_request_falls_back_to_config(self) -> None:
        config = SystemConfig()
        config.symbol_research.symbol = "XAUUSD"
        config.symbol_research.broker_symbol = "XAUUSD.cash"

        data_symbol, broker_symbol = resolve_symbol_research_request([], config)

        self.assertEqual(data_symbol, "XAUUSD")
        self.assertEqual(broker_symbol, "XAUUSD.cash")

    def test_run_symbol_research_cli_prints_usage_when_symbol_missing(self) -> None:
        printed: list[str] = []
        with patch("quant_system.research.cli.SystemConfig") as config_cls:
            config = config_cls.return_value
            config.symbol_research.symbol = ""
            config.symbol_research.broker_symbol = ""

            exit_code = run_symbol_research_cli([], print_fn=printed.append)

        self.assertEqual(exit_code, 1)
        self.assertEqual(printed, [symbol_research_usage()])

    def test_run_symbol_research_cli_invokes_app(self) -> None:
        printed: list[str] = []
        with patch("quant_system.research.cli.run_symbol_research_app", return_value=["ok"]) as run_app:
            exit_code = run_symbol_research_cli(["EURUSD"], print_fn=printed.append)

        self.assertEqual(exit_code, 0)
        run_app.assert_called_once_with("EURUSD", None)
        self.assertEqual(printed, ["ok"])

    def test_run_live_research_cli_invokes_app_with_prefixes(self) -> None:
        printed: list[str] = []
        with patch("quant_system.research.cli.run_symbol_research_app", return_value=["done"]) as run_app:
            exit_code = run_live_research_cli(
                ["EURUSD", "EURUSD", "blue_guardian", "[\"trend\",\"breakout\"]"],
                print_fn=printed.append,
            )

        self.assertEqual(exit_code, 0)
        run_app.assert_called_once_with("EURUSD", "EURUSD", candidate_name_prefixes=("trend", "breakout"))
        self.assertIn("Live research runner experiment_type=blue_guardian", printed[0])
        self.assertEqual(printed[-1], "done")


if __name__ == "__main__":
    unittest.main()
