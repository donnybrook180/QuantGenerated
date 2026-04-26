from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math

from quant_system.ai.storage import ExperimentStore
from quant_system.artifacts import list_deployment_paths, parse_symbol_profile_name, symbol_profile_name, system_reports_dir
from quant_system.config import SystemConfig
from quant_system.data.market_data import DuckDBMarketDataStore
from quant_system.live.deploy import DEPLOY_DIR, load_symbol_deployment
from quant_system.symbols import (
    is_crypto_symbol,
    is_forex_symbol,
    is_index_symbol,
    is_metal_symbol,
    is_stock_symbol,
    resolve_symbol_request,
)


@dataclass(slots=True)
class AllocationRow:
    profile_name: str
    symbol: str
    asset_class: str
    correlation_bucket: str
    candidate_name: str
    promotion_tier: str
    policy_summary: str
    variant_label: str
    regime_filter_label: str
    base_allocation_weight: float
    max_risk_multiplier: float
    min_risk_multiplier: float
    base_score: float
    score: float
    weight_pct: float
    realized_pnl: float
    profit_factor: float
    max_drawdown_pct: float
    closed_trades: int
    validation_pnl: float
    validation_profit_factor: float
    validation_closed_trades: int
    test_pnl: float
    test_profit_factor: float
    test_closed_trades: int
    walk_forward_pass_rate_pct: float
    walk_forward_windows: int
    combo_outperformance_score: float
    dominant_regime_share_pct: float


@dataclass(slots=True)
class AllocationInput:
    profile_name: str
    symbol: str
    candidate_row: dict[str, object]


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0.0:
        return 0.0
    return numerator / denominator


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _symbol_slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def _candidate_score(row: dict[str, object]) -> float:
    validation_pf_score = _clamp(_safe_div(float(row.get("validation_profit_factor", 0.0)), 2.5))
    test_pf_score = _clamp(_safe_div(float(row.get("test_profit_factor", 0.0)), 2.5))
    validation_pnl_score = _clamp(_safe_div(float(row.get("validation_pnl", 0.0)), 100.0))
    test_pnl_score = _clamp(_safe_div(float(row.get("test_pnl", 0.0)), 100.0))
    walk_forward_score = _clamp(_safe_div(float(row.get("walk_forward_pass_rate_pct", 0.0)), 100.0))
    walk_forward_pnl_score = _clamp(_safe_div(float(row.get("walk_forward_avg_test_pnl", 0.0)), 100.0))
    trade_depth_score = _clamp(_safe_div(float(row.get("closed_trades", 0)), 20.0))
    drawdown_score = 1.0 - _clamp(_safe_div(float(row.get("max_drawdown_pct", 0.0)), 5.0))
    combo_score = _clamp(0.5 + _safe_div(float(row.get("combo_outperformance_score", 0.0)), 2.0))
    regime_stability_score = 1.0 - _clamp(_safe_div(max(float(row.get("dominant_regime_share_pct", 0.0)) - 70.0, 0.0), 30.0))

    score = (
        validation_pf_score * 0.16
        + test_pf_score * 0.18
        + validation_pnl_score * 0.12
        + test_pnl_score * 0.14
        + walk_forward_score * 0.16
        + walk_forward_pnl_score * 0.08
        + trade_depth_score * 0.06
        + drawdown_score * 0.06
        + combo_score * 0.02
        + regime_stability_score * 0.02
    )
    return max(score, 0.0)


def _asset_class(symbol: str) -> str:
    if is_crypto_symbol(symbol):
        return "crypto"
    if is_metal_symbol(symbol):
        return "metals"
    if is_forex_symbol(symbol):
        return "forex"
    if is_index_symbol(symbol):
        return "indices"
    if is_stock_symbol(symbol):
        return "stocks"
    return "other"


