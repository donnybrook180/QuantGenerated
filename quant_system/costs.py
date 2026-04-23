from __future__ import annotations

from dataclasses import dataclass

from quant_system.ai.storage import ExperimentStore
from quant_system.config import SystemConfig
from quant_system.integrations.mt5 import MT5Client, MT5Error


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


@dataclass(frozen=True, slots=True)
class CostCalibration:
    spread_points: float
    slippage_bps: float
    source: str
    notes: str


def _is_forex_symbol(symbol: str) -> bool:
    upper = symbol.upper()
    return upper.endswith("USD") or upper.endswith("JPY") or upper.startswith("EUR") or upper.startswith("GBP") or upper.startswith("AUD")


def _prop_broker_family(config: SystemConfig | None) -> str:
    if config is None:
        return "generic"
    broker = str(getattr(config.mt5, "prop_broker", "") or "").strip().lower()
    return broker or "generic"


def resolve_prop_cost_profile(symbol: str, broker_family: str = "generic") -> CostProfile:
    upper = symbol.upper()
    broker = broker_family.strip().lower()
    broker_label = {
        "ftmo": "FTMO",
        "fundednext": "FundedNext",
        "blue_guardian": "Blue Guardian",
    }.get(broker, "Generic prop")
    if any(code in upper for code in ("XAU", "XAG", "XPD", "XPT", "XCU")):
        spread_points = 0.25
        contract_size = 100.0
        if "XAG" in upper:
            spread_points = 0.03
            contract_size = 5_000.0
        elif "XPD" in upper or "XPT" in upper:
            spread_points = 0.8
        elif "XCU" in upper:
            spread_points = 0.02
            contract_size = 1_000.0
        return CostProfile(
            contract_size=contract_size,
            spread_points=spread_points,
            slippage_bps=0.8 if broker != "fundednext" else 1.0,
            commission_mode="notional_pct",
            commission_per_lot=0.0,
            commission_notional_pct=0.0007 if broker != "blue_guardian" else 0.0008,
            fee_bps=0.0,
            overnight_cost_per_lot_day=0.0,
            notes=f"{broker_label} metals model with metal-specific contract sizing and conservative spread assumptions.",
        )
    if "BTC" in upper:
        return CostProfile(
            contract_size=1.0,
            spread_points=20.0,
            slippage_bps=1.5 if broker != "fundednext" else 2.0,
            commission_mode="notional_pct",
            commission_per_lot=0.0,
            commission_notional_pct=0.0325,
            fee_bps=0.0,
            overnight_cost_per_lot_day=0.0,
            notes=f"{broker_label} crypto model: 0.0325% per side, contract size 1 for BTCUSD; spread is a conservative inference.",
        )
    if "ETH" in upper:
        return CostProfile(
            contract_size=10.0,
            spread_points=3.0,
            slippage_bps=4.0 if broker != "fundednext" else 4.5,
            commission_mode="notional_pct",
            commission_per_lot=0.0,
            commission_notional_pct=0.0325,
            fee_bps=0.0,
            overnight_cost_per_lot_day=0.0,
            notes=f"{broker_label} crypto model: 0.0325% per side, contract size 10 for ETHUSD; spread/slippage slightly inflated to reflect observed MT5-vs-Binance intraday divergence.",
        )
    if upper in {"GER40", "GER40.CASH", "DAX", "SX5E", "EU50", "EU50.CASH", "ESTX50", "JP225", "JP225.CASH", "JPN225", "NK225", "HK50", "HK50.CASH", "HSI50", "HANGSENG", "US500", "US500.CASH", "SPY", "US100", "US100.CASH", "QQQ"}:
        spread_points = 1.0
        if "US500" in upper or upper == "SPY":
            spread_points = 0.5
        if "US100" in upper or upper == "QQQ":
            spread_points = 1.0
        return CostProfile(
            contract_size=1.0,
            spread_points=spread_points,
            slippage_bps=0.5 if broker != "blue_guardian" else 0.75,
            commission_mode="none",
            commission_per_lot=0.0,
            commission_notional_pct=0.0,
            fee_bps=0.0,
            overnight_cost_per_lot_day=0.0,
            notes=f"{broker_label} index CFD model: no direct commission, spread modeled conservatively.",
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
            slippage_bps=0.25 if broker != "fundednext" else 0.35,
            commission_mode="per_lot",
            commission_per_lot=2.5 if broker != "blue_guardian" else 3.0,
            commission_notional_pct=0.0,
            fee_bps=0.0,
            overnight_cost_per_lot_day=0.0,
            notes=f"{broker_label} forex model: per-lot commission with conservative spread assumptions.",
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
        notes=f"{broker_label} fallback generic cost model.",
    )


