from __future__ import annotations

import asyncio
import csv
import itertools
from dataclasses import dataclass
from pathlib import Path

from quant_system.ai.models import AgentDescriptor
from quant_system.ai.storage import ExperimentStore
from quant_system.agents.base import Agent
from quant_system.agents.strategies import OpeningRangeBreakoutAgent, VolatilityBreakoutAgent
from quant_system.agents.trend import MeanReversionAgent, MomentumConfirmationAgent, RiskSentinelAgent, TrendAgent
from quant_system.agents.xauusd import XAUUSDVolatilityBreakoutAgent
from quant_system.config import SystemConfig
from quant_system.data.market_data import DuckDBMarketDataStore
from quant_system.execution.broker import SimulatedBroker
from quant_system.execution.engine import AgentCoordinator, EventDrivenEngine, ExecutionResult
from quant_system.integrations.polygon_data import PolygonDataClient, PolygonError
from quant_system.models import FeatureVector, MarketBar
from quant_system.monitoring.heartbeat import HeartbeatMonitor
from quant_system.research.features import build_feature_library
from quant_system.risk.limits import RiskManager


ARTIFACTS_DIR = Path("artifacts")


@dataclass(slots=True)
class CandidateSpec:
    name: str
    description: str
    agents: list[Agent]
    code_path: str


@dataclass(slots=True)
class CandidateResult:
    name: str
    description: str
    archetype: str
    code_path: str
    realized_pnl: float
    closed_trades: int
    win_rate_pct: float
    profit_factor: float
    max_drawdown_pct: float
    total_costs: float


def _symbol_slug(symbol: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in symbol).strip("_")


def _build_engine(config: SystemConfig, agents: list[Agent]) -> EventDrivenEngine:
    broker = SimulatedBroker(
        initial_cash=config.execution.initial_cash,
        fee_bps=config.execution.fee_bps,
        commission_per_unit=config.execution.commission_per_unit,
        slippage_bps=config.execution.slippage_bps,
    )
    engine = EventDrivenEngine(
        coordinator=AgentCoordinator(agents, consensus_min_confidence=config.agents.consensus_min_confidence),
        broker=broker,
        risk_manager=RiskManager(config=config.risk, starting_equity=config.execution.initial_cash),
        heartbeat=HeartbeatMonitor(config.heartbeat),
        quantity=config.execution.order_size,
    )
    engine.min_bars_between_trades = config.execution.min_bars_between_trades
    engine.max_holding_bars = config.execution.max_holding_bars
    engine.stop_loss_atr_multiple = config.execution.stop_loss_atr_multiple
    engine.take_profit_atr_multiple = config.execution.take_profit_atr_multiple
    engine.break_even_atr_multiple = config.execution.break_even_atr_multiple
    engine.trailing_stop_atr_multiple = config.execution.trailing_stop_atr_multiple
    engine.stale_breakout_bars = config.execution.stale_breakout_bars
    engine.stale_breakout_atr_fraction = config.execution.stale_breakout_atr_fraction
    engine.structure_exit_bars = config.execution.structure_exit_bars
    return engine


def _configure_symbol_execution(config: SystemConfig, symbol: str) -> None:
    upper = symbol.upper()
    if "XAU" in upper:
        config.execution.min_bars_between_trades = 30
        config.execution.max_holding_bars = 18
        config.execution.stop_loss_atr_multiple = 1.4
        config.execution.take_profit_atr_multiple = 2.4
        config.execution.break_even_atr_multiple = 0.45
        config.execution.trailing_stop_atr_multiple = 0.85
        config.execution.stale_breakout_bars = 6
        config.execution.stale_breakout_atr_fraction = 0.2
        config.execution.structure_exit_bars = 4
    else:
        config.execution.min_bars_between_trades = 12
        config.execution.max_holding_bars = 24
        config.execution.stop_loss_atr_multiple = 1.2
        config.execution.take_profit_atr_multiple = 2.4
        config.execution.break_even_atr_multiple = 0.8
        config.execution.trailing_stop_atr_multiple = 1.0
        config.execution.stale_breakout_bars = 5
        config.execution.stale_breakout_atr_fraction = 0.1
        config.execution.structure_exit_bars = 3


