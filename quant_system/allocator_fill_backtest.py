from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from quant_system.ai.storage import ExperimentStore
from quant_system.allocator import AllocationInput, allocate_portfolio_candidates
from quant_system.artifacts import system_reports_dir
from quant_system.config import SystemConfig
from quant_system.data.market_data import DuckDBMarketDataStore
from quant_system.symbols import resolve_symbol_request


@dataclass(slots=True)
class FillAwareMethodSummary:
    method: str
    buckets: int
    final_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    positive_bucket_rate_pct: float


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def _as_utc(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _minute_bucket(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


def _resolve_fill_symbol(fill: dict[str, object]) -> str:
    requested = str(fill.get("requested_symbol") or fill.get("broker_symbol") or "")
    broker_symbol = str(fill.get("broker_symbol") or "")
    resolved = resolve_symbol_request(requested, broker_symbol=broker_symbol)
    return resolved.profile_symbol.upper()


def _load_symbol_close_series(market_store: DuckDBMarketDataStore, symbol: str) -> list[tuple[datetime, float]]:
    resolved = resolve_symbol_request(symbol)
    timeframe_candidates = [
        f"symbol_research_{_slug(resolved.data_symbol)}_5_minute",
        f"symbol_research_{_slug(resolved.data_symbol)}_15_minute",
        f"symbol_research_{_slug(resolved.data_symbol)}_30_minute",
    ]
    for timeframe in timeframe_candidates:
        bars = market_store.load_bars(resolved.data_symbol, timeframe, 500000)
        if len(bars) >= 10:
            return [(bar.timestamp, float(bar.close)) for bar in bars if bar.close > 0.0]
    return []


def _build_symbol_market_views(
    market_store: DuckDBMarketDataStore, symbols: set[str], bucket_times: list[datetime], history_limit: int = 96
) -> tuple[dict[str, dict[datetime, float | None]], dict[str, dict[datetime, list[float]]]]:
    price_views: dict[str, dict[datetime, float | None]] = {}
    returns_views: dict[str, dict[datetime, list[float]]] = {}
    for symbol in symbols:
        series = _load_symbol_close_series(market_store, symbol)
        prices_by_bucket: dict[datetime, float | None] = {}
        returns_by_bucket: dict[datetime, list[float]] = {}
        if not series:
            price_views[symbol] = prices_by_bucket
            returns_views[symbol] = returns_by_bucket
            continue
        series_index = 0
        closes: list[float] = []
        for bucket in bucket_times:
            while series_index < len(series) and series[series_index][0] <= bucket:
                closes.append(series[series_index][1])
                series_index += 1
            prices_by_bucket[bucket] = closes[-1] if closes else None
            if len(closes) >= 11:
                window = closes[-(history_limit + 1) :]
                returns_by_bucket[bucket] = [
                    math.log(current / previous) for previous, current in zip(window, window[1:]) if previous > 0.0 and current > 0.0
                ]
            else:
                returns_by_bucket[bucket] = []
        price_views[symbol] = prices_by_bucket
        returns_views[symbol] = returns_by_bucket
    return price_views, returns_views


def _select_candidate_row(store: ExperimentStore, run: dict[str, object]) -> tuple[str, dict[str, object]] | None:
    candidates = store.list_symbol_research_candidates_for_run(int(run["id"]))
    if not candidates:
        return None
    candidate_map = {str(row["candidate_name"]): row for row in candidates}
    execution_set = store.get_symbol_execution_set_for_run(str(run["profile_name"]), int(run["id"]))
    if execution_set and execution_set["items"]:
        lead_name = str(execution_set["items"][0]["candidate_name"])
        lead_row = candidate_map.get(lead_name)
        if lead_row is not None:
            resolved = resolve_symbol_request(str(run["data_symbol"]), broker_symbol=str(run.get("broker_symbol") or ""))
            return resolved.profile_symbol.upper(), lead_row
    recommended_names = [str(name) for name in run.get("recommended_names", [])]
    for name in recommended_names:
        recommended = candidate_map.get(name)
        if recommended is not None:
            resolved = resolve_symbol_request(str(run["data_symbol"]), broker_symbol=str(run.get("broker_symbol") or ""))
            return resolved.profile_symbol.upper(), recommended
    if candidates:
        resolved = resolve_symbol_request(str(run["data_symbol"]), broker_symbol=str(run.get("broker_symbol") or ""))
        return resolved.profile_symbol.upper(), candidates[0]
    return None


def _build_selected_timelines(store: ExperimentStore, allowed_symbols: set[str]) -> dict[str, list[tuple[datetime, AllocationInput]]]:
    timelines: dict[str, list[tuple[datetime, AllocationInput]]] = {}
    for profile_name in store.list_symbol_research_profiles():
        if not profile_name.startswith("symbol::"):
            continue
        for run in store.list_symbol_research_runs(profile_name):
            selected = _select_candidate_row(store, run)
            if selected is None:
                continue
            symbol, candidate_row = selected
            if allowed_symbols and symbol not in allowed_symbols:
                continue
            timelines.setdefault(symbol, []).append(
                (_as_utc(run["created_at"]), AllocationInput(profile_name=profile_name, symbol=symbol, candidate_row=candidate_row))
            )
    return timelines


def _latest_input_before(
    timelines: dict[str, list[tuple[datetime, AllocationInput]]], symbol: str, as_of: datetime
) -> AllocationInput | None:
    latest: AllocationInput | None = None
    for created_at, item in timelines.get(symbol.upper(), []):
        if created_at <= as_of:
            latest = item
        else:
            break
    return latest


def _build_symbol_fill_returns(
    fills_by_symbol: dict[str, list[dict[str, object]]],
    bucket_times: list[datetime],
    price_views: dict[str, dict[datetime, float | None]],
) -> dict[str, dict[datetime, float]]:
    returns_by_symbol: dict[str, dict[datetime, float]] = {}
    for symbol, fills in fills_by_symbol.items():
        bucket_returns: dict[datetime, float] = {}
        fill_index = 0
        quantity = 0.0
        cash = 0.0
        base_notional = 0.0
        previous_equity: float | None = None
        sorted_fills = sorted(fills, key=lambda row: (_as_utc(row["event_timestamp"]), int(row["id"])))
        for bucket in bucket_times:
            while fill_index < len(sorted_fills) and _minute_bucket(_as_utc(sorted_fills[fill_index]["event_timestamp"])) <= bucket:
                fill = sorted_fills[fill_index]
                fill_index += 1
                signed_quantity = float(fill["quantity"]) if str(fill["side"]).lower() == "buy" else -float(fill["quantity"])
                fill_price = float(fill["fill_price"] or 0.0)
                costs = float(fill["costs"] or 0.0)
                if base_notional <= 0.0 and fill_price > 0.0 and abs(signed_quantity) > 0.0:
                    base_notional = abs(signed_quantity * fill_price)
                cash -= signed_quantity * fill_price
                cash -= costs
                quantity += signed_quantity
            mark_price = price_views.get(symbol, {}).get(bucket)
            if mark_price is None:
                continue
            equity = cash + quantity * mark_price
            if previous_equity is not None and base_notional > 0.0:
                bucket_returns[bucket] = (equity - previous_equity) / base_notional
            previous_equity = equity
        returns_by_symbol[symbol] = bucket_returns
    return returns_by_symbol


def _max_drawdown_pct(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_drawdown = 0.0
    for equity in equity_curve:
        if equity > peak:
            peak = equity
        if peak > 0.0:
            drawdown = (peak - equity) / peak
            if drawdown > max_drawdown:
                max_drawdown = drawdown
    return max_drawdown * 100.0


def backtest_fill_aware_portfolio_allocator(min_symbols: int = 2) -> tuple[list[FillAwareMethodSummary], Path]:
    config = SystemConfig()
    store = ExperimentStore(config.ai.experiment_database_path, read_only=True)
    fills = store.list_mt5_fill_events()
    report_path = system_reports_dir() / "portfolio_allocator_fill_backtest.txt"
    if not fills:
        report_path.write_text(
            "Portfolio allocator fill-aware backtest\n\nNo MT5 fills were found in mt5_fill_events.\n",
            encoding="utf-8",
        )
        return [], report_path

    fills_by_symbol: dict[str, list[dict[str, object]]] = {}
    bucket_times = sorted({_minute_bucket(_as_utc(fill["event_timestamp"])) for fill in fills})
    for fill in fills:
        fills_by_symbol.setdefault(_resolve_fill_symbol(fill), []).append(fill)

    active_symbols = set(fills_by_symbol)
    market_store = DuckDBMarketDataStore(config.mt5.database_path, read_only=True)
    price_views, corr_views = _build_symbol_market_views(market_store, active_symbols, bucket_times)
    timelines = _build_selected_timelines(store, active_symbols)
    symbol_bucket_returns = _build_symbol_fill_returns(fills_by_symbol, bucket_times, price_views)

    methods = ("naive", "bucket", "correlation_aware")
    method_equity = {method: 1.0 for method in methods}
    method_curve = {method: [1.0] for method in methods}
    method_returns = {method: [] for method in methods}

    for bucket in bucket_times:
        inputs: list[AllocationInput] = []
        available_symbols: list[str] = []
        for symbol in active_symbols:
            if bucket not in symbol_bucket_returns.get(symbol, {}):
                continue
            latest_input = _latest_input_before(timelines, symbol, bucket)
            if latest_input is None:
                continue
            inputs.append(latest_input)
            available_symbols.append(symbol)
        if len(inputs) < min_symbols:
            continue
        interval_returns = {symbol: symbol_bucket_returns[symbol][bucket] for symbol in available_symbols}
        for method in methods:
            corr_inputs = {item.symbol: corr_views.get(item.symbol, {}).get(bucket, []) for item in inputs} if method == "correlation_aware" else None
            allocations = allocate_portfolio_candidates(inputs, method=method, returns_by_symbol=corr_inputs)
            if not allocations:
                continue
            bucket_return = sum((row.weight_pct / 100.0) * interval_returns.get(row.symbol, 0.0) for row in allocations)
            method_equity[method] *= 1.0 + bucket_return
            method_curve[method].append(method_equity[method])
            method_returns[method].append(bucket_return)

    summaries = [
        FillAwareMethodSummary(
            method=method,
            buckets=len(method_returns[method]),
            final_equity=method_equity[method],
            total_return_pct=(method_equity[method] - 1.0) * 100.0,
            max_drawdown_pct=_max_drawdown_pct(method_curve[method]),
            positive_bucket_rate_pct=(
                sum(1 for value in method_returns[method] if value > 0.0) / float(len(method_returns[method])) * 100.0
                if method_returns[method]
                else 0.0
            ),
        )
        for method in methods
    ]

    lines = [
        "Portfolio allocator fill-aware backtest",
        "Metric: MT5 fill cashflows plus mark-to-market by symbol, then allocator weighting across symbols.",
        f"fills: {len(fills)}",
        "",
        "Summary",
    ]
    for summary in summaries:
        lines.extend(
            [
                summary.method,
                f"  buckets: {summary.buckets}",
                f"  final_equity: {summary.final_equity:.4f}",
                f"  total_return_pct: {summary.total_return_pct:.2f}",
                f"  max_drawdown_pct: {summary.max_drawdown_pct:.2f}",
                f"  positive_bucket_rate_pct: {summary.positive_bucket_rate_pct:.2f}",
                "",
            ]
        )
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return summaries, report_path
