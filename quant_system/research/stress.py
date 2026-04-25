from __future__ import annotations

from quant_system.symbols import (
    is_crypto_symbol,
    is_forex_symbol,
    is_index_symbol,
    is_metal_symbol,
)


def _stress_cost_multipliers(symbol: str) -> tuple[float, float, float]:
    upper = symbol.upper()
    if is_crypto_symbol(upper):
        return 0.35, 0.75, 1.25
    if is_metal_symbol(upper):
        return 0.25, 0.55, 1.00
    if is_index_symbol(upper):
        return 0.20, 0.50, 0.95
    if is_forex_symbol(upper):
        return 0.15, 0.35, 0.70
    return 0.20, 0.50, 1.00


def _stressed_profit_factor(
    *,
    expectancy: float,
    profit_factor: float,
    closed_trades: int,
    avg_loss: float,
    extra_cost_per_trade: float,
) -> float:
    if closed_trades <= 0:
        return 0.0
    extra_total_cost = max(extra_cost_per_trade, 0.0) * float(closed_trades)
    if profit_factor > 1.0 and expectancy > 0.0:
        gross_loss_total = (float(closed_trades) * expectancy) / (profit_factor - 1.0)
        gross_profit_total = gross_loss_total * profit_factor
        stressed_loss_total = gross_loss_total + extra_total_cost
        if stressed_loss_total <= 0.0:
            return 999.0 if gross_profit_total > 0.0 else 0.0
        return max(0.0, gross_profit_total / stressed_loss_total)
    loss_scale = max(abs(avg_loss), 1.0)
    return max(0.0, profit_factor - (extra_cost_per_trade / loss_scale))


def estimate_execution_stress(
    *,
    symbol: str,
    expectancy: float,
    profit_factor: float,
    total_costs: float,
    closed_trades: int,
    avg_loss: float,
) -> dict[str, float]:
    if closed_trades <= 0:
        return {
            "stress_expectancy_mild": 0.0,
            "stress_expectancy_medium": 0.0,
            "stress_expectancy_harsh": 0.0,
            "stress_pf_mild": 0.0,
            "stress_pf_medium": 0.0,
            "stress_pf_harsh": 0.0,
            "stress_survival_score": 0.0,
        }

    baseline_cost_per_trade = max(float(total_costs), 0.0) / float(closed_trades)
    mild_multiplier, medium_multiplier, harsh_multiplier = _stress_cost_multipliers(symbol)
    extra_mild = baseline_cost_per_trade * mild_multiplier
    extra_medium = baseline_cost_per_trade * medium_multiplier
    extra_harsh = baseline_cost_per_trade * harsh_multiplier

    stress_expectancy_mild = expectancy - extra_mild
    stress_expectancy_medium = expectancy - extra_medium
    stress_expectancy_harsh = expectancy - extra_harsh
    stress_pf_mild = _stressed_profit_factor(
        expectancy=expectancy,
        profit_factor=profit_factor,
        closed_trades=closed_trades,
        avg_loss=avg_loss,
        extra_cost_per_trade=extra_mild,
    )
    stress_pf_medium = _stressed_profit_factor(
        expectancy=expectancy,
        profit_factor=profit_factor,
        closed_trades=closed_trades,
        avg_loss=avg_loss,
        extra_cost_per_trade=extra_medium,
    )
    stress_pf_harsh = _stressed_profit_factor(
        expectancy=expectancy,
        profit_factor=profit_factor,
        closed_trades=closed_trades,
        avg_loss=avg_loss,
        extra_cost_per_trade=extra_harsh,
    )
    survival_weights = (
        (0.40, stress_expectancy_mild > 0.0 and stress_pf_mild >= 1.0),
        (0.35, stress_expectancy_medium > 0.0 and stress_pf_medium >= 1.0),
        (0.25, stress_expectancy_harsh > 0.0 and stress_pf_harsh >= 1.0),
    )
    stress_survival_score = sum(weight for weight, passed in survival_weights if passed)
    return {
        "stress_expectancy_mild": stress_expectancy_mild,
        "stress_expectancy_medium": stress_expectancy_medium,
        "stress_expectancy_harsh": stress_expectancy_harsh,
        "stress_pf_mild": stress_pf_mild,
        "stress_pf_medium": stress_pf_medium,
        "stress_pf_harsh": stress_pf_harsh,
        "stress_survival_score": stress_survival_score,
    }
