from __future__ import annotations

import asyncio
import csv
import hashlib
from pathlib import Path
from statistics import mean

from quant_system.agents.factory import build_alpha_agents, build_shadow_candidate_agents
from quant_system.artifacts import ARTIFACTS_DIR, profile_logs_dir, profile_reports_dir, research_candidates_dir
from quant_system.config import SystemConfig
from quant_system.execution.engine import AgentCoordinator
from quant_system.models import FeatureVector, MarketBar, Side
from quant_system.profile_data import load_shadow_features
from quant_system.profile_runtime import build_system_with_agents
from quant_system.profiles import StrategyProfile


def _safe_artifact_stem(name: str, max_length: int = 140) -> str:
    if len(name) <= max_length:
        return name
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]
    trimmed = name[: max_length - 13].rstrip("_")
    return f"{trimmed}_{digest}"


def export_trade_artifacts(profile: StrategyProfile, result) -> tuple[Path, Path]:
    return export_closed_trade_artifacts(result.closed_trades, result.realized_pnl, f"{profile.name}")


def export_ai_artifacts(profile: StrategyProfile, package) -> tuple[Path, Path]:
    reports_dir = profile_reports_dir(profile.name)
    summary_path = reports_dir / "ai_summary.txt"
    experiments_path = reports_dir / "next_experiment.txt"

    summary_lines = [package.local_summary]
    if package.ai_summary:
        summary_lines.extend(["", "AI summary", package.ai_summary])
    else:
        summary_lines.extend(["", "AI summary", "AI enrichment unavailable. Local analysis only."])
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")

    experiment_lines = [f"Profile: {profile.name}", "Recommended next experiments", ""]
    experiment_lines.extend(f"- {item}" for item in package.next_experiments)
    experiments_path.write_text("\n".join(experiment_lines), encoding="utf-8")
    return summary_path, experiments_path


def export_memory_artifacts(profile: StrategyProfile, package) -> tuple[Path, Path]:
    reports_dir = profile_reports_dir(profile.name)
    history_path = reports_dir / "experiment_history.txt"
    comparison_path = reports_dir / "run_comparison.txt"
    history_path.write_text(package.history_summary, encoding="utf-8")
    comparison_path.write_text(package.comparison_summary, encoding="utf-8")
    return history_path, comparison_path


def export_agent_registry_artifact(profile: StrategyProfile, rendered_registry: str) -> Path:
    reports_dir = profile_reports_dir(profile.name)
    registry_path = reports_dir / "agent_registry.txt"
    registry_path.write_text(rendered_registry, encoding="utf-8")
    return registry_path


def export_agent_catalog_artifact(profile: StrategyProfile, rendered_catalog: str) -> Path:
    reports_dir = profile_reports_dir(profile.name)
    catalog_path = reports_dir / "agent_catalog.txt"
    catalog_path.write_text(rendered_catalog, encoding="utf-8")
    return catalog_path


def export_closed_trade_artifacts(closed_trades, realized_pnl: float, artifact_prefix: str) -> tuple[Path, Path]:
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    symbol = artifact_prefix.split("_", 1)[0]
    safe_prefix = _safe_artifact_stem(artifact_prefix)
    file_stem = safe_prefix[len(symbol) + 1 :] if safe_prefix.startswith(f"{symbol}_") else safe_prefix
    file_stem = _safe_artifact_stem(file_stem, max_length=110)
    candidate_dir = research_candidates_dir(symbol)
    trades_path = candidate_dir / f"{file_stem}_trades.csv"
    analysis_path = candidate_dir / f"{file_stem}_analysis.txt"

    with trades_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "symbol",
                "entry_timestamp",
                "exit_timestamp",
                "entry_hour",
                "exit_hour",
                "entry_reason",
                "exit_reason",
                "entry_price",
                "exit_price",
                "quantity",
                "pnl",
                "costs",
                "hold_bars",
                "entry_confidence",
                "entry_metadata",
            ]
        )
        for trade in closed_trades:
            writer.writerow(
                [
                    trade.symbol,
                    trade.entry_timestamp.isoformat(),
                    trade.exit_timestamp.isoformat(),
                    trade.entry_hour,
                    trade.exit_hour,
                    trade.entry_reason,
                    trade.exit_reason,
                    f"{trade.entry_price:.5f}",
                    f"{trade.exit_price:.5f}",
                    f"{trade.quantity:.5f}",
                    f"{trade.pnl:.5f}",
                    f"{trade.costs:.5f}",
                    trade.hold_bars,
                    f"{trade.entry_confidence:.5f}",
                    trade.entry_metadata,
                ]
            )

    by_hour: dict[int, list[float]] = {}
    by_setup: dict[str, list[float]] = {}
    by_exit: dict[str, list[float]] = {}
    for trade in closed_trades:
        by_hour.setdefault(trade.entry_hour, []).append(trade.pnl)
        by_setup.setdefault(trade.entry_reason, []).append(trade.pnl)
        by_exit.setdefault(trade.exit_reason, []).append(trade.pnl)

    def render_bucket(title: str, buckets: dict[object, list[float]]) -> list[str]:
        lines = [title]
        for key, pnls in sorted(buckets.items(), key=lambda item: (sum(item[1]), len(item[1]))):
            wins = sum(1 for pnl in pnls if pnl > 0)
            lines.append(
                f"{key}: trades={len(pnls)} pnl={sum(pnls):.2f} avg={sum(pnls)/len(pnls):.2f} win_rate={wins/len(pnls)*100.0:.2f}%"
            )
        return lines

    analysis_lines = [
        f"Artifact: {file_stem}",
        f"Closed trades: {len(closed_trades)}",
        f"Realized pnl: {realized_pnl:.2f}",
        "",
    ]
    analysis_lines.extend(render_bucket("By entry hour", by_hour))
    analysis_lines.append("")
    analysis_lines.extend(render_bucket("By entry setup", by_setup))
    analysis_lines.append("")
    analysis_lines.extend(render_bucket("By exit reason", by_exit))
    analysis_path.write_text("\n".join(analysis_lines), encoding="utf-8")
    return trades_path, analysis_path