def _load_symbol_features(config: SystemConfig, data_symbol: str) -> tuple[list[FeatureVector], str]:
    config.polygon.symbol = data_symbol
    store = DuckDBMarketDataStore(config.mt5.database_path)
    timeframe = f"{config.polygon.multiplier}_{config.polygon.timespan}"
    scoped_timeframe = f"symbol_research_{_symbol_slug(data_symbol)}_{timeframe}"

    if config.polygon.fetch_policy in {"cache_first", "cache_only"}:
        cached = store.load_bars(data_symbol, scoped_timeframe, 50_000)
        if cached:
            return build_feature_library(cached), "duckdb_cache"
        if config.polygon.fetch_policy == "cache_only":
            raise RuntimeError(f"No cached DuckDB bars available for {data_symbol}/{scoped_timeframe}.")

    try:
        client = PolygonDataClient(config.polygon)
        bars = client.fetch_bars()
        store.upsert_bars(bars, timeframe=scoped_timeframe, source="polygon")
        persisted = store.load_bars(data_symbol, scoped_timeframe, len(bars))
        if not persisted:
            raise RuntimeError(f"No Polygon bars were loaded into DuckDB for {data_symbol}.")
        return build_feature_library(persisted), "polygon"
    except PolygonError:
        cached = store.load_bars(data_symbol, scoped_timeframe, 50_000)
        if cached:
            return build_feature_library(cached), "duckdb_cache"
        raise


def _candidate_specs(config: SystemConfig, data_symbol: str) -> list[CandidateSpec]:
    risk = RiskSentinelAgent(
        max_volatility=config.risk.max_volatility,
        min_relative_volume=config.agents.min_relative_volume,
    )
    specs = [
        CandidateSpec(
            name="trend",
            description="EMA trend continuation",
            agents=[
                TrendAgent(
                    fast_window=config.agents.trend_fast_window,
                    slow_window=config.agents.trend_slow_window,
                    min_trend_strength=config.agents.min_trend_strength,
                    min_relative_volume=config.agents.min_relative_volume,
                ),
                risk,
            ],
            code_path="quant_system.agents.trend.TrendAgent",
        ),
        CandidateSpec(
            name="momentum",
            description="Momentum confirmation",
            agents=[MomentumConfirmationAgent(config.agents.mean_reversion_threshold), risk],
            code_path="quant_system.agents.trend.MomentumConfirmationAgent",
        ),
        CandidateSpec(
            name="mean_reversion",
            description="Intraday mean reversion",
            agents=[MeanReversionAgent(config.agents.mean_reversion_window, config.agents.mean_reversion_threshold), risk],
            code_path="quant_system.agents.trend.MeanReversionAgent",
        ),
        CandidateSpec(
            name="volatility_breakout",
            description="Generic volatility breakout",
            agents=[VolatilityBreakoutAgent(lookback=max(8, config.agents.mean_reversion_window)), risk],
            code_path="quant_system.agents.strategies.VolatilityBreakoutAgent",
        ),
        CandidateSpec(
            name="opening_range_breakout",
            description="Opening range breakout",
            agents=[OpeningRangeBreakoutAgent(), risk],
            code_path="quant_system.agents.strategies.OpeningRangeBreakoutAgent",
        ),
    ]
    if "XAU" in data_symbol.upper():
        specs.append(
            CandidateSpec(
                name="xauusd_volatility_breakout",
                description="XAUUSD-tuned volatility breakout",
                agents=[XAUUSDVolatilityBreakoutAgent(lookback=max(6, config.agents.mean_reversion_window)), risk],
                code_path="quant_system.agents.xauusd.XAUUSDVolatilityBreakoutAgent",
            )
        )
    return specs


