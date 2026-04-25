from __future__ import annotations

from quant_system.models import ClosedTradeRecord, FeatureVector
from quant_system.research.funding import infer_feature_bar_hours
from quant_system.symbols import (
    is_crypto_symbol,
    is_forex_symbol,
    is_index_symbol,
    is_metal_symbol,
)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _ultra_short_hold_threshold_hours(symbol: str, bar_hours: float) -> float:
    upper = symbol.upper()
    if is_crypto_symbol(upper):
        base = 0.25
    elif is_forex_symbol(upper) or is_metal_symbol(upper):
        base = 0.50
    elif is_index_symbol(upper):
        base = 0.25
    else:
        base = 0.25
    if bar_hours > 0.0:
        return max(base, bar_hours * 2.0)
    return base


def estimate_prop_rule_fit(
    *,
    symbol: str,
    features: list[FeatureVector],
    closed_trades: list[ClosedTradeRecord],
    avg_win: float,
    payoff_ratio: float,
    total_costs: float,
    stress_expectancy_medium: float,
    stress_pf_medium: float,
) -> dict[str, object]:
    if not closed_trades:
        return {
            "prop_fit_score": 0.0,
            "prop_fit_label": "fail",
            "prop_fit_reasons": ("no_closed_trades_for_prop_fit",),
            "news_window_trade_share": 0.0,
            "sub_short_hold_share": 0.0,
            "micro_target_risk_flag": False,
            "execution_dependency_flag": True,
        }

    feature_by_timestamp = {feature.timestamp: feature for feature in features}
    news_window_trades = 0
    ultra_short_trades = 0
    bar_hours = infer_feature_bar_hours(features)
    ultra_short_threshold_hours = _ultra_short_hold_threshold_hours(symbol, bar_hours)
    for trade in closed_trades:
        feature = feature_by_timestamp.get(trade.entry_timestamp)
        values = feature.values if feature is not None else {}
        in_news_window = (
            float(values.get("macro_pre_event_window", 0.0) or 0.0) > 0.0
            or float(values.get("macro_post_event_window", 0.0) or 0.0) > 0.0
            or float(values.get("macro_event_blackout", 0.0) or 0.0) > 0.0
            or float(values.get("macro_high_impact_event_day", 0.0) or 0.0) > 0.0
            or float(values.get("event_blackout", 0.0) or 0.0) > 0.0
            or float(values.get("high_impact_event_day", 0.0) or 0.0) > 0.0
        )
        if in_news_window:
            news_window_trades += 1
        hold_hours = max(0.0, float(trade.hold_bars)) * max(bar_hours, 0.0)
        if hold_hours > 0.0 and hold_hours <= ultra_short_threshold_hours:
            ultra_short_trades += 1

    closed_count = float(len(closed_trades))
    news_window_trade_share = news_window_trades / closed_count if closed_count > 0.0 else 0.0
    sub_short_hold_share = ultra_short_trades / closed_count if closed_count > 0.0 else 0.0
    avg_cost_per_trade = max(float(total_costs), 0.0) / closed_count if closed_count > 0.0 else 0.0
    micro_target_risk_flag = bool(avg_win > 0.0 and avg_cost_per_trade > 0.0 and (avg_win <= (avg_cost_per_trade * 3.0)))
    execution_dependency_flag = bool(
        news_window_trade_share >= 0.35
        or sub_short_hold_share >= 0.55
        or micro_target_risk_flag
        or stress_expectancy_medium <= 0.0
        or stress_pf_medium < 1.0
        or payoff_ratio < 1.15
    )

    reasons: list[str] = []
    if news_window_trade_share >= 0.45:
        reasons.append("news_window_trade_share_too_high")
    elif news_window_trade_share >= 0.25:
        reasons.append("news_window_trade_share_elevated")
    if sub_short_hold_share >= 0.60:
        reasons.append("sub_short_hold_share_too_high")
    elif sub_short_hold_share >= 0.35:
        reasons.append("sub_short_hold_share_elevated")
    if micro_target_risk_flag:
        reasons.append("micro_target_risk_flag")
    if execution_dependency_flag:
        reasons.append("execution_dependency_flag")

    prop_fit_score = 1.0
    prop_fit_score -= min(0.40, news_window_trade_share * 0.80)
    prop_fit_score -= min(0.30, sub_short_hold_share * 0.50)
    if micro_target_risk_flag:
        prop_fit_score -= 0.15
    if execution_dependency_flag:
        prop_fit_score -= 0.15
    prop_fit_score = round(_clamp01(prop_fit_score), 4)

    if any(reason in reasons for reason in ("news_window_trade_share_too_high", "sub_short_hold_share_too_high")):
        label = "fail"
    elif reasons:
        label = "caution"
    else:
        label = "pass"
    return {
        "prop_fit_score": prop_fit_score,
        "prop_fit_label": label,
        "prop_fit_reasons": tuple(reasons),
        "news_window_trade_share": round(news_window_trade_share, 4),
        "sub_short_hold_share": round(sub_short_hold_share, 4),
        "micro_target_risk_flag": micro_target_risk_flag,
        "execution_dependency_flag": execution_dependency_flag,
    }