def resolve_ftmo_cost_profile(symbol: str) -> CostProfile:
    return resolve_prop_cost_profile(symbol, "ftmo")


def calibrate_cost_profile_with_mt5(config: SystemConfig, symbol: str, broker_symbol: str | None, profile: CostProfile) -> CostProfile:
    target_symbol = (broker_symbol or config.mt5.symbol or symbol).strip()
    if not target_symbol:
        return profile
    fill_calibration = ExperimentStore(config.ai.experiment_database_path, read_only=True).load_mt5_fill_calibration(target_symbol)
    if fill_calibration is not None:
        calibrated_spread = max(profile.spread_points, float(fill_calibration["median_spread_points"]) * 1.05)
        calibrated_slippage = max(profile.slippage_bps, float(fill_calibration["p75_slippage_bps"]) * 1.1)
        return CostProfile(
            contract_size=profile.contract_size,
            spread_points=calibrated_spread,
            slippage_bps=calibrated_slippage,
            commission_mode=profile.commission_mode,
            commission_per_lot=profile.commission_per_lot,
            commission_notional_pct=profile.commission_notional_pct,
            fee_bps=profile.fee_bps,
            overnight_cost_per_lot_day=profile.overnight_cost_per_lot_day,
            notes=(
                profile.notes
                + f" MT5 fill calibration applied from {target_symbol}: fills={int(fill_calibration['count'])},"
                + f" median_spread={float(fill_calibration['median_spread_points']):.6f},"
                + f" p75_slippage_bps={float(fill_calibration['p75_slippage_bps']):.3f}."
            ),
        )
    mt5_config = config.mt5
    mt5_config.symbol = target_symbol
    client = MT5Client(mt5_config)
    try:
        client.initialize()
        snapshot = client.market_snapshot()
    except MT5Error:
        return profile
    finally:
        try:
            client.shutdown()
        except Exception:
            pass

    mid_price = (snapshot.bid + snapshot.ask) / 2.0 if snapshot.bid > 0 and snapshot.ask > 0 else 0.0
    if mid_price <= 0.0:
        return profile

    observed_spread = max(snapshot.spread_points, 0.0)
    spread_bps = (observed_spread / mid_price) * 10_000 if observed_spread > 0.0 else 0.0
    calibrated_spread = max(profile.spread_points, observed_spread * 1.05)
    calibrated_slippage = max(profile.slippage_bps, min(25.0, spread_bps * 0.5))
    if calibrated_spread == profile.spread_points and calibrated_slippage == profile.slippage_bps:
        return profile

    return CostProfile(
        contract_size=profile.contract_size,
        spread_points=calibrated_spread,
        slippage_bps=calibrated_slippage,
        commission_mode=profile.commission_mode,
        commission_per_lot=profile.commission_per_lot,
        commission_notional_pct=profile.commission_notional_pct,
        fee_bps=profile.fee_bps,
        overnight_cost_per_lot_day=profile.overnight_cost_per_lot_day,
        notes=profile.notes + f" MT5 calibration applied from {snapshot.symbol}: spread={observed_spread:.6f}, spread_bps={spread_bps:.3f}.",
    )


def apply_prop_cost_profile(config: SystemConfig, symbol: str, broker_symbol: str | None = None) -> CostProfile:
    profile = resolve_prop_cost_profile(symbol, _prop_broker_family(config))
    profile = calibrate_cost_profile_with_mt5(config, symbol, broker_symbol, profile)
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


def apply_ftmo_cost_profile(config: SystemConfig, symbol: str, broker_symbol: str | None = None) -> CostProfile:
    return apply_prop_cost_profile(config, symbol, broker_symbol)
