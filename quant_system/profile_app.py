from __future__ import annotations

import asyncio
import logging
import time

from quant_system.ai.analysis import build_profile_analysis
from quant_system.ai.history import build_experiment_memory_report
from quant_system.ai.models import ProfileArtifacts
from quant_system.ai.registry import build_agent_registry_records, render_agent_catalog, render_agent_registry
from quant_system.ai.storage import ExperimentStore
from quant_system.agents.factory import describe_profile_agents
from quant_system.config import SystemConfig
from quant_system.evaluation.report import build_ftmo_report
from quant_system.logging_utils import configure_logging
from quant_system.optimization.walk_forward import SimpleParameterOptimizer
from quant_system.profile_data import (
    configure_profile_execution,
    configure_profile_optimization,
    load_features,
)
from quant_system.profile_reporting import (
    export_agent_catalog_artifact,
    export_agent_registry_artifact,
    export_ai_artifacts,
    export_memory_artifacts,
    export_shadow_execution_artifacts,
    export_signal_artifacts,
    export_trade_artifacts,
)
from quant_system.profile_runtime import build_system, maybe_place_live_order
from quant_system.profiles import StrategyProfile, resolve_profiles


LOGGER = logging.getLogger(__name__)


def run_profile(config: SystemConfig, profile: StrategyProfile) -> list[str]:
    try:
        configure_profile_execution(config, profile)
        configure_profile_optimization(config, profile)
        features, data_source = load_features(config, profile)
        optimized_agents = SimpleParameterOptimizer(
            config.optimization,
            config.execution,
            config.risk,
            profile.name,
        ).fit(features, config.agents)
        LOGGER.info("profile=%s optimized agent config=%s", profile.name, optimized_agents)
        engine = build_system(config, optimized_agents)
        result = asyncio.run(engine.run(features, sleep_seconds=config.execution.bar_interval_seconds))
        trades_path, analysis_path = export_trade_artifacts(profile, result)
        shadow_csv_path, shadow_analysis_path = export_shadow_execution_artifacts(config, profile, features, optimized_agents)
        signals_path, signals_analysis_path = export_signal_artifacts(config, profile, features, optimized_agents)
        maybe_place_live_order(config, features, optimized_agents)
        report = build_ftmo_report(result, config.execution.initial_cash, config.risk, config.ftmo, config.instrument)
        artifacts = ProfileArtifacts(
            trade_log=trades_path,
            trade_analysis=analysis_path,
            signal_log=signals_path,
            signal_analysis=signals_analysis_path,
            shadow_log=shadow_csv_path,
            shadow_analysis=shadow_analysis_path,
        )
        analysis_package = build_profile_analysis(
            profile=profile,
            result=result,
            report=report,
            artifacts=artifacts,
            ai_config=config.ai,
        )
        ai_summary_path, next_experiment_path = export_ai_artifacts(profile, analysis_package)
        experiment_store = ExperimentStore(config.ai.experiment_database_path)
        experiment_id = experiment_store.record_experiment(
            profile=profile,
            result=result,
            report=report,
            optimized_agents=optimized_agents,
            artifacts=artifacts,
            local_summary=analysis_package.local_summary,
            ai_summary=analysis_package.ai_summary,
            next_experiments=analysis_package.next_experiments,
        )
        descriptors = describe_profile_agents(optimized_agents, config.risk, profile.name)
        agent_records = build_agent_registry_records(profile.name, artifacts)
        experiment_store.record_agent_registry(experiment_id, agent_records)
        experiment_store.record_agent_lifecycle(
            experiment_id=experiment_id,
            profile=profile,
            descriptors=descriptors,
            registry_records=agent_records,
            optimized_agents=optimized_agents,
        )
        registry_text = render_agent_registry(agent_records, profile.name)
        registry_path = export_agent_registry_artifact(profile, registry_text)
        catalog_text = render_agent_catalog(profile.name, experiment_store.list_agent_catalog(profile.name))
        catalog_path = export_agent_catalog_artifact(profile, catalog_text)
        current_run, previous_run = experiment_store.compare_latest_runs(profile.name)
        recent_runs = experiment_store.list_recent_experiments(profile.name, limit=config.ai.history_lookback)
        best_run = experiment_store.get_best_experiment(profile.name)
        memory_package = build_experiment_memory_report(
            profile_name=profile.name,
            recent_runs=recent_runs,
            best_run=best_run,
            current_run=current_run,
            previous_run=previous_run,
        )
        history_path, comparison_path = export_memory_artifacts(profile, memory_package)
        LOGGER.info(
            "profile=%s finished ending_equity=%.2f realized_pnl=%.2f trades=%d locked=%s",
            profile.name,
            result.ending_equity,
            result.realized_pnl,
            result.trades,
            result.locked,
        )
        return [
            f"Profile: {profile.name}",
            f"Description: {profile.description}",
            f"Data symbol: {profile.data_symbol}",
            f"Broker symbol: {profile.broker_symbol}",
            f"Data source: {data_source}",
            f"Ending equity: {result.ending_equity:.2f}",
            f"Realized PnL: {result.realized_pnl:.2f}",
            f"Trades: {result.trades}",
            f"Closed trades: {report.closed_trades}",
            f"Win rate: {report.win_rate_pct:.2f}%",
            f"Profit factor: {report.profit_factor:.2f}",
            f"Max drawdown: {report.max_drawdown_pct:.2f}%",
            f"Total costs: {report.total_costs:.2f}",
            f"Trade log: {trades_path}",
            f"Trade analysis: {analysis_path}",
            f"Signal log: {signals_path}",
            f"Signal analysis: {signals_analysis_path}",
            f"Shadow setup log: {shadow_csv_path}" if shadow_csv_path is not None else "Shadow setup log: none",
            f"Shadow setup analysis: {shadow_analysis_path}" if shadow_analysis_path is not None else "Shadow setup analysis: none",
            f"AI summary: {ai_summary_path}",
            f"Next experiments: {next_experiment_path}",
            f"Agent registry: {registry_path}",
            f"Agent catalog: {catalog_path}",
            f"Experiment history: {history_path}",
            f"Run comparison: {comparison_path}",
            f"FTMO pass: {report.passed}",
            f"FTMO reasons: {', '.join(report.reasons) if report.reasons else 'none'}",
            f"Kill-switch triggered: {result.locked}",
        ]
    except Exception as exc:
        LOGGER.exception("profile=%s failed", profile.name)
        return [
            f"Profile: {profile.name}",
            f"Description: {profile.description}",
            f"Data symbol: {profile.data_symbol}",
            f"Broker symbol: {profile.broker_symbol}",
            "Status: failed",
            f"Reason: {exc}",
        ]


def main() -> int:
    configure_logging()
    config = SystemConfig()
    profiles = resolve_profiles(config.instrument.active_profiles)
    report_lines = ["QuantGenerated run complete"]
    for index, profile in enumerate(profiles):
        report_lines.append("")
        report_lines.extend(run_profile(config, profile))
        if index < len(profiles) - 1 and config.market_data.profile_pause_seconds > 0:
            time.sleep(config.market_data.profile_pause_seconds)
    print("\n".join(report_lines))
    return 0
