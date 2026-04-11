from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from quant_system.ai.storage import ExperimentStore
from quant_system.artifacts import system_reports_dir
from quant_system.config import SystemConfig


def _as_utc(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int((len(ordered) - 1) * q)
    return float(ordered[index])


def _average(values: list[float]) -> float:
    return sum(values) / float(len(values)) if values else 0.0


def _weighted_average(values: list[float], weights: list[float]) -> float:
    if not values or not weights:
        return 0.0
    total_weight = sum(weights)
    if total_weight <= 0.0:
        return 0.0
    return sum(value * weight for value, weight in zip(values, weights)) / total_weight


def _fmt_ts(value: datetime | None) -> str:
    if value is None:
        return "n/a"
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%SZ")


def _fmt_num(value: float, decimals: int = 2) -> str:
    return f"{value:.{decimals}f}"


def _infer_strategy(fill: dict[str, object]) -> str:
    metadata = fill.get("metadata", {})
    if isinstance(metadata, dict):
        strategy = str(metadata.get("strategy") or "").strip()
        if strategy:
            return strategy
    comment = str(fill.get("comment") or "").strip()
    if comment:
        return comment
    reason = str(fill.get("reason") or "").strip()
    if reason.startswith("close_"):
        return reason.removeprefix("close_")
    if reason:
        return reason
    return "unknown"


def _fill_intent(fill: dict[str, object]) -> str:
    position_ticket = int(fill.get("position_ticket") or 0)
    reason = str(fill.get("reason") or "").strip().lower()
    if position_ticket > 0 or reason.startswith("close_") or reason in {
        "stop_loss",
        "take_profit",
        "trailing_stop",
        "signal_exit",
        "time_stop",
        "structure_exit",
        "stale_breakout",
        "end_of_run",
    }:
        return "close"
    return "open"


def _signed_touch_slippage_points(fill: dict[str, object]) -> float:
    requested = float(fill.get("requested_price") or 0.0)
    execution = float(fill.get("fill_price") or 0.0)
    side = str(fill.get("side") or "").lower()
    if requested <= 0.0 or execution <= 0.0:
        return 0.0
    if side == "buy":
        return execution - requested
    return requested - execution


def _mid_price(fill: dict[str, object]) -> float:
    bid = float(fill.get("bid") or 0.0)
    ask = float(fill.get("ask") or 0.0)
    if bid > 0.0 and ask > 0.0:
        return (bid + ask) / 2.0
    return float(fill.get("requested_price") or 0.0)


def _implementation_shortfall_points(fill: dict[str, object]) -> float:
    execution = float(fill.get("fill_price") or 0.0)
    mid = _mid_price(fill)
    side = str(fill.get("side") or "").lower()
    if execution <= 0.0 or mid <= 0.0:
        return 0.0
    if side == "buy":
        return execution - mid
    return mid - execution


def _bps(points: float, reference_price: float) -> float:
    if reference_price <= 0.0:
        return 0.0
    return points / reference_price * 10_000.0


@dataclass(slots=True)
class TCAAggregate:
    label: str
    fill_count: int
    first_fill_at: datetime | None
    last_fill_at: datetime | None
    buy_count: int
    sell_count: int
    open_count: int
    close_count: int
    avg_quantity: float
    avg_spread_points: float
    median_spread_points: float
    p75_spread_points: float
    avg_touch_slippage_bps: float
    median_touch_slippage_bps: float
    p75_touch_slippage_bps: float
    weighted_touch_slippage_bps: float
    adverse_touch_fill_rate_pct: float
    avg_shortfall_bps: float
    median_shortfall_bps: float
    p75_shortfall_bps: float
    weighted_shortfall_bps: float
    total_costs: float
    avg_cost_per_fill: float
    weighted_cost_bps: float
    total_notional: float


@dataclass(slots=True)
class TCAReport:
    generated_at: datetime
    broker_symbol: str | None
    overview: TCAAggregate | None
    by_symbol: list[TCAAggregate]
    by_strategy: list[TCAAggregate]
    by_intent: list[TCAAggregate]
    by_hour: list[TCAAggregate]
    worst_fills: list[dict[str, object]]
    report_path: Path


def summarize_tca_overview(report: TCAReport) -> str:
    if report.overview is None:
        return "none"
    overview = report.overview
    return (
        f"fills={overview.fill_count} "
        f"w_touch_slip_bps={overview.weighted_touch_slippage_bps:.3f} "
        f"w_shortfall_bps={overview.weighted_shortfall_bps:.3f} "
        f"w_cost_bps={overview.weighted_cost_bps:.3f} "
        f"adverse_fill_rate_pct={overview.adverse_touch_fill_rate_pct:.1f}"
    )


def _aggregate(label: str, fills: list[dict[str, object]]) -> TCAAggregate:
    timestamps = [_as_utc(fill["event_timestamp"]) for fill in fills]
    quantities = [abs(float(fill.get("quantity") or 0.0)) for fill in fills]
    spreads = [float(fill.get("spread_points") or 0.0) for fill in fills]
    touch_bps_values: list[float] = []
    shortfall_bps_values: list[float] = []
    cost_values: list[float] = []
    notionals: list[float] = []
    adverse_count = 0
    for fill in fills:
        price = float(fill.get("fill_price") or 0.0)
        quantity = abs(float(fill.get("quantity") or 0.0))
        reference_touch = float(fill.get("requested_price") or 0.0) or price
        reference_mid = _mid_price(fill) or price
        touch_bps = _bps(_signed_touch_slippage_points(fill), reference_touch)
        shortfall_bps = _bps(_implementation_shortfall_points(fill), reference_mid)
        if touch_bps > 0.0:
            adverse_count += 1
        touch_bps_values.append(touch_bps)
        shortfall_bps_values.append(shortfall_bps)
        cost_values.append(abs(float(fill.get("costs") or 0.0)))
        notionals.append(price * quantity)
    buy_count = sum(1 for fill in fills if str(fill.get("side") or "").lower() == "buy")
    open_count = sum(1 for fill in fills if _fill_intent(fill) == "open")
    total_notional = sum(notionals)
    return TCAAggregate(
        label=label,
        fill_count=len(fills),
        first_fill_at=min(timestamps) if timestamps else None,
        last_fill_at=max(timestamps) if timestamps else None,
        buy_count=buy_count,
        sell_count=len(fills) - buy_count,
        open_count=open_count,
        close_count=len(fills) - open_count,
        avg_quantity=_average(quantities),
        avg_spread_points=_average(spreads),
        median_spread_points=median(spreads) if spreads else 0.0,
        p75_spread_points=_quantile(spreads, 0.75),
        avg_touch_slippage_bps=_average(touch_bps_values),
        median_touch_slippage_bps=median(touch_bps_values) if touch_bps_values else 0.0,
        p75_touch_slippage_bps=_quantile(touch_bps_values, 0.75),
        weighted_touch_slippage_bps=_weighted_average(touch_bps_values, notionals),
        adverse_touch_fill_rate_pct=(adverse_count / float(len(fills)) * 100.0) if fills else 0.0,
        avg_shortfall_bps=_average(shortfall_bps_values),
        median_shortfall_bps=median(shortfall_bps_values) if shortfall_bps_values else 0.0,
        p75_shortfall_bps=_quantile(shortfall_bps_values, 0.75),
        weighted_shortfall_bps=_weighted_average(shortfall_bps_values, notionals),
        total_costs=sum(cost_values),
        avg_cost_per_fill=_average(cost_values),
        weighted_cost_bps=_weighted_average(
            [_bps(cost, notional) for cost, notional in zip(cost_values, notionals)],
            notionals,
        ),
        total_notional=total_notional,
    )


def _group_aggregates(fills: list[dict[str, object]], key_fn) -> list[TCAAggregate]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for fill in fills:
        key = str(key_fn(fill) or "unknown")
        grouped.setdefault(key, []).append(fill)
    aggregates = [_aggregate(label, rows) for label, rows in grouped.items()]
    aggregates.sort(key=lambda row: (-row.fill_count, row.label))
    return aggregates


def _worst_fills(fills: list[dict[str, object]], limit: int = 12) -> list[dict[str, object]]:
    ranked = sorted(
        fills,
        key=lambda fill: (
            -_bps(_implementation_shortfall_points(fill), _mid_price(fill) or float(fill.get("fill_price") or 0.0)),
            -abs(float(fill.get("quantity") or 0.0) * float(fill.get("fill_price") or 0.0)),
            -int(fill.get("id") or 0),
        ),
    )
    return ranked[:limit]


def generate_tca_report(config: SystemConfig | None = None, broker_symbol: str | None = None) -> TCAReport:
    config = config or SystemConfig()
    store = ExperimentStore(config.ai.experiment_database_path, read_only=True)
    fills = store.list_mt5_fill_events(broker_symbol=broker_symbol)
    generated_at = datetime.now(UTC)
    suffix = f"_{_slug(broker_symbol)}" if broker_symbol else ""
    report_path = system_reports_dir() / f"trade_cost_analysis{suffix}.txt"
    if not fills:
        report_path.write_text(
            "\n".join(
                [
                    "Trade Cost Analysis",
                    f"Generated at: {_fmt_ts(generated_at)}",
                    f"Database: {config.ai.experiment_database_path}",
                    f"Broker symbol filter: {broker_symbol or 'all'}",
                    "",
                    "No MT5 fills found in mt5_fill_events.",
                    "",
                    "TCA needs real fills. The current project already records requested price, fill price, bid/ask, spread, slippage, strategy comment and magic number.",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return TCAReport(
            generated_at=generated_at,
            broker_symbol=broker_symbol,
            overview=None,
            by_symbol=[],
            by_strategy=[],
            by_intent=[],
            by_hour=[],
            worst_fills=[],
            report_path=report_path,
        )

    overview = _aggregate("all_fills", fills)
    by_symbol = _group_aggregates(fills, lambda fill: fill.get("broker_symbol") or fill.get("requested_symbol") or "unknown")
    by_strategy = _group_aggregates(fills, _infer_strategy)
    by_intent = _group_aggregates(fills, _fill_intent)
    by_hour = _group_aggregates(fills, lambda fill: f"{_as_utc(fill['event_timestamp']).hour:02d}:00")
    worst = _worst_fills(fills)
    report_path.write_text(render_tca_report_text(generated_at, config.ai.experiment_database_path, broker_symbol, overview, by_symbol, by_strategy, by_intent, by_hour, worst), encoding="utf-8")
    return TCAReport(
        generated_at=generated_at,
        broker_symbol=broker_symbol,
        overview=overview,
        by_symbol=by_symbol,
        by_strategy=by_strategy,
        by_intent=by_intent,
        by_hour=by_hour,
        worst_fills=worst,
        report_path=report_path,
    )


def _render_table(title: str, rows: list[TCAAggregate], limit: int) -> list[str]:
    lines = [title]
    if not rows:
        lines.append("none")
        lines.append("")
        return lines
    header = f"{'label':<24} {'fills':>5} {'open':>5} {'close':>5} {'spr_avg':>9} {'slip_w_bps':>11} {'is_w_bps':>9} {'cost_bps':>9} {'adv%':>7}"
    lines.append(header)
    lines.append("-" * len(header))
    for row in rows[:limit]:
        lines.append(
            f"{row.label[:24]:<24} {row.fill_count:>5} {row.open_count:>5} {row.close_count:>5} "
            f"{_fmt_num(row.avg_spread_points, 4):>9} {_fmt_num(row.weighted_touch_slippage_bps, 3):>11} "
            f"{_fmt_num(row.weighted_shortfall_bps, 3):>9} {_fmt_num(row.weighted_cost_bps, 3):>9} {_fmt_num(row.adverse_touch_fill_rate_pct, 1):>7}"
        )
    lines.append("")
    return lines


def render_tca_report_text(
    generated_at: datetime,
    database_path: str,
    broker_symbol: str | None,
    overview: TCAAggregate,
    by_symbol: list[TCAAggregate],
    by_strategy: list[TCAAggregate],
    by_intent: list[TCAAggregate],
    by_hour: list[TCAAggregate],
    worst_fills: list[dict[str, object]],
) -> str:
    lines = [
        "Trade Cost Analysis",
        f"Generated at: {_fmt_ts(generated_at)}",
        f"Database: {database_path}",
        f"Broker symbol filter: {broker_symbol or 'all'}",
        "",
        "Overview",
        f"fills: {overview.fill_count}",
        f"window: {_fmt_ts(overview.first_fill_at)} -> {_fmt_ts(overview.last_fill_at)}",
        f"buy_vs_sell: {overview.buy_count}/{overview.sell_count}",
        f"open_vs_close: {overview.open_count}/{overview.close_count}",
        f"avg_quantity: {_fmt_num(overview.avg_quantity, 4)}",
        f"avg_spread_points: {_fmt_num(overview.avg_spread_points, 6)}",
        f"median_spread_points: {_fmt_num(overview.median_spread_points, 6)}",
        f"p75_spread_points: {_fmt_num(overview.p75_spread_points, 6)}",
        f"avg_touch_slippage_bps: {_fmt_num(overview.avg_touch_slippage_bps, 4)}",
        f"median_touch_slippage_bps: {_fmt_num(overview.median_touch_slippage_bps, 4)}",
        f"p75_touch_slippage_bps: {_fmt_num(overview.p75_touch_slippage_bps, 4)}",
        f"weighted_touch_slippage_bps: {_fmt_num(overview.weighted_touch_slippage_bps, 4)}",
        f"avg_implementation_shortfall_bps: {_fmt_num(overview.avg_shortfall_bps, 4)}",
        f"median_implementation_shortfall_bps: {_fmt_num(overview.median_shortfall_bps, 4)}",
        f"p75_implementation_shortfall_bps: {_fmt_num(overview.p75_shortfall_bps, 4)}",
        f"weighted_implementation_shortfall_bps: {_fmt_num(overview.weighted_shortfall_bps, 4)}",
        f"total_broker_costs: {_fmt_num(overview.total_costs, 4)}",
        f"avg_cost_per_fill: {_fmt_num(overview.avg_cost_per_fill, 6)}",
        f"weighted_cost_bps: {_fmt_num(overview.weighted_cost_bps, 4)}",
        f"adverse_touch_fill_rate_pct: {_fmt_num(overview.adverse_touch_fill_rate_pct, 2)}",
        f"total_notional: {_fmt_num(overview.total_notional, 2)}",
        "",
    ]
    lines.extend(_render_table("By symbol", by_symbol, limit=12))
    lines.extend(_render_table("By strategy", by_strategy, limit=15))
    lines.extend(_render_table("By intent", by_intent, limit=10))
    lines.extend(_render_table("By hour (UTC)", by_hour, limit=24))
    lines.append("Worst fills by implementation shortfall")
    if not worst_fills:
        lines.append("none")
    else:
        header = f"{'ts':<20} {'symbol':<14} {'strategy':<24} {'side':<5} {'intent':<5} {'short_bps':>9} {'slip_bps':>9} {'cost':>9}"
        lines.append(header)
        lines.append("-" * len(header))
        for fill in worst_fills:
            mid = _mid_price(fill) or float(fill.get("fill_price") or 0.0)
            lines.append(
                f"{_fmt_ts(_as_utc(fill['event_timestamp'])):<20} "
                f"{str(fill.get('broker_symbol') or '')[:14]:<14} "
                f"{_infer_strategy(fill)[:24]:<24} "
                f"{str(fill.get('side') or '')[:5]:<5} "
                f"{_fill_intent(fill)[:5]:<5} "
                f"{_fmt_num(_bps(_implementation_shortfall_points(fill), mid), 3):>9} "
                f"{_fmt_num(_bps(_signed_touch_slippage_points(fill), float(fill.get('requested_price') or 0.0) or float(fill.get('fill_price') or 0.0)), 3):>9} "
                f"{_fmt_num(abs(float(fill.get('costs') or 0.0)), 4):>9}"
            )
    lines.append("")
    lines.append("Definitions")
    lines.append("touch slippage: fill vs requested bid/ask; positive means worse execution.")
    lines.append("implementation shortfall: fill vs mid-price at decision time; this includes half-spread plus slippage.")
    return "\n".join(lines).rstrip() + "\n"