def export_shadow_execution_artifacts(
    config: SystemConfig,
    profile: StrategyProfile,
    features: list[FeatureVector],
    optimized_agents,
) -> tuple[Path, Path] | tuple[None, None]:
    del features
    candidates = build_shadow_candidate_agents(optimized_agents, config.risk, profile.name)
    if not candidates:
        return None, None
    shadow_features, shadow_data_source = load_shadow_features(config, profile)

    logs_dir = profile_logs_dir(profile.name)
    reports_dir = profile_reports_dir(profile.name)
    csv_path = logs_dir / "shadow_setups.csv"
    analysis_path = reports_dir / "shadow_setups.txt"
    rows: list[dict[str, object]] = []

    for setup_name, agents in candidates.items():
        engine = build_system_with_agents(config, agents, optimized_agents.consensus_min_confidence)
        result = asyncio.run(engine.run(shadow_features, sleep_seconds=0.0))
        export_closed_trade_artifacts(
            result.closed_trades,
            result.realized_pnl,
            f"{profile.name}_{setup_name}_shadow",
        )
        rows.append(
            {
                "setup_name": setup_name,
                "trades": result.trades,
                "closed_trades": len(result.closed_trades),
                "realized_pnl": result.realized_pnl,
                "win_rate_pct": result.win_rate_pct,
                "profit_factor": result.profit_factor,
                "max_drawdown_pct": result.max_drawdown * 100.0,
                "total_costs": result.total_costs,
                "kill_switch_triggered": result.locked,
                "data_source": shadow_data_source,
            }
        )

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "setup_name",
                "trades",
                "closed_trades",
                "realized_pnl",
                "win_rate_pct",
                "profit_factor",
                "max_drawdown_pct",
                "total_costs",
                "kill_switch_triggered",
                "data_source",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["setup_name"],
                    row["trades"],
                    row["closed_trades"],
                    f"{float(row['realized_pnl']):.5f}",
                    f"{float(row['win_rate_pct']):.5f}",
                    f"{float(row['profit_factor']):.5f}",
                    f"{float(row['max_drawdown_pct']):.5f}",
                    f"{float(row['total_costs']):.5f}",
                    row["kill_switch_triggered"],
                    row["data_source"],
                ]
            )

    ranked_rows = sorted(
        rows,
        key=lambda row: (
            float(row["realized_pnl"]),
            float(row["profit_factor"]),
            float(row["win_rate_pct"]),
            -float(row["total_costs"]),
        ),
        reverse=True,
    )
    analysis_lines = [
        f"Profile: {profile.name}",
        "Shadow execution by setup",
        "",
    ]
    for row in ranked_rows:
        analysis_lines.append(
            f"{row['setup_name']}: pnl={float(row['realized_pnl']):.2f} closed={row['closed_trades']} pf={float(row['profit_factor']):.2f} win_rate={float(row['win_rate_pct']):.2f}% costs={float(row['total_costs']):.2f} data_source={row['data_source']}"
        )
    analysis_path.write_text("\n".join(analysis_lines), encoding="utf-8")
    return csv_path, analysis_path


