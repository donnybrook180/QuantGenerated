from __future__ import annotations

from datetime import UTC, datetime, timedelta

from quant_system.execution.engine import ExecutionResult
from quant_system.models import ClosedTradeRecord, FeatureVector, MarketBar
from quant_system.symbol_research import CandidateResult


def make_feature(*, index: int, symbol: str = "EURUSD", close: float = 100.0, atr_proxy: float = 0.01) -> FeatureVector:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=index * 5)
    return FeatureVector(
        timestamp=timestamp,
        symbol=symbol,
        values={
            "close": close,
            "atr_proxy": atr_proxy,
            "trend_strength": 0.001,
            "relative_volume": 1.0,
        },
    )


def make_feature_series(count: int, *, symbol: str = "EURUSD", start_close: float = 100.0) -> list[FeatureVector]:
    return [
        make_feature(index=index, symbol=symbol, close=start_close + float(index))
        for index in range(count)
    ]


def make_market_bar_series(
    count: int,
    *,
    symbol: str = "EURUSD",
    start_close: float = 100.0,
    minutes: int = 60,
) -> list[MarketBar]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars: list[MarketBar] = []
    for index in range(count):
        close = start_close + float(index)
        bars.append(
            MarketBar(
                timestamp=start + timedelta(minutes=index * minutes),
                symbol=symbol,
                open=close - 0.5,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                volume=100.0 + float(index),
            )
        )
    return bars


def make_closed_trade(
    *,
    pnl: float = 100.0,
    symbol: str = "EURUSD",
    index: int = 0,
    hold_bars: int = 3,
) -> ClosedTradeRecord:
    entry_timestamp = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=index * 5)
    exit_timestamp = entry_timestamp + timedelta(minutes=hold_bars * 5)
    return ClosedTradeRecord(
        symbol=symbol,
        entry_timestamp=entry_timestamp,
        exit_timestamp=exit_timestamp,
        entry_price=100.0,
        exit_price=101.0,
        quantity=1.0,
        pnl=pnl,
        costs=2.0,
        entry_reason="test_entry",
        exit_reason="test_exit",
        entry_hour=entry_timestamp.hour,
        exit_hour=exit_timestamp.hour,
        hold_bars=hold_bars,
        entry_confidence=0.75,
        entry_metadata={},
    )


def make_execution_result(
    *,
    initial_cash: float = 100_000.0,
    ending_equity: float | None = None,
    realized_pnl: float = 12_000.0,
    trades: int = 12,
    locked: bool = False,
    max_drawdown: float = 0.04,
    win_rate_pct: float = 45.0,
    profit_factor: float = 1.5,
    total_costs: float = 250.0,
    closed_trade_pnls: list[float] | None = None,
) -> ExecutionResult:
    pnls = closed_trade_pnls or [500.0, -200.0, 800.0, -100.0, 300.0, 250.0, -50.0, 400.0, 150.0, 200.0]
    closed_trades = [make_closed_trade(pnl=pnl, index=index) for index, pnl in enumerate(pnls)]
    return ExecutionResult(
        ending_equity=ending_equity if ending_equity is not None else initial_cash + realized_pnl,
        realized_pnl=realized_pnl,
        trades=trades,
        locked=locked,
        max_drawdown=max_drawdown,
        win_rate_pct=win_rate_pct,
        profit_factor=profit_factor,
        total_costs=total_costs,
        closed_trade_pnls=pnls,
        closed_trades=closed_trades,
    )


