from __future__ import annotations

import json

from quant_system.symbols import (
    is_crypto_symbol as symbol_is_crypto,
    is_metal_symbol as symbol_is_metal,
    is_stock_symbol as symbol_is_stock,
)


def row_value(row: object | dict[str, object], field_name: str, default: object = None) -> object:
    if isinstance(row, dict):
        return row.get(field_name, default)
    return getattr(row, field_name, default)


def research_thresholds(symbol: str) -> dict[str, float | int]:
    if symbol.upper() == "US100":
        return {
            "validation_closed_trades": 3,
            "test_closed_trades": 0,
            "min_profit_factor": 1.0,
            "walk_forward_min_windows": 1,
            "walk_forward_min_pass_rate_pct": 0.0,
            "sparse_max_closed_trades": 20,
            "sparse_min_payoff_ratio": 1.6,
            "sparse_combined_closed_trades": 3,
            "sparse_walk_forward_min_pass_rate_pct": 0.0,
            "core_use_combined_splits": 1,
            "core_combined_closed_trades": 4,
            "core_allow_positive_validation_only": 1,
        }
    if symbol.upper() == "EURUSD":
        return {
            "validation_closed_trades": 1,
            "test_closed_trades": 1,
            "min_profit_factor": 1.0,
            "walk_forward_min_windows": 1,
            "walk_forward_min_pass_rate_pct": 0.0,
            "sparse_max_closed_trades": 18,
            "sparse_min_payoff_ratio": 1.5,
            "sparse_combined_closed_trades": 2,
            "sparse_walk_forward_min_pass_rate_pct": 0.0,
            "core_use_combined_splits": 1,
            "core_combined_closed_trades": 2,
            "core_allow_positive_validation_only": 0,
        }
    if symbol.upper() == "GBPUSD":
        return {
            "validation_closed_trades": 1,
            "test_closed_trades": 0,
            "min_profit_factor": 1.0,
            "walk_forward_min_windows": 1,
            "walk_forward_min_pass_rate_pct": 0.0,
            "sparse_max_closed_trades": 12,
            "sparse_min_payoff_ratio": 1.5,
            "sparse_combined_closed_trades": 0,
            "sparse_walk_forward_min_pass_rate_pct": 0.0,
            "core_use_combined_splits": 1,
            "core_combined_closed_trades": 2,
            "core_allow_positive_validation_only": 0,
        }
    if symbol.upper() == "US500":
        return {
            "validation_closed_trades": 2,
            "test_closed_trades": 1,
            "min_profit_factor": 1.0,
            "walk_forward_min_windows": 1,
            "walk_forward_min_pass_rate_pct": 0.0,
            "sparse_max_closed_trades": 18,
            "sparse_min_payoff_ratio": 1.6,
            "sparse_combined_closed_trades": 2,
            "sparse_walk_forward_min_pass_rate_pct": 0.0,
            "core_use_combined_splits": 1,
            "core_combined_closed_trades": 3,
            "core_allow_positive_validation_only": 1,
        }
    if symbol_is_crypto(symbol):
        return {
            "validation_closed_trades": 2,
            "test_closed_trades": 1,
            "min_profit_factor": 1.0,
            "walk_forward_min_windows": 1,
            "walk_forward_min_pass_rate_pct": 40.0,
            "sparse_max_closed_trades": 20,
            "sparse_min_payoff_ratio": 1.75,
            "sparse_combined_closed_trades": 2,
            "sparse_walk_forward_min_pass_rate_pct": 25.0,
        }
    if symbol_is_stock(symbol):
        return {
            "validation_closed_trades": 1,
            "test_closed_trades": 1,
            "min_profit_factor": 1.0,
            "walk_forward_min_windows": 1,
            "walk_forward_min_pass_rate_pct": 20.0,
            "sparse_max_closed_trades": 24,
            "sparse_min_payoff_ratio": 1.75,
            "sparse_combined_closed_trades": 2,
            "sparse_walk_forward_min_pass_rate_pct": 15.0,
        }
    return {
        "validation_closed_trades": 3,
        "test_closed_trades": 2,
        "min_profit_factor": 1.0,
        "walk_forward_min_windows": 1,
        "walk_forward_min_pass_rate_pct": 50.0,
        "sparse_max_closed_trades": 18,
        "sparse_min_payoff_ratio": 1.75,
        "sparse_combined_closed_trades": 2,
        "sparse_walk_forward_min_pass_rate_pct": 25.0,
    }