def _score_result(name: str, description: str, archetype: str, code_path: str, result: ExecutionResult) -> CandidateResult:
    return CandidateResult(
        name=name,
        description=description,
        archetype=archetype,
        code_path=code_path,
        realized_pnl=result.realized_pnl,
        closed_trades=len(result.closed_trades),
        win_rate_pct=result.win_rate_pct,
        profit_factor=result.profit_factor,
        max_drawdown_pct=result.max_drawdown * 100.0,
        total_costs=result.total_costs,
    )


def _run_candidate(config: SystemConfig, features: list[FeatureVector], spec: CandidateSpec, archetype: str) -> CandidateResult:
    engine = _build_engine(config, spec.agents)
    result = asyncio.run(engine.run(features, sleep_seconds=0.0))
    return _score_result(spec.name, spec.description, archetype, spec.code_path, result)


def _combined_specs(config: SystemConfig, singles: list[CandidateSpec], winners: list[CandidateResult]) -> list[CandidateSpec]:
    lookup = {spec.name: spec for spec in singles}
    positive = [winner for winner in winners if winner.realized_pnl > 0 and winner.profit_factor >= 1.0]
    positive = sorted(positive, key=lambda item: (item.realized_pnl, item.profit_factor), reverse=True)[:3]
    combined: list[CandidateSpec] = []
    for left, right in itertools.combinations(positive, 2):
        left_spec = lookup[left.name]
        right_spec = lookup[right.name]
        combo_agents = [agent for agent in left_spec.agents if agent.name != "risk_sentinel"]
        combo_agents.extend(agent for agent in right_spec.agents if agent.name != "risk_sentinel")
        combo_agents.append(
            RiskSentinelAgent(
                max_volatility=config.risk.max_volatility,
                min_relative_volume=config.agents.min_relative_volume,
            )
        )
        combined.append(
            CandidateSpec(
                name=f"{left.name}__plus__{right.name}",
                description=f"Combined {left.name} + {right.name}",
                agents=combo_agents,
                code_path=f"{left_spec.code_path};{right_spec.code_path}",
            )
        )
    return combined


def _component_set(code_path: str) -> set[str]:
    return {part.strip() for part in code_path.split(";") if part.strip()}


def select_execution_candidates(rows: list[dict[str, object]], max_candidates: int = 2) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    used_components: set[str] = set()
    ranked = sorted(
        rows,
        key=lambda row: (
            bool(row.get("recommended")),
            float(row.get("realized_pnl", 0.0)),
            float(row.get("profit_factor", 0.0)),
            int(row.get("closed_trades", 0)),
        ),
        reverse=True,
    )
    for row in ranked:
        components = _component_set(str(row["code_path"]))
        if selected and components & used_components:
            continue
        selected.append(row)
        used_components.update(components)
        if len(selected) >= max_candidates:
            break
    return selected


def _export_results(symbol: str, broker_symbol: str, data_source: str, rows: list[CandidateResult]) -> tuple[Path, Path]:
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    slug = _symbol_slug(symbol)
    csv_path = ARTIFACTS_DIR / f"{slug}_symbol_research.csv"
    txt_path = ARTIFACTS_DIR / f"{slug}_symbol_research.txt"

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "name",
                "description",
                "archetype",
                "realized_pnl",
                "closed_trades",
                "win_rate_pct",
                "profit_factor",
                "max_drawdown_pct",
                "total_costs",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.name,
                    row.description,
                    row.archetype,
                    f"{row.realized_pnl:.5f}",
                    row.closed_trades,
                    f"{row.win_rate_pct:.5f}",
                    f"{row.profit_factor:.5f}",
                    f"{row.max_drawdown_pct:.5f}",
                    f"{row.total_costs:.5f}",
                ]
            )

    ranked = sorted(rows, key=lambda item: (item.realized_pnl, item.profit_factor, item.closed_trades), reverse=True)
    lines = [
        f"Symbol research: {symbol}",
        f"Broker symbol: {broker_symbol}",
        f"Data source: {data_source}",
        "",
        "Ranked candidates",
    ]
    for row in ranked:
        lines.append(
            f"{row.name} [{row.archetype}]: pnl={row.realized_pnl:.2f} closed={row.closed_trades} "
            f"pf={row.profit_factor:.2f} win_rate={row.win_rate_pct:.2f}% dd={row.max_drawdown_pct:.2f}%"
        )
    winners = [row for row in ranked if row.realized_pnl > 0 and row.profit_factor >= 1.0]
    lines.extend(["", "Recommended active agents"])
    if winners:
        for row in winners[:3]:
            lines.append(f"- {row.name} ({row.description})")
    else:
        lines.append("No candidate met the positive-PnL and PF>=1.0 threshold.")
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, txt_path


