from __future__ import annotations

import copy
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from quant_system.artifacts import live_symbol_dir, system_reports_dir
from quant_system.config import SystemConfig
from quant_system.live.activity import record_adaptation_result
from quant_system.live.models import DeploymentStrategy, SymbolDeployment
from quant_system.tca import TCAAggregate, generate_tca_report


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


@dataclass(slots=True)
class StrategyAdaptation:
    candidate_name: str
    fill_count: int
    action: str
    base_weight_scale: float
    risk_scale: float
    min_bars_between_trades: int
    resulting_base_weight: float
    resulting_max_risk_multiplier: float
    local_rank_label: str
    reason: str


@dataclass(slots=True)
class ExecutionAdaptationResult:
    symbol: str
    broker_symbol: str
    action: str
    adapted: bool
    reason: str
    fill_count: int
    weighted_shortfall_bps: float
    weighted_cost_bps: float
    adverse_fill_rate_pct: float
    guardrail_reason: str
    strategy_actions: list[StrategyAdaptation]
    report_path: Path


def _apply_live_guardrails(
    original: SymbolDeployment,
    adapted: SymbolDeployment,
    action: str,
    reason: str,
    strategy_actions: list[StrategyAdaptation],
) -> tuple[SymbolDeployment, str, str, str]:
    min_active_strategies = _env_int("LIVE_GUARDRAIL_MIN_ACTIVE_STRATEGIES_PER_SYMBOL", 1)
    max_severe_demotions = _env_int("LIVE_GUARDRAIL_MAX_SEVERE_DEMOTIONS_PER_SYMBOL", 1)
    severe_block_fill_threshold = _env_int("LIVE_GUARDRAIL_MIN_FILLS_TO_BLOCK", 12)
    guardrail_notes: list[str] = []

    original_map = {item.candidate_name: item for item in original.strategies}
    active_candidates = set(item.candidate_name for item in adapted.strategies)
    severe_actions = [item for item in strategy_actions if item.action == "demote_severe"]
    if len(severe_actions) > max_severe_demotions:
        for item in severe_actions[max_severe_demotions:]:
            strategy = next((row for row in adapted.strategies if row.candidate_name == item.candidate_name), None)
            baseline = original_map.get(item.candidate_name)
            if strategy is None or baseline is None:
                continue
            strategy.base_allocation_weight = baseline.base_allocation_weight
            strategy.max_risk_multiplier = min(strategy.max_risk_multiplier, max(0.20, baseline.max_risk_multiplier * 0.80))
            strategy.execution_overrides.pop("tca_block_new_entries", None)
            strategy.execution_overrides["risk_per_trade_pct"] = max(
                0.001,
                float(strategy.execution_overrides.get("risk_per_trade_pct", 0.015) or 0.015),
            )
            item.action = "guardrail_capped_severe_demotion"
            item.local_rank_label = "guardrail_reduced_local"
            item.reason = "guardrail: capped number of severe demotions"
            guardrail_notes.append(f"capped severe demotions for {item.candidate_name}")

    blocked_count = 0
    for item in strategy_actions:
        strategy = next((row for row in adapted.strategies if row.candidate_name == item.candidate_name), None)
        if strategy is None:
            continue
        if int(strategy.execution_overrides.get("tca_block_new_entries", 0) or 0) > 0:
            if item.fill_count < severe_block_fill_threshold:
                strategy.execution_overrides.pop("tca_block_new_entries", None)
                item.action = "guardrail_block_removed"
                item.local_rank_label = "guardrail_reduced_local"
                item.reason = "guardrail: not enough fills for full block"
                guardrail_notes.append(f"removed block for {item.candidate_name} due to low fill count")
            else:
                blocked_count += 1

    if len(active_candidates) - blocked_count < min_active_strategies:
        restored = 0
        for item in sorted(strategy_actions, key=lambda row: (row.action != "demote_severe", row.fill_count)):
            strategy = next((row for row in adapted.strategies if row.candidate_name == item.candidate_name), None)
            baseline = original_map.get(item.candidate_name)
            if strategy is None or baseline is None:
                continue
            if int(strategy.execution_overrides.get("tca_block_new_entries", 0) or 0) <= 0:
                continue
            strategy.execution_overrides.pop("tca_block_new_entries", None)
            strategy.base_allocation_weight = max(0.10, baseline.base_allocation_weight * 0.50)
            strategy.max_risk_multiplier = max(0.10, baseline.max_risk_multiplier * 0.50)
            strategy.execution_overrides["risk_per_trade_pct"] = max(0.0005, float(baseline.execution_overrides.get("risk_per_trade_pct", 0.015) or 0.015) * 0.50)
            item.action = "guardrail_kept_one_live"
            item.local_rank_label = "guardrail_min_coverage"
            item.reason = "guardrail: preserved minimum live coverage"
            restored += 1
            blocked_count -= 1
            if len(active_candidates) - blocked_count >= min_active_strategies:
                break
        if restored > 0:
            guardrail_notes.append(f"restored {restored} blocked strategies to preserve minimum coverage")

    if all(int(item.execution_overrides.get("tca_block_new_entries", 0) or 0) > 0 for item in adapted.strategies) and adapted.strategies:
        adapted.symbol_status = original.symbol_status
        guardrail_notes.append("reverted symbol status change to preserve live presence")

    guardrail_reason = "; ".join(guardrail_notes) if guardrail_notes else "none"
    if guardrail_notes:
        reason = f"{reason} | guardrails: {guardrail_reason}"
        action = f"{action}_guardrailed"
    return adapted, action, reason, guardrail_reason