def is_sparse_candidate(row: object | dict[str, object], symbol: str) -> bool:
    thresholds = research_thresholds(symbol)
    closed_trades = int(row_value(row, "closed_trades", 0) or 0)
    payoff_ratio = float(row_value(row, "payoff_ratio", 0.0) or 0.0)
    profit_factor = float(row_value(row, "profit_factor", 0.0) or 0.0)
    return (
        closed_trades > 0
        and closed_trades <= int(thresholds["sparse_max_closed_trades"])
        and payoff_ratio >= float(thresholds["sparse_min_payoff_ratio"])
        and profit_factor >= float(thresholds["min_profit_factor"])
    )


def metric_map_from_row(row: object | dict[str, object], field_name: str) -> dict[str, float]:
    raw = row_value(row, field_name, "{}")
    if isinstance(raw, dict):
        payload = raw
    else:
        try:
            payload = json.loads(str(raw or "{}"))
        except json.JSONDecodeError:
            return {}
    result: dict[str, float] = {}
    for key, value in payload.items():
        try:
            result[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return result


def meets_monte_carlo_viability(row: object | dict[str, object]) -> bool:
    mc_simulations = int(row_value(row, "mc_simulations", 0) or 0)
    mc_pnl_p05 = float(row_value(row, "mc_pnl_p05", 0.0) or 0.0)
    mc_loss_probability_pct = float(row_value(row, "mc_loss_probability_pct", 0.0) or 0.0)
    return mc_simulations > 0 and mc_pnl_p05 > 0.0 and mc_loss_probability_pct <= 10.0


def infer_strategy_family_name(candidate_name: str, code_path: str) -> str:
    explicit = {
        "quant_system.agents.strategies.OpeningRangeBreakoutAgent": "opening_range_breakout",
        "quant_system.agents.strategies.OpeningRangeShortBreakdownAgent": "opening_range_breakout",
        "quant_system.agents.strategies.VolatilityBreakoutAgent": "volatility_breakout",
        "quant_system.agents.strategies.VolatilityShortBreakdownAgent": "volatility_breakout",
        "quant_system.agents.crypto.CryptoTrendPullbackAgent": "crypto_trend_pullback",
    }
    if code_path in explicit:
        return explicit[code_path]
    lowered = candidate_name.strip().lower()
    if "opening_range" in lowered:
        return "opening_range_breakout"
    if "volatility" in lowered:
        return "volatility_breakout"
    return lowered


def infer_direction_mode(candidate_name: str, code_path: str) -> str:
    lowered = f"{candidate_name} {code_path}".lower()
    if "short" in lowered or "downside" in lowered or "breakdown" in lowered:
        return "short_only"
    if "trendagent" in lowered or "meanreversionagent" in lowered or "momentumconfirmationagent" in lowered:
        return "both"
    return "long_only"


def infer_direction_role(direction_mode_value: str) -> str:
    if direction_mode_value == "short_only":
        return "short_leg"
    if direction_mode_value == "both":
        return "combined"
    return "long_leg"


def strategy_family(row: object | dict[str, object]) -> str:
    explicit = str(row_value(row, "strategy_family", "") or "").strip()
    if explicit:
        return explicit
    candidate_name = str(row_value(row, "name", row_value(row, "candidate_name", "")) or "")
    code_path = str(row_value(row, "code_path", "") or "")
    return infer_strategy_family_name(candidate_name, code_path)


def direction_mode(row: object | dict[str, object]) -> str:
    explicit = str(row_value(row, "direction_mode", "") or "").strip()
    if explicit:
        return explicit
    candidate_name = str(row_value(row, "name", row_value(row, "candidate_name", "")) or "")
    code_path = str(row_value(row, "code_path", "") or "")
    return infer_direction_mode(candidate_name, code_path)


def direction_role(row: object | dict[str, object]) -> str:
    explicit = str(row_value(row, "direction_role", "") or "").strip()
    if explicit:
        return explicit
    return infer_direction_role(direction_mode(row))


def family_unused_for_single_selection(row: dict[str, object], used_families: set[str]) -> bool:
    family = str(row.get("strategy_family", "") or "").strip()
    return not family or family not in used_families


def component_set(code_path: str) -> set[str]:
    return {part.strip() for part in code_path.split(";") if part.strip()}


def component_names(candidate_name: str) -> list[str]:
    return [part.strip() for part in candidate_name.split("__plus__") if part.strip()]