def run_symbol_research(data_symbol: str, broker_symbol: str | None = None) -> list[str]:
    config = SystemConfig()
    broker = broker_symbol or data_symbol
    _configure_symbol_execution(config, data_symbol)
    features, data_source = _load_symbol_features(config, data_symbol)
    singles = _candidate_specs(config, data_symbol)
    results = [_run_candidate(config, features, spec, "single") for spec in singles]
    combos = _combined_specs(config, singles, results)
    results.extend(_run_candidate(config, features, spec, "combined") for spec in combos)
    csv_path, txt_path = _export_results(data_symbol, broker, data_source, results)
    ranked = sorted(results, key=lambda item: (item.realized_pnl, item.profit_factor, item.closed_trades), reverse=True)
    best = ranked[0] if ranked else None
    recommended = [row.name for row in ranked if row.realized_pnl > 0 and row.profit_factor >= 1.0][:3]
    profile_name = f"symbol::{_symbol_slug(data_symbol)}"

    store = ExperimentStore(config.ai.experiment_database_path)
    run_id = store.record_symbol_research_run(
        profile_name=profile_name,
        data_symbol=data_symbol,
        broker_symbol=broker,
        data_source=data_source,
        candidates=results,
        recommended_names=recommended,
    )
    selected_execution_candidates = select_execution_candidates(
        [
            {
                "candidate_name": row.name,
                "code_path": row.code_path,
                "realized_pnl": row.realized_pnl,
                "profit_factor": row.profit_factor,
                "closed_trades": row.closed_trades,
                "recommended": row.name in recommended,
            }
            for row in results
        ],
        max_candidates=2,
    )
    execution_set_id = store.record_symbol_execution_set(
        profile_name=profile_name,
        symbol_research_run_id=run_id,
        selected_candidates=selected_execution_candidates,
    )
    descriptors = [
        AgentDescriptor(
            profile_name=profile_name,
            agent_name=row.name,
            lifecycle_scope="active",
            class_name=row.name,
            code_path=row.code_path,
            description=row.description,
            is_active=row.name in recommended,
        )
        for row in results
    ]
    store.promote_symbol_research_candidates(
        profile_name=profile_name,
        data_symbol=data_symbol,
        broker_symbol=broker,
        descriptors=descriptors,
        candidates=results,
        recommended_names=recommended,
        symbol_research_run_id=run_id,
    )

    lines = [
        f"Symbol: {data_symbol}",
        f"Broker symbol: {broker}",
        f"Catalog profile: {profile_name}",
        f"Data source: {data_source}",
        f"Candidates tested: {len(results)}",
        f"Research CSV: {csv_path}",
        f"Research report: {txt_path}",
    ]
    if best is not None:
        lines.extend(
            [
                f"Best candidate: {best.name}",
                f"Best PnL: {best.realized_pnl:.2f}",
                f"Best profit factor: {best.profit_factor:.2f}",
                f"Best closed trades: {best.closed_trades}",
            ]
        )
    lines.append("Recommended active agents: " + (", ".join(recommended) if recommended else "none"))
    lines.append(
        "Execution set: "
        + (
            ", ".join(str(row["candidate_name"]) for row in selected_execution_candidates)
            if selected_execution_candidates
            else "none"
        )
    )
    lines.append(f"Execution set id: {execution_set_id}")
    return lines