def _severity(row: TCAAggregate | None, *, min_fills: int, moderate_shortfall_bps: float, severe_shortfall_bps: float, moderate_cost_bps: float, severe_cost_bps: float, moderate_adverse_fill_rate_pct: float, severe_adverse_fill_rate_pct: float) -> str:
    if row is None or row.fill_count < min_fills:
        return "insufficient"
    severe_hits = 0
    moderate_hits = 0
    if row.weighted_shortfall_bps >= severe_shortfall_bps:
        severe_hits += 1
    elif row.weighted_shortfall_bps >= moderate_shortfall_bps:
        moderate_hits += 1
    if row.weighted_cost_bps >= severe_cost_bps:
        severe_hits += 1
    elif row.weighted_cost_bps >= moderate_cost_bps:
        moderate_hits += 1
    if row.adverse_touch_fill_rate_pct >= severe_adverse_fill_rate_pct:
        severe_hits += 1
    elif row.adverse_touch_fill_rate_pct >= moderate_adverse_fill_rate_pct:
        moderate_hits += 1
    if severe_hits > 0:
        return "severe"
    if moderate_hits > 0:
        return "moderate"
    return "healthy"


def _find_strategy_row(rows: list[TCAAggregate], strategy: DeploymentStrategy) -> TCAAggregate | None:
    target = strategy.candidate_name.strip().lower()
    truncated = target[:31]
    for row in rows:
        label = row.label.strip().lower()
        if label == target or label == truncated:
            return row
        if target.startswith(label) or label.startswith(truncated):
            return row
    return None


def _apply_strategy_adjustment(strategy: DeploymentStrategy, severity: str) -> StrategyAdaptation:
    promote_fill_count = _env_int("EXEC_ADAPTATION_PROMOTE_MIN_STRATEGY_FILLS", 10)
    promote_weight_scale = _env_float("EXEC_ADAPTATION_PROMOTE_BASE_WEIGHT_SCALE", 1.08)
    promote_risk_scale = _env_float("EXEC_ADAPTATION_PROMOTE_RISK_SCALE", 1.05)
    if severity == "severe":
        base_weight_scale = 0.35
        risk_scale = 0.45
        min_bars_increment = 6
        action = "demote_severe"
        local_rank_label = "blocked_local"
    elif severity == "moderate":
        base_weight_scale = 0.80
        risk_scale = 0.80
        min_bars_increment = 2
        action = "demote_moderate"
        local_rank_label = "reduced_local"
    elif severity == "healthy":
        if strategy.execution_overrides.get("__tca_fill_count__", 0) >= promote_fill_count:
            base_weight_scale = promote_weight_scale
            risk_scale = promote_risk_scale
            min_bars_increment = 0
            action = "promote_healthy"
            local_rank_label = "promoted_local"
        else:
            return StrategyAdaptation(
                candidate_name=strategy.candidate_name,
                fill_count=0,
                action="unchanged",
                base_weight_scale=1.0,
                risk_scale=1.0,
                min_bars_between_trades=int(strategy.execution_overrides.get("min_bars_between_trades", 0) or 0),
                resulting_base_weight=strategy.base_allocation_weight,
                resulting_max_risk_multiplier=strategy.max_risk_multiplier,
                local_rank_label="baseline_local",
                reason="healthy_but_not_enough_strategy_fills_for_promotion",
            )
    else:
        return StrategyAdaptation(
            candidate_name=strategy.candidate_name,
            fill_count=0,
            action="unchanged",
            base_weight_scale=1.0,
            risk_scale=1.0,
            min_bars_between_trades=int(strategy.execution_overrides.get("min_bars_between_trades", 0) or 0),
            resulting_base_weight=strategy.base_allocation_weight,
            resulting_max_risk_multiplier=strategy.max_risk_multiplier,
            local_rank_label="baseline_local",
            reason="healthy_or_insufficient_data",
        )

    strategy.base_allocation_weight = max(0.10, strategy.base_allocation_weight * base_weight_scale)
    strategy.max_risk_multiplier = max(0.10, strategy.max_risk_multiplier * risk_scale)
    current_risk_pct = float(strategy.execution_overrides.get("risk_per_trade_pct", 0.015) or 0.015)
    current_min_bars = int(strategy.execution_overrides.get("min_bars_between_trades", 8) or 8)
    strategy.execution_overrides["risk_per_trade_pct"] = max(0.001, current_risk_pct * risk_scale)
    strategy.execution_overrides["min_bars_between_trades"] = current_min_bars + min_bars_increment
    if severity == "severe":
        strategy.min_risk_multiplier = 0.0
        strategy.execution_overrides["risk_per_trade_pct"] = max(0.0005, current_risk_pct * 0.35)
        strategy.execution_overrides["tca_block_new_entries"] = 1
    return StrategyAdaptation(
        candidate_name=strategy.candidate_name,
        fill_count=0,
        action=action,
        base_weight_scale=base_weight_scale,
        risk_scale=risk_scale,
        min_bars_between_trades=int(strategy.execution_overrides["min_bars_between_trades"]),
        resulting_base_weight=strategy.base_allocation_weight,
        resulting_max_risk_multiplier=strategy.max_risk_multiplier,
        local_rank_label=local_rank_label,
        reason=f"{severity}_execution_tca",
    )


