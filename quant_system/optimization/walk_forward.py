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


@dataclass(slots=True)
class WindowScore:
    net_return: float
    expectancy: float
    profit_factor: float
    win_rate_pct: float
    max_drawdown: float
    closed_trades: int
    total_costs: float
    locked: bool


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
        profile_name: str,
    ) -> None:
        self.config = config
        self.execution_config = execution_config
        self.risk_config = risk_config
        self.profile_name = profile_name

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
        score = self._simulate_window(window, candidate)
        if score.closed_trades == 0:
            return -1.0
        trade_quality = (
            (score.expectancy / self.execution_config.initial_cash) * 5000.0
            + (score.profit_factor - 1.0) * 0.25
            + (score.win_rate_pct - 40.0) * 0.002
        )
        cost_penalty = (score.total_costs / self.execution_config.initial_cash) * 25.0
        drawdown_penalty = score.max_drawdown * 2.5
        trade_count_penalty = 0.04 if score.closed_trades < 8 else 0.0
        lock_penalty = 0.5 if score.locked else 0.0
        return score.net_return + trade_quality - cost_penalty - drawdown_penalty - trade_count_penalty - lock_penalty

    def _simulate_window(self, window: WalkForwardWindow, candidate: AgentConfig) -> WindowScore:
        agents = build_alpha_agents(candidate, self.risk_config, self.profile_name)
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
        last_trade_index: int | None = None
        entry_index: int | None = None
        entry_price: float | None = None
        entry_atr_proxy: float | None = None
        peak_price: float | None = None
        for feature in window.train:
            coordinator.decide(feature)
        for index, feature in enumerate(window.test):
            snapshot = broker.snapshot(feature.timestamp, feature.values["close"])
            if risk_manager.on_snapshot(snapshot):
                break
            decision = coordinator.decide(feature)
            position_qty = broker.get_position_quantity()
            if position_qty > 0 and entry_price is not None:
                close = feature.values["close"]
                atr_proxy = entry_atr_proxy or feature.values.get("atr_proxy", 0.0)
                if atr_proxy > 0:
                    peak_price = close if peak_price is None else max(peak_price, close)
                    stop_price = entry_price - (entry_price * atr_proxy * self.execution_config.stop_loss_atr_multiple)
                    target_price = entry_price + (entry_price * atr_proxy * self.execution_config.take_profit_atr_multiple)
                    break_even_price = entry_price + (entry_price * atr_proxy * self.execution_config.break_even_atr_multiple)
                    trailing_floor = max(
                        entry_price,
                        (peak_price or close) - (entry_price * atr_proxy * self.execution_config.trailing_stop_atr_multiple),
                    )
                    if close <= stop_price or close >= target_price:
                        decision = Side.SELL
                    elif (peak_price or close) >= break_even_price and close <= trailing_floor:
                        decision = Side.SELL
            if (
                position_qty > 0
                and self.execution_config.max_holding_bars > 0
                and entry_index is not None
                and (index - entry_index) >= self.execution_config.max_holding_bars
            ):
                decision = Side.SELL
            if decision == Side.BUY and position_qty <= 0:
                if last_trade_index is not None and (index - last_trade_index) < self.execution_config.min_bars_between_trades:
                    continue
                order = OrderRequest(
                    timestamp=feature.timestamp,
                    symbol=feature.symbol,
                    side=Side.BUY,
                    quantity=self.execution_config.order_size,
                    reason="optuna_eval",
                )
                if risk_manager.check_order(order, snapshot):
                    fill = broker.submit_order(order, feature.values["close"])
                    trades += 1
                    last_trade_index = index
                    entry_index = index
                    entry_price = fill.price
                    entry_atr_proxy = max(feature.values.get("atr_proxy", 0.0), 0.0001)
                    peak_price = fill.price
            elif decision == Side.SELL and position_qty > 0:
                if last_trade_index is not None and (index - last_trade_index) < self.execution_config.min_bars_between_trades:
                    continue
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
                    last_trade_index = index
                    entry_index = None
                    entry_price = None
                    entry_atr_proxy = None
                    peak_price = None
        final_snapshot = broker.snapshot(window.test[-1].timestamp, window.test[-1].values["close"])
        closed_trade_pnls = broker.get_closed_trade_pnls()
        wins = [pnl for pnl in closed_trade_pnls if pnl > 0]
        losses = [pnl for pnl in closed_trade_pnls if pnl < 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
        expectancy = sum(closed_trade_pnls) / len(closed_trade_pnls) if closed_trade_pnls else 0.0
        win_rate_pct = (len(wins) / len(closed_trade_pnls) * 100.0) if closed_trade_pnls else 0.0
        return WindowScore(
            net_return=(final_snapshot.equity / self.execution_config.initial_cash) - 1.0,
            expectancy=expectancy,
            profit_factor=profit_factor,
            win_rate_pct=win_rate_pct,
            max_drawdown=final_snapshot.drawdown,
            closed_trades=len(closed_trade_pnls),
            total_costs=broker.get_total_costs(),
            locked=risk_manager.locked_until is not None,
        )