def export_signal_artifacts(
    config: SystemConfig,
    profile: StrategyProfile,
    features: list[FeatureVector],
    optimized_agents,
) -> tuple[Path, Path]:
    logs_dir = profile_logs_dir(profile.name)
    reports_dir = profile_reports_dir(profile.name)
    signals_path = logs_dir / "signals.csv"
    analysis_path = reports_dir / "signals_analysis.txt"
    agents = build_alpha_agents(optimized_agents, config.risk, profile.name)
    coordinator = AgentCoordinator(agents, consensus_min_confidence=optimized_agents.consensus_min_confidence)
    horizons = (3, 6, 12)
    signal_rows: list[dict[str, object]] = []
    by_setup: dict[str, list[float]] = {}
    by_hour: dict[int, list[float]] = {}
    accepted_by_setup: dict[str, int] = {}

    for index, feature in enumerate(features):
        decision_context = coordinator.evaluate(feature)
        consensus_reasons = set(decision_context.reasons) if decision_context is not None else set()
        for agent in agents:
            signal = agent.on_feature(feature)
            if signal is None or signal.side != Side.BUY or signal.agent_name == "risk_sentinel":
                continue
            forward_returns: dict[int, float | None] = {}
            for horizon in horizons:
                target_index = index + horizon
                if target_index >= len(features):
                    forward_returns[horizon] = None
                    continue
                target_close = features[target_index].values["close"]
                forward_returns[horizon] = ((target_close / feature.values["close"]) - 1.0) * 100.0
            signal_rows.append(
                {
                    "timestamp": feature.timestamp.isoformat(),
                    "hour": int(feature.values.get("hour_of_day", feature.timestamp.hour)),
                    "agent_name": signal.agent_name,
                    "confidence": signal.confidence,
                    "consensus_accepted": signal.agent_name in consensus_reasons,
                    "forward_return_3": forward_returns[3],
                    "forward_return_6": forward_returns[6],
                    "forward_return_12": forward_returns[12],
                    "metadata": signal.metadata,
                }
            )
            if forward_returns[6] is not None:
                by_setup.setdefault(signal.agent_name, []).append(forward_returns[6])
                by_hour.setdefault(int(feature.values.get("hour_of_day", feature.timestamp.hour)), []).append(forward_returns[6])
            if signal.agent_name in consensus_reasons:
                accepted_by_setup[signal.agent_name] = accepted_by_setup.get(signal.agent_name, 0) + 1

    with signals_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "timestamp",
                "hour",
                "agent_name",
                "confidence",
                "consensus_accepted",
                "forward_return_3_pct",
                "forward_return_6_pct",
                "forward_return_12_pct",
                "metadata",
            ]
        )
        for row in signal_rows:
            writer.writerow(
                [
                    row["timestamp"],
                    row["hour"],
                    row["agent_name"],
                    f"{float(row['confidence']):.5f}",
                    row["consensus_accepted"],
                    "" if row["forward_return_3"] is None else f"{float(row['forward_return_3']):.5f}",
                    "" if row["forward_return_6"] is None else f"{float(row['forward_return_6']):.5f}",
                    "" if row["forward_return_12"] is None else f"{float(row['forward_return_12']):.5f}",
                    row["metadata"],
                ]
            )

    analysis_lines = [
        f"Profile: {profile.name}",
        f"Candidate buy signals: {len(signal_rows)}",
        "",
        "By setup (6-bar forward return)",
    ]
    for setup, returns in sorted(by_setup.items(), key=lambda item: mean(item[1]) if item[1] else -999.0):
        wins = sum(1 for value in returns if value > 0)
        analysis_lines.append(
            f"{setup}: signals={len(returns)} accepted={accepted_by_setup.get(setup, 0)} avg_6bar={mean(returns):.3f}% win_rate={wins/len(returns)*100.0:.2f}%"
        )
    analysis_lines.append("")
    analysis_lines.append("By hour (6-bar forward return)")
    for hour, returns in sorted(by_hour.items(), key=lambda item: mean(item[1]) if item[1] else -999.0):
        wins = sum(1 for value in returns if value > 0)
        analysis_lines.append(
            f"{hour}: signals={len(returns)} avg_6bar={mean(returns):.3f}% win_rate={wins/len(returns)*100.0:.2f}%"
        )
    analysis_path.write_text("\n".join(analysis_lines), encoding="utf-8")
    return signals_path, analysis_path