def make_candidate_result(
    *,
    name: str = "candidate",
    description: str = "test candidate",
    archetype: str = "test",
    code_path: str = "quant_system.agents.strategies.OpeningRangeBreakoutAgent",
    realized_pnl: float = 15.0,
    profit_factor: float = 1.4,
    closed_trades: int = 6,
    validation_pnl: float = 6.0,
    validation_profit_factor: float = 1.3,
    validation_closed_trades: int = 2,
    test_pnl: float = 5.0,
    test_profit_factor: float = 1.2,
    test_closed_trades: int = 2,
    walk_forward_windows: int = 1,
    walk_forward_pass_rate_pct: float = 50.0,
    walk_forward_avg_validation_pnl: float = 3.0,
    walk_forward_avg_test_pnl: float = 2.5,
    best_regime: str = "trend_up_vol_high",
    best_regime_pnl: float = 8.0,
    regime_stability_score: float = 0.7,
    regime_loss_ratio: float = 0.4,
    best_trade_share_pct: float = 20.0,
    equity_quality_score: float = 0.7,
    mc_simulations: int = 500,
    mc_pnl_p05: float = 2.0,
    mc_loss_probability_pct: float = 0.0,
    strategy_family: str = "opening_range_breakout",
    direction_mode: str = "long_only",
    direction_role: str = "long_leg",
    interpreter_fit_score: float = 0.82,
    common_live_regime_fit: float = 0.66,
    blocked_by_interpreter_risk: float = 0.18,
) -> CandidateResult:
    return CandidateResult(
        name=name,
        description=description,
        archetype=archetype,
        code_path=code_path,
        realized_pnl=realized_pnl,
        closed_trades=closed_trades,
        win_rate_pct=50.0,
        profit_factor=profit_factor,
        max_drawdown_pct=5.0,
        total_costs=100.0,
        validation_pnl=validation_pnl,
        validation_profit_factor=validation_profit_factor,
        validation_closed_trades=validation_closed_trades,
        test_pnl=test_pnl,
        test_profit_factor=test_profit_factor,
        test_closed_trades=test_closed_trades,
        walk_forward_windows=walk_forward_windows,
        walk_forward_pass_rate_pct=walk_forward_pass_rate_pct,
        walk_forward_avg_validation_pnl=walk_forward_avg_validation_pnl,
        walk_forward_avg_test_pnl=walk_forward_avg_test_pnl,
        best_regime=best_regime,
        best_regime_pnl=best_regime_pnl,
        regime_stability_score=regime_stability_score,
        regime_loss_ratio=regime_loss_ratio,
        best_trade_share_pct=best_trade_share_pct,
        equity_quality_score=equity_quality_score,
        mc_simulations=mc_simulations,
        mc_pnl_p05=mc_pnl_p05,
        mc_loss_probability_pct=mc_loss_probability_pct,
        strategy_family=strategy_family,
        direction_mode=direction_mode,
        direction_role=direction_role,
        prop_fit_score=0.85,
        prop_fit_label="pass",
        interpreter_fit_score=interpreter_fit_score,
        common_live_regime_fit=common_live_regime_fit,
        blocked_by_interpreter_risk=blocked_by_interpreter_risk,
    )


def make_candidate_row(**overrides: object) -> dict[str, object]:
    base = {
        "candidate_name": "opening_range_breakout",
        "symbol": "EURUSD",
        "code_path": "quant_system.agents.strategies.OpeningRangeBreakoutAgent",
        "description": "test candidate",
        "archetype": "test",
        "strategy_family": "opening_range_breakout",
        "direction_mode": "long_only",
        "direction_role": "long_leg",
        "realized_pnl": 15.0,
        "profit_factor": 1.4,
        "closed_trades": 6,
        "validation_pnl": 6.0,
        "validation_profit_factor": 1.3,
        "validation_closed_trades": 2,
        "test_pnl": 5.0,
        "test_profit_factor": 1.2,
        "test_closed_trades": 2,
        "walk_forward_windows": 1,
        "walk_forward_pass_rate_pct": 50.0,
        "walk_forward_soft_pass_rate_pct": 50.0,
        "walk_forward_avg_validation_pnl": 3.0,
        "walk_forward_avg_test_pnl": 2.5,
        "best_regime": "trend_up_vol_high",
        "best_regime_pnl": 8.0,
        "regime_stability_score": 0.7,
        "regime_loss_ratio": 0.4,
        "best_trade_share_pct": 20.0,
        "equity_quality_score": 0.7,
        "combo_outperformance_score": 0.0,
        "combo_trade_overlap_pct": 0.0,
        "component_count": 1,
        "mc_simulations": 500,
        "mc_pnl_p05": 2.0,
        "mc_loss_probability_pct": 0.0,
        "regime_trade_count_by_label": {"trend_up_vol_high": 2},
        "regime_pf_by_label": {"trend_up_vol_high": 1.4},
        "regime_specialist_viable": False,
        "promotion_tier": "core",
        "recommended": False,
        "variant_label": "",
        "regime_filter_label": "",
        "execution_overrides": {},
        "signal_quality_score": 0.82,
        "prop_viability_score": 0.79,
        "prop_viability_label": "pass",
        "prop_viability_pass": True,
        "prop_viability_reasons": (),
        "prop_fit_score": 0.85,
        "prop_fit_label": "pass",
        "prop_fit_reasons": (),
        "news_window_trade_share": 0.0,
        "sub_short_hold_share": 0.0,
        "micro_target_risk_flag": False,
        "execution_dependency_flag": False,
        "interpreter_fit_score": 0.82,
        "common_live_regime_fit": 0.66,
        "blocked_by_interpreter_risk": 0.18,
        "interpreter_fit_reasons": (),
    }
    base.update(overrides)
    return base
