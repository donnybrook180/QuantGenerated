from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import optuna

from quant_system.config import AgentConfig, ExecutionConfig, OptimizationConfig, RiskConfig
from quant_system.optimization.walk_forward import SimpleParameterOptimizer, WalkForwardWindow, WindowScore, make_walk_forward_windows
from quant_system.test_fixtures import make_feature_series


class OptimizationWalkForwardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = OptimizationConfig(train_bars=6, test_bars=3, step_bars=3, n_trials=4, sampler_seed=7)
        self.execution_config = ExecutionConfig(initial_cash=100_000.0)
        self.risk_config = RiskConfig()
        self.defaults = AgentConfig()
        self.optimizer = SimpleParameterOptimizer(
            self.config,
            self.execution_config,
            self.risk_config,
            profile_name="default",
        )

    def test_make_walk_forward_windows_returns_expected_slices(self) -> None:
        features = make_feature_series(12)

        windows = make_walk_forward_windows(features, self.config)

        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0].train, features[:6])
        self.assertEqual(windows[0].test, features[6:9])
        self.assertEqual(windows[1].train, features[3:9])
        self.assertEqual(windows[1].test, features[9:12])

    def test_make_walk_forward_windows_returns_empty_when_not_enough_bars(self) -> None:
        features = make_feature_series(8)

        windows = make_walk_forward_windows(features, self.config)

        self.assertEqual(windows, [])

    def test_score_window_returns_negative_one_without_closed_trades(self) -> None:
        window = WalkForwardWindow(train=make_feature_series(20), test=make_feature_series(15))
        candidate = AgentConfig()

        with patch.object(
            self.optimizer,
            "_simulate_window",
            return_value=WindowScore(
                net_return=0.02,
                expectancy=100.0,
                profit_factor=1.4,
                win_rate_pct=50.0,
                max_drawdown=0.03,
                closed_trades=0,
                total_costs=50.0,
                locked=False,
            ),
        ):
            score = self.optimizer._score_window(window, candidate)

        self.assertEqual(score, -1.0)

    def test_objective_prunes_invalid_fast_slow_window_combination(self) -> None:
        windows = [WalkForwardWindow(train=make_feature_series(10), test=make_feature_series(5))]
        trial = Mock()
        trial.suggest_int.side_effect = [20, 20]

        with self.assertRaises(optuna.TrialPruned):
            self.optimizer._objective(trial, windows, self.defaults)

    def test_fit_returns_defaults_when_no_windows_exist(self) -> None:
        features = make_feature_series(5)

        fitted = self.optimizer.fit(features, self.defaults)

        self.assertEqual(fitted, self.defaults)

    def test_score_window_penalizes_locked_result(self) -> None:
        window = WalkForwardWindow(train=make_feature_series(40), test=make_feature_series(12))
        candidate = AgentConfig()
        unlocked = WindowScore(0.03, 150.0, 1.6, 55.0, 0.03, 10, 40.0, False)
        locked = WindowScore(0.03, 150.0, 1.6, 55.0, 0.03, 10, 40.0, True)

        with patch.object(self.optimizer, "_simulate_window", return_value=unlocked):
            unlocked_score = self.optimizer._score_window(window, candidate)
        with patch.object(self.optimizer, "_simulate_window", return_value=locked):
            locked_score = self.optimizer._score_window(window, candidate)

        self.assertLess(locked_score, unlocked_score)
        self.assertAlmostEqual(unlocked_score - locked_score, 0.5, places=6)

    def test_score_window_penalizes_low_trade_count(self) -> None:
        window = WalkForwardWindow(train=make_feature_series(40), test=make_feature_series(12))
        candidate = AgentConfig()
        dense = WindowScore(0.03, 150.0, 1.6, 55.0, 0.03, 8, 40.0, False)
        sparse = WindowScore(0.03, 150.0, 1.6, 55.0, 0.03, 7, 40.0, False)

        with patch.object(self.optimizer, "_simulate_window", return_value=dense):
            dense_score = self.optimizer._score_window(window, candidate)
        with patch.object(self.optimizer, "_simulate_window", return_value=sparse):
            sparse_score = self.optimizer._score_window(window, candidate)

        self.assertLess(sparse_score, dense_score)
        self.assertAlmostEqual(dense_score - sparse_score, 0.04, places=6)

    def test_fit_uses_best_params_from_study(self) -> None:
        features = make_feature_series(12)
        mock_study = Mock()
        mock_study.best_params = {
            "trend_fast_window": 7,
            "trend_slow_window": 25,
            "mean_reversion_window": 9,
            "mean_reversion_threshold": 0.003,
        }

        with patch("quant_system.optimization.walk_forward.optuna.create_study", return_value=mock_study):
            fitted = self.optimizer.fit(features, self.defaults)

        mock_study.optimize.assert_called_once()
        self.assertEqual(fitted.trend_fast_window, 7)
        self.assertEqual(fitted.trend_slow_window, 25)
        self.assertEqual(fitted.mean_reversion_window, 9)
        self.assertEqual(fitted.mean_reversion_threshold, 0.003)


if __name__ == "__main__":
    unittest.main()
