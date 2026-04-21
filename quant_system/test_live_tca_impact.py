from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from quant_system.live.tca_impact import generate_tca_impact_report


class LiveTCAImpactTests(unittest.TestCase):
    def test_generate_tca_impact_report_includes_raw_and_tca_fill_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            deploy_dir = root / "deploy" / "eurusd"
            reports_dir = root / "reports"
            deploy_dir.mkdir(parents=True, exist_ok=True)
            reports_dir.mkdir(parents=True, exist_ok=True)
            (deploy_dir / "live.json").write_text(
                json.dumps(
                    {
                        "symbol": "EURUSD",
                        "broker_symbol": "EURUSD",
                        "research_run_id": 7,
                        "strategies": [{"candidate_name": "candidate_a"}],
                    }
                ),
                encoding="utf-8",
            )

            fake_store = SimpleNamespace(
                load_mt5_fill_summary=lambda broker_symbol: {"fill_count": 9},
                list_symbol_research_candidates_for_run=lambda run_id: [
                    {
                        "candidate_name": "candidate_a",
                        "expectancy": 12.5,
                        "closed_trades": 8,
                        "avg_win": 20.0,
                        "avg_loss": -10.0,
                    }
                ],
            )
            fake_tca_strategy = SimpleNamespace(
                label="candidate_a",
                weighted_shortfall_bps=1.2,
                weighted_cost_bps=0.8,
                fill_count=3,
            )
            fake_tca_report = SimpleNamespace(by_strategy=[fake_tca_strategy])

            with (
                patch("quant_system.live.tca_impact.DEPLOY_DIR", root / "deploy"),
                patch("quant_system.live.tca_impact.system_reports_dir", return_value=reports_dir),
                patch("quant_system.live.tca_impact.ExperimentStore", return_value=fake_store),
                patch("quant_system.live.tca_impact.generate_tca_report", return_value=fake_tca_report),
                patch(
                    "quant_system.live.tca_impact.load_symbol_deployment",
                    return_value=SimpleNamespace(
                        symbol="EURUSD",
                        broker_symbol="EURUSD",
                        research_run_id=7,
                        strategies=[SimpleNamespace(candidate_name="candidate_a")],
                    ),
                ),
            ):
                report_path = generate_tca_impact_report()

            payload = json.loads(report_path.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(len(payload["rows"]), 1)
            row = payload["rows"][0]
            self.assertEqual(row["raw_live_fill_count"], 9)
            self.assertEqual(row["live_fill_count"], 3)


if __name__ == "__main__":
    unittest.main()