def adapt_deployment_for_execution(deployment: SymbolDeployment, config: SystemConfig | None = None) -> tuple[SymbolDeployment, ExecutionAdaptationResult]:
    config = config or SystemConfig()
    min_symbol_fills = _env_int("EXEC_ADAPTATION_MIN_SYMBOL_FILLS", 12)
    min_strategy_fills = _env_int("EXEC_ADAPTATION_MIN_STRATEGY_FILLS", 4)
    moderate_shortfall_bps = _env_float("EXEC_ADAPTATION_MODERATE_SHORTFALL_BPS", 3.0)
    severe_shortfall_bps = _env_float("EXEC_ADAPTATION_SEVERE_SHORTFALL_BPS", 6.0)
    moderate_cost_bps = _env_float("EXEC_ADAPTATION_MODERATE_COST_BPS", 1.5)
    severe_cost_bps = _env_float("EXEC_ADAPTATION_SEVERE_COST_BPS", 3.0)
    moderate_adverse_fill_rate_pct = _env_float("EXEC_ADAPTATION_MODERATE_ADVERSE_FILL_RATE_PCT", 65.0)
    severe_adverse_fill_rate_pct = _env_float("EXEC_ADAPTATION_SEVERE_ADVERSE_FILL_RATE_PCT", 80.0)

    adapted = copy.deepcopy(deployment)
    tca_report = generate_tca_report(config, broker_symbol=deployment.broker_symbol)
    overview = tca_report.overview
    symbol_severity = _severity(
        overview,
        min_fills=min_symbol_fills,
        moderate_shortfall_bps=moderate_shortfall_bps,
        severe_shortfall_bps=severe_shortfall_bps,
        moderate_cost_bps=moderate_cost_bps,
        severe_cost_bps=severe_cost_bps,
        moderate_adverse_fill_rate_pct=moderate_adverse_fill_rate_pct,
        severe_adverse_fill_rate_pct=severe_adverse_fill_rate_pct,
    )
    strategy_actions: list[StrategyAdaptation] = []

    if symbol_severity == "severe":
        adapted.symbol_status = "reduced_risk_only"
        adapted.max_symbol_vol_percentile = min(adapted.max_symbol_vol_percentile, 0.92)
        action = "symbol_de_risk_severe"
        reason = "symbol execution too expensive or too adverse"
    elif symbol_severity == "moderate":
        adapted.max_symbol_vol_percentile = min(adapted.max_symbol_vol_percentile, 0.95)
        action = "symbol_de_risk_moderate"
        reason = "symbol execution degraded"
    elif symbol_severity == "healthy":
        action = "healthy"
        reason = "execution within thresholds"
    else:
        action = "insufficient_data"
        reason = "not enough local fills for adaptation"

    for strategy in adapted.strategies:
        row = _find_strategy_row(tca_report.by_strategy, strategy)
        strategy.execution_overrides["__tca_fill_count__"] = row.fill_count if row is not None else 0
        severity = _severity(
            row,
            min_fills=min_strategy_fills,
            moderate_shortfall_bps=moderate_shortfall_bps,
            severe_shortfall_bps=severe_shortfall_bps,
            moderate_cost_bps=moderate_cost_bps,
            severe_cost_bps=severe_cost_bps,
            moderate_adverse_fill_rate_pct=moderate_adverse_fill_rate_pct,
            severe_adverse_fill_rate_pct=severe_adverse_fill_rate_pct,
        )
        strategy_action = _apply_strategy_adjustment(strategy, severity if severity in {"moderate", "severe", "healthy"} else "insufficient")
        if row is not None:
            strategy_action.fill_count = row.fill_count
            if severity in {"moderate", "severe", "healthy"}:
                strategy_action.reason = (
                    f"{severity}: shortfall={row.weighted_shortfall_bps:.3f}bps "
                    f"cost={row.weighted_cost_bps:.3f}bps adverse={row.adverse_touch_fill_rate_pct:.1f}%"
                )
        strategy.execution_overrides.pop("__tca_fill_count__", None)
        strategy_actions.append(strategy_action)

    severe_count = sum(1 for item in strategy_actions if item.action == "demote_severe")
    promoted_count = sum(1 for item in strategy_actions if item.action == "promote_healthy")
    if severe_count >= max(1, len(strategy_actions)):
        adapted.symbol_status = "reduced_risk_only"
        adapted.max_symbol_vol_percentile = min(adapted.max_symbol_vol_percentile, 0.90)
        action = "all_strategies_demoted"
        reason = "all local strategies have severe execution drag"
    elif promoted_count > 0 and action == "healthy":
        reason = f"execution within thresholds; promoted_strategies={promoted_count}"

    adapted, action, reason, guardrail_reason = _apply_live_guardrails(
        deployment,
        adapted,
        action,
        reason,
        strategy_actions,
    )

    result = ExecutionAdaptationResult(
        symbol=adapted.symbol,
        broker_symbol=adapted.broker_symbol,
        action=action,
        adapted=action not in {"healthy", "insufficient_data"},
        reason=reason,
        fill_count=overview.fill_count if overview is not None else 0,
        weighted_shortfall_bps=overview.weighted_shortfall_bps if overview is not None else 0.0,
        weighted_cost_bps=overview.weighted_cost_bps if overview is not None else 0.0,
        adverse_fill_rate_pct=overview.adverse_touch_fill_rate_pct if overview is not None else 0.0,
        guardrail_reason=guardrail_reason,
        strategy_actions=strategy_actions,
        report_path=_write_adaptation_artifact(adapted, action, reason, overview, strategy_actions),
    )
    return adapted, result


