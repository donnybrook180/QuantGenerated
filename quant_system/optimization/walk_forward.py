from __future__ import annotations

from dataclasses import dataclass

import optuna

from quant_system.config import AgentConfig, ExecutionConfig, OptimizationConfig, RiskConfig
from quant_system.execution.broker import SimulatedBroker
from quant_system.execution.engine import AgentCoordinator
from quant_system.models import FeatureVector
from quant_system.agents.factory import build_alpha_agents
from quant_system.models import OrderRequest, Side
from quant_system.risk.limits import RiskManager


@dataclass(slots=True)
class WalkForwardWindow:
    train: list[FeatureVector]
    test: list[FeatureVector]


def make_walk_forward_windows(
    features: list[FeatureVector],
    config: OptimizationConfig,
) -> list[WalkForwardWindow]:
    windows: list[WalkForwardWindow] = []
    start = 0
    while start + config.train_bars + config.test_bars <= len(features):
        train_end = start + config.train_bars
        test_end = train_end + config.test_bars
        windows.append(
            WalkForwardWindow(
                train=features[start:train_end],
                test=features[train_end:test_end],
            )
        )
        start += config.step_bars
    return windows


class SimpleParameterOptimizer:
    """Optuna-based walk-forward optimizer."""

    def __init__(
        self,
        config: OptimizationConfig,
        execution_config: ExecutionConfig,
        risk_config: RiskConfig,
    ) -> None:
        self.config = config
        self.execution_config = execution_config
        self.risk_config = risk_config

    def fit(self, features: list[FeatureVector], defaults: AgentConfig) -> AgentConfig:
        windows = make_walk_forward_windows(features, self.config)
        if not windows:
            return defaults

        study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=self.config.sampler_seed))
        study.optimize(lambda trial: self._objective(trial, windows, defaults), n_trials=self.config.n_trials)
        best = study.best_params
        return AgentConfig(
            trend_fast_window=best["trend_fast_window"],
            trend_slow_window=best["trend_slow_window"],
            mean_reversion_window=best["mean_reversion_window"],
            mean_reversion_threshold=best["mean_reversion_threshold"],
        )

    def _objective(
        self,
        trial: optuna.Trial,
        windows: list[WalkForwardWindow],
        defaults: AgentConfig,
    ) -> float:
        trend_fast_window = trial.suggest_int("trend_fast_window", *self.config.search_space["trend_fast_window"])
        trend_slow_window = trial.suggest_int("trend_slow_window", *self.config.search_space["trend_slow_window"])
        if trend_fast_window >= trend_slow_window:
            raise optuna.TrialPruned()
        candidate = AgentConfig(
            trend_fast_window=trend_fast_window,
            trend_slow_window=trend_slow_window,
            mean_reversion_window=trial.suggest_int(
                "mean_reversion_window",
                *self.config.search_space["mean_reversion_window"],
            ),
            mean_reversion_threshold=trial.suggest_float(
                "mean_reversion_threshold",
                defaults.mean_reversion_threshold / 2,
                defaults.mean_reversion_threshold * 2,
            ),
        )
        return sum(self._score_window(window, candidate) for window in windows) / len(windows)

    def _score_window(self, window: WalkForwardWindow, candidate: AgentConfig) -> float:
        if len(window.train) + len(window.test) < max(candidate.trend_slow_window, candidate.mean_reversion_window):
            return 0.0
        agents = build_alpha_agents(candidate, self.risk_config)
        coordinator = AgentCoordinator(agents, consensus_min_confidence=candidate.consensus_min_confidence)
        broker = SimulatedBroker(
            initial_cash=self.execution_config.initial_cash,
            fee_bps=self.execution_config.fee_bps,
            commission_per_unit=self.execution_config.commission_per_unit,
            slippage_bps=self.execution_config.slippage_bps,
        )
        risk_manager = RiskManager(
            config=self.risk_config,
            starting_equity=self.execution_config.initial_cash,
        )
        trades = 0
        for feature in window.train:
            coordinator.decide(feature)
        for feature in window.test:
            snapshot = broker.snapshot(feature.timestamp, feature.values["close"])
            if risk_manager.on_snapshot(snapshot):
                break
            decision = coordinator.decide(feature)
            position_qty = broker.get_position_quantity()
            if decision == Side.BUY and position_qty <= 0:
                order = OrderRequest(
                    timestamp=feature.timestamp,
                    symbol=feature.symbol,
                    side=Side.BUY,
                    quantity=self.execution_config.order_size,
                    reason="optuna_eval",
                )
                if risk_manager.check_order(order, snapshot):
                    broker.submit_order(order, feature.values["close"])
                    trades += 1
            elif decision == Side.SELL and position_qty > 0:
                order = OrderRequest(
                    timestamp=feature.timestamp,
                    symbol=feature.symbol,
                    side=Side.SELL,
                    quantity=position_qty,
                    reason="optuna_eval",
                )
                if risk_manager.check_order(order, snapshot):
                    broker.submit_order(order, feature.values["close"])
                    trades += 1
        final_snapshot = broker.snapshot(window.test[-1].timestamp, window.test[-1].values["close"])
        net_return = (final_snapshot.equity / self.execution_config.initial_cash) - 1.0
        trade_penalty = 0.00005 * max(0, 3 - trades)
        drawdown_penalty = final_snapshot.drawdown * 1.5
        return net_return - drawdown_penalty - trade_penalty
