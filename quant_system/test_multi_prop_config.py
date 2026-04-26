from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from quant_system.config import SystemConfig, apply_mt5_broker, credential_config_for_venue, resolve_live_prop_brokers
from quant_system.live.app import configure_live_runtime, resolve_live_deployment_paths


class MultiPropConfigTests(unittest.TestCase):
    def test_system_config_uses_prop_broker_specific_mt5_credentials(self) -> None:
        env = {
            "PROP_BROKER": "blue_guardian",
            "MT5_BLUE_GUARDIAN_LOGIN": "111",
            "MT5_BLUE_GUARDIAN_PASSWORD": "bg-pass",
            "MT5_BLUE_GUARDIAN_SERVER": "BG-Server",
            "MT5_BLUE_GUARDIAN_TERMINAL_PATH": r"C:\BG\terminal64.exe",
            "MT5_LOGIN": "999",
            "MT5_PASSWORD": "generic-pass",
            "MT5_SERVER": "Generic-Server",
            "MT5_TERMINAL_PATH": r"C:\Generic\terminal64.exe",
        }
        with patch.dict("os.environ", env, clear=False):
            config = SystemConfig()

        self.assertEqual(config.mt5.prop_broker, "blue_guardian")
        self.assertEqual(config.mt5.login, 111)
        self.assertEqual(config.mt5.password, "bg-pass")
        self.assertEqual(config.mt5.server, "BG-Server")
        self.assertEqual(config.mt5.terminal_path, r"C:\BG\terminal64.exe")

    def test_resolve_live_prop_brokers_prefers_explicit_list(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "PROP_BROKER": "blue_guardian",
                "LIVE_PROP_BROKERS": "ftmo, fundednext, blue_guardian, ftmo",
            },
            clear=False,
        ):
            brokers = resolve_live_prop_brokers()

        self.assertEqual(brokers, ("ftmo", "fundednext", "blue_guardian"))

    def test_apply_mt5_broker_retargets_existing_config(self) -> None:
        env = {
            "PROP_BROKER": "ftmo",
            "MT5_FTMO_LOGIN": "101",
            "MT5_FTMO_PASSWORD": "ftmo-pass",
            "MT5_FTMO_SERVER": "FTMO-Server",
            "MT5_FTMO_TERMINAL_PATH": r"C:\FTMO\terminal64.exe",
            "MT5_BLUE_GUARDIAN_LOGIN": "202",
            "MT5_BLUE_GUARDIAN_PASSWORD": "bg-pass",
            "MT5_BLUE_GUARDIAN_SERVER": "BG-Server",
            "MT5_BLUE_GUARDIAN_TERMINAL_PATH": r"C:\BG\terminal64.exe",
        }
        with patch.dict("os.environ", env, clear=False):
            config = SystemConfig()
            apply_mt5_broker(config, "blue_guardian")
            credentials = credential_config_for_venue("blue_guardian")

        self.assertEqual(config.mt5.prop_broker, "blue_guardian")
        self.assertEqual(config.mt5.login, 202)
        self.assertEqual(config.mt5.password, "bg-pass")
        self.assertEqual(credentials.terminal_path, r"C:\BG\terminal64.exe")

    def test_resolve_live_deployment_paths_filters_to_selected_broker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            ftmo_path = base / "ftmo" / "eurusd" / "live.json"
            bg_path = base / "blue_guardian" / "eurusd" / "live.json"
            ftmo_path.parent.mkdir(parents=True, exist_ok=True)
            bg_path.parent.mkdir(parents=True, exist_ok=True)
            ftmo_path.write_text("{}", encoding="utf-8")
            bg_path.write_text("{}", encoding="utf-8")
            config = SystemConfig()
            with patch("quant_system.live.app.DEPLOY_DIR", base), patch(
                "quant_system.live.app.list_deployment_paths",
                return_value=[ftmo_path, bg_path],
            ), patch(
                "quant_system.live.app.load_symbol_deployment",
                side_effect=[
                    SimpleNamespace(venue_key="ftmo"),
                    SimpleNamespace(venue_key="blue_guardian"),
                ],
            ):
                config, _symbols = configure_live_runtime(["--broker", "blue_guardian"], config)
                paths = resolve_live_deployment_paths(["--broker", "blue_guardian"], config)

        self.assertEqual(paths, [bg_path])


if __name__ == "__main__":
    unittest.main()