def summarize_execution_adaptation(result: ExecutionAdaptationResult) -> str:
    return (
        f"{result.action} fills={result.fill_count} "
        f"w_shortfall_bps={result.weighted_shortfall_bps:.3f} "
        f"w_cost_bps={result.weighted_cost_bps:.3f} "
        f"adverse_fill_rate_pct={result.adverse_fill_rate_pct:.1f}"
    )


def _write_adaptation_artifact(
    deployment: SymbolDeployment,
    action: str,
    reason: str,
    overview: TCAAggregate | None,
    strategy_actions: list[StrategyAdaptation],
) -> Path:
    path = live_symbol_dir(deployment.symbol) / "execution_adaptation.json"
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "symbol": deployment.symbol,
        "broker_symbol": deployment.broker_symbol,
        "action": action,
        "reason": reason,
        "overview": asdict(overview) if overview is not None else None,
        "strategy_actions": [asdict(item) for item in strategy_actions],
        "adapted_deployment": asdict(deployment),
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def generate_execution_adaptation_report(config: SystemConfig | None = None) -> Path:
    from quant_system.artifacts import DEPLOY_DIR
    from quant_system.live.deploy import load_symbol_deployment

    config = config or SystemConfig()
    lines = [
        "Execution adaptation report",
        f"generated_at: {datetime.now(UTC).isoformat()}",
        "",
    ]
    for path in sorted(DEPLOY_DIR.glob("*/live.json")) if DEPLOY_DIR.exists() else []:
        deployment = load_symbol_deployment(path)
        adapted, result = adapt_deployment_for_execution(deployment, config)
        del adapted
        record_adaptation_result(result)
        lines.append(f"{deployment.symbol}: {summarize_execution_adaptation(result)}")
        lines.append(f"  reason: {result.reason}")
        lines.append(f"  guardrail: {result.guardrail_reason}")
        lines.append(f"  artifact: {result.report_path}")
        for item in result.strategy_actions:
            lines.append(
                f"  strategy {item.candidate_name}: {item.action} fills={item.fill_count} "
                f"scale={item.base_weight_scale:.2f}/{item.risk_scale:.2f} "
                f"base_weight={item.resulting_base_weight:.2f} max_risk={item.resulting_max_risk_multiplier:.2f} "
                f"min_bars={item.min_bars_between_trades} rank={item.local_rank_label}"
            )
        lines.append("")
    report_path = system_reports_dir() / "execution_adaptation_report.txt"
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return report_path
