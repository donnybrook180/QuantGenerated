from __future__ import annotations

import json
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
class ForwardBucketSignal:
    timestamp: datetime
    symbol: str
    signed_strength: float


@dataclass(slots=True)
class ForwardMethodSummary:
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


def _parse_journal_timestamp(path: Path) -> datetime | None:
    try:
        prefix = path.name.split("_", 1)[0]
        return datetime.strptime(prefix, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _minute_bucket(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


def _signal_sign(value: str) -> float:
    normalized = str(value or "").strip().lower()
    if normalized == "buy":
        return 1.0
    if normalized == "sell":
        return -1.0
    return 0.0


def _signed_strength_from_actions(actions: list[dict[str, object]]) -> float:
    active = [action for action in actions if _signal_sign(str(action.get("signal_side", ""))) != 0.0]
    if not active:
        return 0.0
    total = 0.0
    for action in active:
        sign = _signal_sign(str(action.get("signal_side", "")))
        confidence = float(action.get("confidence", 0.0) or 0.0)
        allocation_fraction = float(action.get("allocation_fraction", 0.0) or 0.0)
        if allocation_fraction <= 0.0:
            allocation_fraction = 1.0 / float(len(active))
        total += sign * confidence * allocation_fraction
    if total > 1.0:
        return 1.0
    if total < -1.0:
        return -1.0
    return total


def _collect_bucket_signals() -> dict[datetime, dict[str, float]]:
    bucketed: dict[datetime, dict[str, list[float]]] = {}
    for path in Path("artifacts/live").rglob("*_journal.json"):
        ts = _parse_journal_timestamp(path)
        if ts is None:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        symbol = str(payload.get("symbol", "")).upper()
        if not symbol:
            continue
        strength = _signed_strength_from_actions(list(payload.get("actions", [])))
        if strength == 0.0:
            continue
        bucket = _minute_bucket(ts)
        bucketed.setdefault(bucket, {}).setdefault(symbol, []).append(strength)
    collapsed: dict[datetime, dict[str, float]] = {}
    for bucket, symbol_values in bucketed.items():
        collapsed[bucket] = {symbol: sum(values) / float(len(values)) for symbol, values in symbol_values.items()}
    return collapsed


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
    recommended_rows = [row for row in candidates if bool(row.get("recommended"))]
    if recommended_rows:
        resolved = resolve_symbol_request(str(run["data_symbol"]), broker_symbol=str(run.get("broker_symbol") or ""))
        return resolved.profile_symbol.upper(), recommended_rows[0]
    resolved = resolve_symbol_request(str(run["data_symbol"]), broker_symbol=str(run.get("broker_symbol") or ""))
    return resolved.profile_symbol.upper(), candidates[0]


def _build_selected_timelines(store: ExperimentStore, allowed_symbols: set[str]) -> dict[str, list[tuple[datetime, AllocationInput]]]:
    timelines: dict[str, list[tuple[datetime, AllocationInput]]] = {}
    for profile_name in store.list_symbol_research_profiles():
        if not profile_name.startswith("symbol::"):
            continue
        runs = store.list_symbol_research_runs(profile_name)
        for run in runs:
            selected = _select_candidate_row(store, run)
            if selected is None:
                continue
            symbol, candidate_row = selected
            upper_symbol = symbol.upper()
            if allowed_symbols and upper_symbol not in allowed_symbols:
                continue
            timelines.setdefault(upper_symbol, []).append(
                (
                    _as_utc(run["created_at"]),
                    AllocationInput(profile_name=profile_name, symbol=upper_symbol, candidate_row=candidate_row),
                )
            )
    return timelines


def _latest_input_before(
    timelines: dict[str, list[tuple[datetime, AllocationInput]]], symbol: str, as_of: datetime
) -> AllocationInput | None:
    items = timelines.get(symbol.upper(), [])
    latest: AllocationInput | None = None
    for created_at, item in items:
        if created_at <= as_of:
            latest = item
        else:
            break
    return latest


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
        if not series:
            price_views[symbol] = {}
            returns_views[symbol] = {}
            continue
        prices_by_bucket: dict[datetime, float | None] = {}
        returns_by_bucket: dict[datetime, list[float]] = {}
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


def _max_drawdown_pct(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for equity in equity_curve:
        if equity > peak:
            peak = equity
        if peak > 0.0:
            drawdown = (peak - equity) / peak
            if drawdown > max_dd:
                max_dd = drawdown
    return max_dd * 100.0


def backtest_forward_portfolio_allocator(
    *,
    min_symbols: int = 2,
) -> tuple[list[ForwardMethodSummary], Path]:
    config = SystemConfig()
    store = ExperimentStore(config.ai.experiment_database_path, read_only=True)
    market_store = DuckDBMarketDataStore(config.mt5.database_path, read_only=True)
    bucket_signals = _collect_bucket_signals()
    active_symbols = {symbol for signals in bucket_signals.values() for symbol in signals}
    timelines = _build_selected_timelines(store, active_symbols)
    bucket_times = sorted(bucket_signals)
    price_views, returns_views = _build_symbol_market_views(market_store, active_symbols, bucket_times)
    methods = ("naive", "bucket", "correlation_aware")
    method_equity: dict[str, float] = {method: 1.0 for method in methods}
    method_curve: dict[str, list[float]] = {method: [1.0] for method in methods}
    method_returns: dict[str, list[float]] = {method: [] for method in methods}

    for current_ts, next_ts in zip(bucket_times, bucket_times[1:]):
        inputs: list[AllocationInput] = []
        strengths: dict[str, float] = {}
        for symbol, signed_strength in bucket_signals[current_ts].items():
            latest_input = _latest_input_before(timelines, symbol, current_ts)
            if latest_input is None:
                continue
            inputs.append(latest_input)
            strengths[symbol] = signed_strength
        if len(inputs) < min_symbols:
            continue
        realized_returns: dict[str, float] = {}
        for symbol in strengths:
            start_price = price_views.get(symbol, {}).get(current_ts)
            end_price = price_views.get(symbol, {}).get(next_ts)
            if start_price is None or end_price is None or start_price <= 0.0:
                continue
            realized_returns[symbol] = (end_price - start_price) / start_price
        if len(realized_returns) < min_symbols:
            continue
        filtered_inputs = [item for item in inputs if item.symbol in realized_returns]
        if len(filtered_inputs) < min_symbols:
            continue
        for method in methods:
            returns_by_symbol = None
            if method == "correlation_aware":
                returns_by_symbol = {item.symbol: returns_views.get(item.symbol, {}).get(current_ts, []) for item in filtered_inputs}
            allocations = allocate_portfolio_candidates(
                filtered_inputs,
                method=method,
                returns_by_symbol=returns_by_symbol,
            )
            if not allocations:
                continue
            bucket_return = 0.0
            for row in allocations:
                symbol_return = realized_returns.get(row.symbol)
                if symbol_return is None:
                    continue
                signed_strength = strengths.get(row.symbol, 0.0)
                bucket_return += (row.weight_pct / 100.0) * signed_strength * symbol_return
            method_equity[method] *= 1.0 + bucket_return
            method_curve[method].append(method_equity[method])
            method_returns[method].append(bucket_return)

    summaries: list[ForwardMethodSummary] = []
    for method in methods:
        returns = method_returns[method]
        final_equity = method_equity[method]
        total_return_pct = (final_equity - 1.0) * 100.0
        positive_rate = (sum(1 for value in returns if value > 0.0) / float(len(returns)) * 100.0) if returns else 0.0
        summaries.append(
            ForwardMethodSummary(
                method=method,
                buckets=len(returns),
                final_equity=final_equity,
                total_return_pct=total_return_pct,
                max_drawdown_pct=_max_drawdown_pct(method_curve[method]),
                positive_bucket_rate_pct=positive_rate,
            )
        )

    report_path = system_reports_dir() / "portfolio_allocator_forward_backtest.txt"
    lines = [
        "Portfolio allocator forward backtest",
        "Metric: live journal signal strength x realized symbol return between journal minute buckets.",
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
