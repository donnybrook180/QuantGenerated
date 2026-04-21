from __future__ import annotations

import copy
import unittest

from quant_system.config import SystemConfig
from quant_system.symbol_research import _research_thresholds, _symbol_research_history_days, _supports_4h_research, _meets_viability
from quant_system.test_fixtures import make_candidate_result


class SymbolThresholdProfilesTests(unittest.TestCase):
    def test_xauusd_threshold_profile_remains_stable(self) -> None:
        thresholds = _research_thresholds("XAUUSD")
        self.assertEqual(thresholds["validation_closed_trades"], 3)
        self.assertEqual(thresholds["test_closed_trades"], 2)
        self.assertEqual(thresholds["walk_forward_min_pass_rate_pct"], 50.0)

    def test_btc_threshold_profile_remains_stable(self) -> None:
        thresholds = _research_thresholds("BTC")
        self.assertEqual(thresholds["validation_closed_trades"], 2)
        self.assertEqual(thresholds["test_closed_trades"], 1)
        self.assertEqual(thresholds["walk_forward_min_pass_rate_pct"], 40.0)

    def test_eth_history_days_remains_longer_than_generic_4h_symbols(self) -> None:
        config = SystemConfig()
        config.symbol_research.history_days = 180
        config.market_data.history_days = 180

        self.assertTrue(_supports_4h_research("ETH"))
        self.assertEqual(_symbol_research_history_days(config, "ETH"), 1460)
        self.assertEqual(_symbol_research_history_days(config, "JP225"), 730)

    def test_4h_viability_thresholds_are_stricter_than_intraday(self) -> None:
        base = make_candidate_result(
            code_path="quant_system.agents.trend.TrendAgent",
            realized_pnl=100.0,
            profit_factor=1.5,
            closed_trades=3,
            validation_pnl=30.0,
            validation_profit_factor=1.2,
            validation_closed_trades=3,
            test_pnl=20.0,
            test_profit_factor=1.1,
            test_closed_trades=2,
            walk_forward_windows=1,
            walk_forward_pass_rate_pct=100.0,
            walk_forward_avg_validation_pnl=15.0,
            walk_forward_avg_test_pnl=15.0,
            regime_stability_score=0.7,
            equity_quality_score=0.7,
            best_trade_share_pct=40.0,
            strategy_family="trend",
            direction_mode="both",
            direction_role="combined",
        )
        intraday = copy.deepcopy(base)
        intraday.timeframe_label = "15m"
        four_hour = copy.deepcopy(base)
        four_hour.timeframe_label = "4h"

        self.assertTrue(_meets_viability(intraday, "XAUUSD"))
        self.assertFalse(_meets_viability(four_hour, "XAUUSD"))


if __name__ == "__main__":
    unittest.main()
