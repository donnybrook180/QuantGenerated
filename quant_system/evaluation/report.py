from __future__ import annotations

from dataclasses import dataclass

from quant_system.config import FTMOEvaluationConfig, InstrumentConfig, RiskConfig
from quant_system.execution.engine import ExecutionResult
from quant_system.venues import get_venue_profile


@dataclass(slots=True)
class EvaluationReport:
    net_return_pct: float
    max_drawdown_pct: float
    target_return_pct: float
    profit_target_reached: bool
    win_rate_pct: float
    profit_factor: float
    total_costs: float
    closed_trades: int
    passed: bool
    reasons: list[str]


def build_ftmo_report(
    result: ExecutionResult,
    initial_cash: float,
    risk: RiskConfig,
    ftmo: FTMOEvaluationConfig,
    instrument: InstrumentConfig,
    venue_key: str = "ftmo",
) -> EvaluationReport:
    del instrument
    net_return_pct = ((result.ending_equity / initial_cash) - 1.0) * 100.0
    max_drawdown_pct = result.max_drawdown * 100.0
    reasons: list[str] = []
    venue_rules = get_venue_profile(venue_key).rules
    drawdown_limit_pct = float(
        venue_rules.total_drawdown_limit_pct if venue_rules.total_drawdown_limit_pct is not None else risk.max_total_drawdown_pct
    )
    target_return_pct = float(
        (venue_rules.profit_target_pct if venue_rules.profit_target_pct is not None else ftmo.profit_target_pct) * 100.0
    )
    profit_target_reached = net_return_pct >= target_return_pct

    if max_drawdown_pct > drawdown_limit_pct * 100.0:
        reasons.append(f"max drawdown breached ({max_drawdown_pct:.2f}% > {drawdown_limit_pct * 100.0:.2f}%)")
    if result.win_rate_pct < ftmo.min_win_rate_pct:
        reasons.append(f"win rate too low ({result.win_rate_pct:.2f}% < {ftmo.min_win_rate_pct:.2f}%)")
    if result.profit_factor < ftmo.min_profit_factor:
        reasons.append(f"profit factor too low ({result.profit_factor:.2f} < {ftmo.min_profit_factor:.2f})")
    if len(result.closed_trade_pnls) < ftmo.min_trades:
        reasons.append(f"too few closed trades ({len(result.closed_trade_pnls)} < {ftmo.min_trades})")
    if result.locked:
        reasons.append("kill-switch triggered")

    return EvaluationReport(
        net_return_pct=net_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        target_return_pct=target_return_pct,
        profit_target_reached=profit_target_reached,
        win_rate_pct=result.win_rate_pct,
        profit_factor=result.profit_factor,
        total_costs=result.total_costs,
        closed_trades=len(result.closed_trade_pnls),
        passed=not reasons,
        reasons=reasons,
    )
