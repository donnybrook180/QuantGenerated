from __future__ import annotations

from dataclasses import dataclass

from quant_system.config import SystemConfig


@dataclass(frozen=True, slots=True)
class CostProfile:
    contract_size: float
    spread_points: float
    slippage_bps: float
    commission_mode: str
    commission_per_lot: float
    commission_notional_pct: float
    fee_bps: float
    overnight_cost_per_lot_day: float
    notes: str


def _is_forex_symbol(symbol: str) -> bool:
    upper = symbol.upper()
    return upper.endswith("USD") or upper.endswith("JPY") or upper.startswith("EUR") or upper.startswith("GBP") or upper.startswith("AUD")


def resolve_ftmo_cost_profile(symbol: str) -> CostProfile:
    upper = symbol.upper()
    if "BTC" in upper:
        return CostProfile(
            contract_size=1.0,
            spread_points=20.0,
            slippage_bps=1.5,
            commission_mode="notional_pct",
            commission_per_lot=0.0,
            commission_notional_pct=0.0325,
            fee_bps=0.0,
            overnight_cost_per_lot_day=0.0,
            notes="FTMO crypto model: 0.0325% per side, contract size 1 for BTCUSD; spread is a conservative inference.",
        )
    if "ETH" in upper:
        return CostProfile(
            contract_size=10.0,
            spread_points=3.0,
            slippage_bps=4.0,
            commission_mode="notional_pct",
            commission_per_lot=0.0,
            commission_notional_pct=0.0325,
            fee_bps=0.0,
            overnight_cost_per_lot_day=0.0,
            notes="FTMO crypto model: 0.0325% per side, contract size 10 for ETHUSD; spread/slippage slightly inflated to reflect observed MT5-vs-Binance intraday divergence.",
        )
    if "XAU" in upper:
        return CostProfile(
            contract_size=100.0,
            spread_points=0.25,
            slippage_bps=0.8,
            commission_mode="notional_pct",
            commission_per_lot=0.0,
            commission_notional_pct=0.0007,
            fee_bps=0.0,
            overnight_cost_per_lot_day=0.0,
            notes="FTMO metals model: 0.0007% per side; contract size 100 follows standard metal CFD convention; spread is a conservative inference.",
        )
    if upper in {"GER40", "GER40.CASH", "DAX", "US500", "US500.CASH", "SPY", "US100", "US100.CASH", "QQQ"}:
        spread_points = 1.0
        if "US500" in upper or upper == "SPY":
            spread_points = 0.5
        if "US100" in upper or upper == "QQQ":
            spread_points = 1.0
        return CostProfile(
            contract_size=1.0,
            spread_points=spread_points,
            slippage_bps=0.5,
            commission_mode="none",
            commission_per_lot=0.0,
            commission_notional_pct=0.0,
            fee_bps=0.0,
            overnight_cost_per_lot_day=0.0,
            notes="FTMO index CFD model: no direct commission, spread modeled conservatively.",
        )
    if _is_forex_symbol(upper):
        spread_points = 0.00008
        if upper.endswith("JPY"):
            spread_points = 0.008
        elif upper.startswith("GBP"):
            spread_points = 0.00012
        elif upper.startswith("AUD"):
            spread_points = 0.00010
        return CostProfile(
            contract_size=100_000.0,
            spread_points=spread_points,
            slippage_bps=0.25,
            commission_mode="per_lot",
            commission_per_lot=2.5,
            commission_notional_pct=0.0,
            fee_bps=0.0,
            overnight_cost_per_lot_day=0.0,
            notes="FTMO forex model: $2.50 per lot per side; spread is a conservative inference.",
        )
    return CostProfile(
        contract_size=1.0,
        spread_points=0.0,
        slippage_bps=2.0,
        commission_mode="legacy",
        commission_per_lot=0.0,
        commission_notional_pct=0.0,
        fee_bps=1.0,
        overnight_cost_per_lot_day=0.0,
        notes="Fallback generic cost model.",
    )


def apply_ftmo_cost_profile(config: SystemConfig, symbol: str) -> CostProfile:
    profile = resolve_ftmo_cost_profile(symbol)
    config.execution.contract_size = profile.contract_size
    config.execution.spread_points = profile.spread_points
    config.execution.slippage_bps = profile.slippage_bps
    config.execution.commission_mode = profile.commission_mode
    config.execution.commission_per_lot = profile.commission_per_lot
    config.execution.commission_notional_pct = profile.commission_notional_pct
    config.execution.fee_bps = profile.fee_bps
    config.execution.overnight_cost_per_lot_day = profile.overnight_cost_per_lot_day
    if profile.commission_mode != "legacy":
        config.execution.commission_per_unit = 0.0
    return profile