def _correlation_bucket(symbol: str) -> str:
    upper = symbol.upper()
    if upper in {"US500", "US100", "US30"}:
        return "us_indices"
    if upper in {"GER40", "EU50", "SX5E"}:
        return "eu_indices"
    if upper in {"BTC", "ETH"}:
        return "crypto_beta"
    if upper in {"XAUUSD"}:
        return "gold"
    if upper.endswith("USD") or upper.endswith("JPY") or upper.startswith("EUR") or upper.startswith("GBP") or upper.startswith("AUD"):
        return "majors_fx"
    return _asset_class(symbol)


def _asset_class_caps() -> dict[str, float]:
    return {
        "crypto": 0.25,
        "metals": 0.20,
        "forex": 0.30,
        "indices": 0.45,
        "stocks": 0.40,
        "other": 0.20,
    }


def _sample_correlation(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 3:
        return 0.0
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0.0 or var_y <= 0.0:
        return 0.0
    return cov / math.sqrt(var_x * var_y)


def _rolling_close_returns(store: DuckDBMarketDataStore, symbol: str, history_limit: int = 96) -> list[float]:
    resolved = resolve_symbol_request(symbol)
    timeframe_candidates = [
        f"symbol_research_{_symbol_slug(resolved.data_symbol)}_15_minute",
        f"symbol_research_{_symbol_slug(resolved.data_symbol)}_5_minute",
        f"symbol_research_{_symbol_slug(resolved.data_symbol)}_30_minute",
    ]
    try:
        for timeframe in timeframe_candidates:
            bars = store.load_bars(resolved.data_symbol, timeframe, history_limit + 1)
            if len(bars) >= 12:
                returns: list[float] = []
                previous_close: float | None = None
                for bar in bars:
                    if previous_close is not None and previous_close > 0.0 and bar.close > 0.0:
                        returns.append(math.log(bar.close / previous_close))
                    previous_close = bar.close
                if len(returns) >= 10:
                    return returns[-history_limit:]
    except Exception:
        return []
    return []


def _rolling_close_returns_before(
    store: DuckDBMarketDataStore, symbol: str, end_ts: datetime, history_limit: int = 96
) -> list[float]:
    resolved = resolve_symbol_request(symbol)
    timeframe_candidates = [
        f"symbol_research_{_symbol_slug(resolved.data_symbol)}_15_minute",
        f"symbol_research_{_symbol_slug(resolved.data_symbol)}_5_minute",
        f"symbol_research_{_symbol_slug(resolved.data_symbol)}_30_minute",
    ]
    try:
        for timeframe in timeframe_candidates:
            bars = store.load_bars_before(resolved.data_symbol, timeframe, end_ts, history_limit + 1)
            if len(bars) >= 12:
                returns: list[float] = []
                previous_close: float | None = None
                for bar in bars:
                    if previous_close is not None and previous_close > 0.0 and bar.close > 0.0:
                        returns.append(math.log(bar.close / previous_close))
                    previous_close = bar.close
                if len(returns) >= 10:
                    return returns[-history_limit:]
    except Exception:
        return []
    return []


def load_symbol_returns_before(
    store: DuckDBMarketDataStore, symbol: str, end_ts: datetime, history_limit: int = 96
) -> list[float]:
    return _rolling_close_returns_before(store, symbol, end_ts, history_limit)


def _pairwise_correlation_penalty(
    current_symbol: str,
    selected_symbols: list[str],
    returns_by_symbol: dict[str, list[float]],
    fallback_bucket_penalty: float,
) -> float:
    current_returns = returns_by_symbol.get(current_symbol, [])
    if not current_returns or not selected_symbols:
        return fallback_bucket_penalty
    max_corr = 0.0
    for selected_symbol in selected_symbols:
        other_returns = returns_by_symbol.get(selected_symbol, [])
        if not other_returns:
            continue
        overlap = min(len(current_returns), len(other_returns), 96)
        if overlap < 10:
            continue
        corr = abs(_sample_correlation(current_returns[-overlap:], other_returns[-overlap:]))
        if corr > max_corr:
            max_corr = corr
    if max_corr <= 0.0:
        return fallback_bucket_penalty
    return min(fallback_bucket_penalty, 1.0 - 0.35 * max_corr)


def _apply_diversification_penalty(
    rows: list[tuple[str, str, dict[str, object], float]], returns_by_symbol: dict[str, list[float]]
) -> list[tuple[str, str, dict[str, object], float, float]]:
    bucket_counts: dict[str, int] = {}
    class_counts: dict[str, int] = {}
    selected_symbols: list[str] = []
    adjusted_rows: list[tuple[str, str, dict[str, object], float, float]] = []
    for profile_name, symbol, row, base_score in sorted(rows, key=lambda item: item[3], reverse=True):
        asset = _asset_class(symbol)
        bucket = _correlation_bucket(symbol)
        bucket_penalty = 0.82 ** bucket_counts.get(bucket, 0)
        correlation_penalty = _pairwise_correlation_penalty(symbol, selected_symbols, returns_by_symbol, bucket_penalty)
        class_penalty = 0.90 ** class_counts.get(asset, 0)
        adjusted_score = base_score * correlation_penalty * class_penalty
        adjusted_rows.append((profile_name, symbol, row, base_score, adjusted_score))
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        class_counts[asset] = class_counts.get(asset, 0) + 1
        selected_symbols.append(symbol)
    return adjusted_rows


def _capped_weights(rows: list[tuple[str, str, dict[str, object], float, float]]) -> list[float]:
    if not rows:
        return []
    caps = _asset_class_caps()
    raw_total = sum(adjusted for _, _, _, _, adjusted in rows)
    if raw_total <= 0.0:
        return [0.0 for _ in rows]
    raw_weights = [adjusted / raw_total for _, symbol, _, _, adjusted in rows]
    final_weights = raw_weights[:]
    classes = [_asset_class(symbol) for _, symbol, _, _, _ in rows]

    # Iterative capping: clip overweight asset classes, then redistribute residual to uncapped names.
    for _ in range(4):
        class_totals: dict[str, float] = {}
        for weight, asset in zip(final_weights, classes):
            class_totals[asset] = class_totals.get(asset, 0.0) + weight
        capped_assets = {asset for asset, total in class_totals.items() if total > caps.get(asset, 1.0)}
        if not capped_assets:
            break
        residual = 0.0
        free_indices: list[int] = []
        free_total = 0.0
        for index, asset in enumerate(classes):
            class_total = class_totals[asset]
            cap = caps.get(asset, 1.0)
            if asset in capped_assets and class_total > 0.0:
                capped_weight = final_weights[index] * (cap / class_total)
                residual += final_weights[index] - capped_weight
                final_weights[index] = capped_weight
            else:
                free_indices.append(index)
                free_total += final_weights[index]
        if residual <= 0.0 or free_total <= 0.0:
            continue
        for index in free_indices:
            final_weights[index] += residual * (final_weights[index] / free_total)

    total = sum(final_weights)
    return [weight / total if total > 0.0 else 0.0 for weight in final_weights]


def _equal_weights(count: int) -> list[float]:
    if count <= 0:
        return []
    weight = 1.0 / float(count)
    return [weight for _ in range(count)]


def _row_to_allocation(
    profile_name: str, symbol: str, row: dict[str, object], base_score: float, score: float, weight_pct: float
) -> AllocationRow:
    return AllocationRow(
        profile_name=profile_name,
        symbol=symbol,
        asset_class=_asset_class(symbol),
        correlation_bucket=_correlation_bucket(symbol),
        candidate_name=str(row.get("candidate_name", "")),
        promotion_tier=str(row.get("promotion_tier", "core") or "core"),
        policy_summary=str(row.get("policy_summary", "") or ""),
        variant_label=str(row.get("variant_label", "") or ""),
        regime_filter_label=str(row.get("regime_filter_label", "") or ""),
        base_allocation_weight=float(row.get("base_allocation_weight", 1.0) or 1.0),
        max_risk_multiplier=float(row.get("max_risk_multiplier", 1.0) or 1.0),
        min_risk_multiplier=float(row.get("min_risk_multiplier", 0.0) or 0.0),
        base_score=base_score,
        score=score,
        weight_pct=weight_pct,
        realized_pnl=float(row.get("realized_pnl", 0.0)),
        profit_factor=float(row.get("profit_factor", 0.0)),
        max_drawdown_pct=float(row.get("max_drawdown_pct", 0.0)),
        closed_trades=int(row.get("closed_trades", 0)),
        validation_pnl=float(row.get("validation_pnl", 0.0)),
        validation_profit_factor=float(row.get("validation_profit_factor", 0.0)),
        validation_closed_trades=int(row.get("validation_closed_trades", 0)),
        test_pnl=float(row.get("test_pnl", 0.0)),
        test_profit_factor=float(row.get("test_profit_factor", 0.0)),
        test_closed_trades=int(row.get("test_closed_trades", 0)),
        walk_forward_pass_rate_pct=float(row.get("walk_forward_pass_rate_pct", 0.0)),
        walk_forward_windows=int(row.get("walk_forward_windows", 0)),
        combo_outperformance_score=float(row.get("combo_outperformance_score", 0.0)),
        dominant_regime_share_pct=float(row.get("dominant_regime_share_pct", 0.0)),
    )


def _resolve_profile_symbol(symbol_or_profile: str) -> tuple[str, str]:
    raw = symbol_or_profile.strip()
    parsed = parse_symbol_profile_name(raw)
    if parsed is not None:
        _venue_key, symbol_slug = parsed
        return raw, symbol_slug.upper()
    resolved = resolve_symbol_request(raw)
    config = SystemConfig()
    return symbol_profile_name(resolved.profile_symbol, str(config.mt5.prop_broker)), resolved.profile_symbol


def _prepare_scored_rows(inputs: list[AllocationInput]) -> list[tuple[str, str, dict[str, object], float]]:
    scored_rows: list[tuple[str, str, dict[str, object], float]] = []
    for item in inputs:
        score = _candidate_score(item.candidate_row)
        if score <= 0.0:
            continue
        scored_rows.append((item.profile_name, item.symbol, item.candidate_row, score))
    return scored_rows


def allocate_portfolio_candidates(
    inputs: list[AllocationInput],
    *,
    method: str = "correlation_aware",
    returns_by_symbol: dict[str, list[float]] | None = None,
) -> list[AllocationRow]:
    scored_rows = _prepare_scored_rows(inputs)
    if not scored_rows:
        return []
    normalized_method = method.strip().lower()
    if normalized_method == "agent_first":
        return [
            _row_to_allocation(profile_name, symbol, row, base_score, base_score, 100.0)
            for profile_name, symbol, row, base_score in scored_rows
        ]
    if normalized_method == "naive":
        weights = _equal_weights(len(scored_rows))
        return [
            _row_to_allocation(profile_name, symbol, row, base_score, base_score, weight * 100.0)
            for (profile_name, symbol, row, base_score), weight in zip(scored_rows, weights)
        ]

    diversification_returns = returns_by_symbol or {}
    if normalized_method == "bucket":
        diversification_returns = {}
    adjusted_rows = _apply_diversification_penalty(scored_rows, diversification_returns)
    weights = _capped_weights(adjusted_rows)
    return [
        _row_to_allocation(profile_name, symbol, row, base_score, adjusted_score, weight * 100.0)
        for (profile_name, symbol, row, base_score, adjusted_score), weight in zip(adjusted_rows, weights)
    ]


def build_portfolio_allocation(symbols_or_profiles: list[str] | None = None) -> tuple[list[AllocationRow], Path]:
    config = SystemConfig()
    store = ExperimentStore(config.ai.experiment_database_path)
    market_store = DuckDBMarketDataStore(config.mt5.database_path, read_only=True)
    requested_profiles: list[tuple[str, str]]
    if symbols_or_profiles:
        requested_profiles = [_resolve_profile_symbol(item) for item in symbols_or_profiles]
    else:
        requested_profiles = []
        if DEPLOY_DIR.exists():
            for path in list_deployment_paths():
                deployment = load_symbol_deployment(path)
                requested_profiles.append((deployment.profile_name, deployment.symbol.upper()))
        else:
            for profile_name in store.list_symbol_research_profiles():
                parsed = parse_symbol_profile_name(profile_name)
                if parsed is not None:
                    _venue_key, symbol_slug = parsed
                    requested_profiles.append((profile_name, symbol_slug.upper()))

    inputs: list[AllocationInput] = []
    for profile_name, symbol in requested_profiles:
        latest_run = store.get_latest_symbol_research_run(profile_name)
        if latest_run is None:
            continue
        execution_set = store.get_latest_symbol_execution_set(profile_name)
        if execution_set is None or int(execution_set["symbol_research_run_id"]) != int(latest_run["id"]):
            continue
        candidate_rows = {str(row["candidate_name"]): row for row in store.list_latest_symbol_research_candidates(profile_name)}
        if not execution_set["items"]:
            continue
        for execution_item in execution_set["items"]:
            candidate_row = candidate_rows.get(str(execution_item["candidate_name"]))
            if candidate_row is None:
                continue
            merged_row = dict(candidate_row)
            merged_row.update(
                {
                    "promotion_tier": execution_item.get("promotion_tier", merged_row.get("promotion_tier", "core")),
                    "policy_summary": execution_item.get("policy_summary", ""),
                    "regime_filter_label": execution_item.get(
                        "regime_filter_label", merged_row.get("regime_filter_label", "")
                    ),
                    "base_allocation_weight": execution_item.get("base_allocation_weight", 1.0),
                    "max_risk_multiplier": execution_item.get("max_risk_multiplier", 1.0),
                    "min_risk_multiplier": execution_item.get("min_risk_multiplier", 0.0),
                }
            )
            inputs.append(AllocationInput(profile_name=profile_name, symbol=symbol, candidate_row=merged_row))

    returns_by_symbol = {item.symbol: _rolling_close_returns(market_store, item.symbol) for item in inputs}
    allocations = allocate_portfolio_candidates(inputs, method="agent_first", returns_by_symbol=returns_by_symbol)

    report_path = system_reports_dir() / "portfolio_allocator.txt"
    if not allocations:
        report_path.write_text(
            "Portfolio allocator\n\nNo eligible symbol execution sets were found from the latest symbol research runs.\n",
            encoding="utf-8",
        )
        return allocations, report_path

    data_ready_symbols = sum(1 for values in returns_by_symbol.values() if len(values) >= 10)
    lines = [
        "Portfolio allocator",
        "Mode: agent_first",
        "Interpretation: each live strategy is treated as its own opportunity; weight_pct is not diluted across symbols.",
        f"Correlation data coverage: {data_ready_symbols}/{len(returns_by_symbol)} symbols",
        "",
    ]
    for row in allocations:
        variant = row.variant_label or "default"
        if row.regime_filter_label:
            variant = f"{variant}|{row.regime_filter_label}"
        lines.extend(
            [
                f"{row.symbol} ({row.profile_name})",
                f"  asset_class: {row.asset_class} bucket={row.correlation_bucket}",
                f"  weight_pct: {row.weight_pct:.2f}",
                f"  score: adjusted={row.score:.4f} base={row.base_score:.4f}",
                f"  candidate: {row.candidate_name}",
                f"  tier: {row.promotion_tier} base_alloc={row.base_allocation_weight:.2f} risk_cap={row.max_risk_multiplier:.2f}",
                f"  variant: {variant}",
                f"  realized: pnl={row.realized_pnl:.2f} pf={row.profit_factor:.2f} closed={row.closed_trades} dd={row.max_drawdown_pct:.2f}%",
                f"  validation: pnl={row.validation_pnl:.2f} pf={row.validation_profit_factor:.2f} closed={row.validation_closed_trades}",
                f"  test: pnl={row.test_pnl:.2f} pf={row.test_profit_factor:.2f} closed={row.test_closed_trades}",
                f"  walk_forward: pass_rate={row.walk_forward_pass_rate_pct:.2f}% windows={row.walk_forward_windows}",
                f"  regime_stability: dominant_share={row.dominant_regime_share_pct:.2f}% combo_score={row.combo_outperformance_score:.2f}",
                f"  policy: {row.policy_summary or 'n/a'}",
                "",
            ]
        )
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return allocations, report_path
