from __future__ import annotations

import json
from datetime import datetime
from dataclasses import asdict, is_dataclass
from pathlib import Path
import shutil
import tempfile

import duckdb
from quant_system.ai.models import AgentDescriptor, AgentRegistryRecord, ExperimentSnapshot


class ExperimentStore:
    def __init__(self, database_path: str, *, read_only: bool = False) -> None:
        self.database_path = database_path
        self.read_only = read_only
        if not self.read_only:
            self._initialize_schema()

    def _connect(self):
        try:
            return duckdb.connect(self.database_path, read_only=self.read_only)
        except duckdb.IOException:
            if not self.read_only:
                raise
            snapshot_path = self._create_snapshot_copy()
            return duckdb.connect(snapshot_path, read_only=True)

    def _create_snapshot_copy(self) -> str:
        source = Path(self.database_path)
        suffix = source.suffix or ".duckdb"
        with tempfile.NamedTemporaryFile(prefix=f"{source.stem}_snapshot_", suffix=suffix, delete=False) as handle:
            snapshot_path = handle.name
        shutil.copy2(source, snapshot_path)
        wal_path = source.with_suffix(source.suffix + ".wal")
        if wal_path.exists():
            snapshot_wal = Path(snapshot_path + ".wal")
            shutil.copy2(wal_path, snapshot_wal)
        return snapshot_path

    def _initialize_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS experiments (
                    id BIGINT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    profile_name VARCHAR,
                    description VARCHAR,
                    broker_symbol VARCHAR,
                    data_symbol VARCHAR,
                    ending_equity DOUBLE,
                    realized_pnl DOUBLE,
                    trades INTEGER,
                    closed_trades INTEGER,
                    win_rate_pct DOUBLE,
                    profit_factor DOUBLE,
                    max_drawdown_pct DOUBLE,
                    total_costs DOUBLE,
                    ftmo_passed BOOLEAN,
                    ftmo_reasons VARCHAR,
                    optimized_agents_json VARCHAR,
                    local_summary TEXT,
                    ai_summary TEXT,
                    next_experiments_json VARCHAR
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS experiment_artifacts (
                    experiment_id BIGINT,
                    trade_log VARCHAR,
                    trade_analysis VARCHAR,
                    signal_log VARCHAR,
                    signal_analysis VARCHAR,
                    shadow_log VARCHAR,
                    shadow_analysis VARCHAR
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_registry_events (
                    experiment_id BIGINT,
                    profile_name VARCHAR,
                    agent_name VARCHAR,
                    source_type VARCHAR,
                    realized_pnl DOUBLE,
                    closed_trades INTEGER,
                    win_rate_pct DOUBLE,
                    profit_factor DOUBLE,
                    max_drawdown_pct DOUBLE,
                    data_source VARCHAR,
                    verdict VARCHAR,
                    recommended_action TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_registry (
                    profile_name VARCHAR,
                    agent_name VARCHAR,
                    source_type VARCHAR,
                    best_experiment_id BIGINT,
                    last_experiment_id BIGINT,
                    best_realized_pnl DOUBLE,
                    best_profit_factor DOUBLE,
                    best_closed_trades INTEGER,
                    last_verdict VARCHAR,
                    last_recommended_action TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (profile_name, agent_name, source_type)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_catalog (
                    profile_name VARCHAR,
                    agent_name VARCHAR,
                    lifecycle_scope VARCHAR,
                    class_name VARCHAR,
                    code_path TEXT,
                    description TEXT,
                    variant_label VARCHAR,
                    timeframe_label VARCHAR,
                    session_label VARCHAR,
                    status VARCHAR,
                    is_active BOOLEAN,
                    first_seen_at TIMESTAMP,
                    last_seen_at TIMESTAMP,
                    last_version_id BIGINT,
                    last_evaluation_id BIGINT,
                    PRIMARY KEY (profile_name, agent_name, lifecycle_scope)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_versions (
                    id BIGINT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    experiment_id BIGINT,
                    profile_name VARCHAR,
                    agent_name VARCHAR,
                    lifecycle_scope VARCHAR,
                    class_name VARCHAR,
                    code_path TEXT,
                    parameters_json TEXT,
                    data_symbol VARCHAR,
                    broker_symbol VARCHAR
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_evaluations (
                    id BIGINT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    experiment_id BIGINT,
                    profile_name VARCHAR,
                    agent_name VARCHAR,
                    lifecycle_scope VARCHAR,
                    evaluation_source VARCHAR,
                    realized_pnl DOUBLE,
                    closed_trades INTEGER,
                    win_rate_pct DOUBLE,
                    profit_factor DOUBLE,
                    max_drawdown_pct DOUBLE,
                    data_source VARCHAR,
                    verdict VARCHAR,
                    recommended_action TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS symbol_research_runs (
                    id BIGINT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    profile_name VARCHAR,
                    data_symbol VARCHAR,
                    broker_symbol VARCHAR,
                    data_source VARCHAR,
                    recommended_names_json TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS symbol_research_candidates (
                    symbol_research_run_id BIGINT,
                    profile_name VARCHAR,
                    candidate_name VARCHAR,
                    description TEXT,
                    archetype VARCHAR,
                    code_path TEXT,
                    realized_pnl DOUBLE,
                    closed_trades INTEGER,
                    win_rate_pct DOUBLE,
                    profit_factor DOUBLE,
                    max_drawdown_pct DOUBLE,
                    total_costs DOUBLE,
                    train_pnl DOUBLE,
                    validation_pnl DOUBLE,
                    validation_profit_factor DOUBLE,
                    validation_closed_trades INTEGER,
                    test_pnl DOUBLE,
                    test_profit_factor DOUBLE,
                    test_closed_trades INTEGER,
                    expectancy DOUBLE,
                    sharpe_ratio DOUBLE,
                    sortino_ratio DOUBLE,
                    calmar_ratio DOUBLE,
                    avg_win DOUBLE,
                    avg_loss DOUBLE,
                    payoff_ratio DOUBLE,
                    avg_hold_bars DOUBLE,
                    best_trade_share_pct DOUBLE,
                    equity_new_high_share_pct DOUBLE,
                    max_consecutive_losses INTEGER,
                    equity_quality_score DOUBLE,
                    dominant_exit VARCHAR,
                    dominant_exit_share_pct DOUBLE,
                    walk_forward_windows INTEGER,
                    walk_forward_pass_rate_pct DOUBLE,
                    walk_forward_avg_validation_pnl DOUBLE,
                    walk_forward_avg_test_pnl DOUBLE,
                    walk_forward_avg_validation_pf DOUBLE,
                    walk_forward_avg_test_pf DOUBLE,
                    component_count INTEGER,
                    combo_outperformance_score DOUBLE,
                    combo_trade_overlap_pct DOUBLE,
                    best_regime VARCHAR,
                    best_regime_pnl DOUBLE,
                    worst_regime VARCHAR,
                    worst_regime_pnl DOUBLE,
                    dominant_regime_share_pct DOUBLE,
                    regime_stability_score DOUBLE,
                    regime_loss_ratio DOUBLE,
                    regime_trade_count_by_label TEXT,
                    regime_pnl_by_label TEXT,
                    regime_pf_by_label TEXT,
                    regime_win_rate_by_label TEXT,
                    variant_label VARCHAR,
                    timeframe_label VARCHAR,
                    session_label VARCHAR,
                    regime_filter_label VARCHAR,
                    execution_overrides_json TEXT,
                    recommended BOOLEAN
                )
                """
            )
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS train_pnl DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS validation_pnl DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS validation_profit_factor DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS validation_closed_trades INTEGER")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS test_pnl DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS test_profit_factor DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS test_closed_trades INTEGER")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS expectancy DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS sharpe_ratio DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS sortino_ratio DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS calmar_ratio DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS avg_win DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS avg_loss DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS payoff_ratio DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS avg_hold_bars DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS best_trade_share_pct DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS equity_new_high_share_pct DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS max_consecutive_losses INTEGER")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS equity_quality_score DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS dominant_exit VARCHAR")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS dominant_exit_share_pct DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS walk_forward_windows INTEGER")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS walk_forward_pass_rate_pct DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS walk_forward_avg_validation_pnl DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS walk_forward_avg_test_pnl DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS walk_forward_avg_validation_pf DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS walk_forward_avg_test_pf DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS component_count INTEGER")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS combo_outperformance_score DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS combo_trade_overlap_pct DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS best_regime VARCHAR")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS best_regime_pnl DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS worst_regime VARCHAR")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS worst_regime_pnl DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS dominant_regime_share_pct DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS regime_stability_score DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS regime_loss_ratio DOUBLE")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS regime_trade_count_by_label TEXT")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS regime_pnl_by_label TEXT")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS regime_pf_by_label TEXT")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS regime_win_rate_by_label TEXT")
            connection.execute("ALTER TABLE agent_catalog ADD COLUMN IF NOT EXISTS variant_label VARCHAR")
            connection.execute("ALTER TABLE agent_catalog ADD COLUMN IF NOT EXISTS timeframe_label VARCHAR")
            connection.execute("ALTER TABLE agent_catalog ADD COLUMN IF NOT EXISTS session_label VARCHAR")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS variant_label VARCHAR")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS timeframe_label VARCHAR")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS session_label VARCHAR")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS regime_filter_label VARCHAR")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS execution_overrides_json TEXT")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS symbol_execution_sets (
                    id BIGINT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    profile_name VARCHAR,
                    symbol_research_run_id BIGINT,
                    selection_method VARCHAR
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS symbol_execution_set_items (
                    execution_set_id BIGINT,
                    profile_name VARCHAR,
                    candidate_name VARCHAR,
                    code_path TEXT,
                    policy_summary TEXT,
                    regime_filter_label VARCHAR,
                    execution_policy_json TEXT,
                    execution_overrides_json TEXT,
                    selection_rank INTEGER
                )
                """
            )
            connection.execute("ALTER TABLE symbol_execution_set_items ADD COLUMN IF NOT EXISTS policy_summary TEXT")
            connection.execute("ALTER TABLE symbol_execution_set_items ADD COLUMN IF NOT EXISTS regime_filter_label VARCHAR")
            connection.execute("ALTER TABLE symbol_execution_set_items ADD COLUMN IF NOT EXISTS execution_policy_json TEXT")
            connection.execute("ALTER TABLE symbol_execution_set_items ADD COLUMN IF NOT EXISTS execution_overrides_json TEXT")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mt5_fill_events (
                    id BIGINT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    event_timestamp TIMESTAMP,
                    broker_symbol VARCHAR,
                    requested_symbol VARCHAR,
                    side VARCHAR,
                    quantity DOUBLE,
                    requested_price DOUBLE,
                    fill_price DOUBLE,
                    bid DOUBLE,
                    ask DOUBLE,
                    spread_points DOUBLE,
                    slippage_points DOUBLE,
                    slippage_bps DOUBLE,
                    costs DOUBLE,
                    reason VARCHAR,
                    confidence DOUBLE,
                    metadata_json TEXT,
                    magic_number BIGINT,
                    comment VARCHAR,
                    position_ticket BIGINT
                )
                """
            )

    def _serialize(self, value) -> str:
        if is_dataclass(value):
            return json.dumps(asdict(value))
        if isinstance(value, Path):
            return str(value)
        return json.dumps(value)

    def _row_to_snapshot(self, row) -> ExperimentSnapshot:
        return ExperimentSnapshot(
            experiment_id=int(row[0]),
            created_at=str(row[1]),
            profile_name=str(row[2]),
            ending_equity=float(row[3] or 0.0),
            realized_pnl=float(row[4] or 0.0),
            closed_trades=int(row[5] or 0),
            win_rate_pct=float(row[6] or 0.0),
            profit_factor=float(row[7] or 0.0),
            max_drawdown_pct=float(row[8] or 0.0),
            ftmo_passed=bool(row[9]),
            local_summary=str(row[10] or ""),
            ai_summary=str(row[11] or ""),
        )

    def record_experiment(
        self,
        *,
        profile,
        result,
        report,
        optimized_agents,
        artifacts,
        local_summary: str,
        ai_summary: str | None,
        next_experiments: list[str],
    ) -> int:
        with self._connect() as connection:
            next_id = connection.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM experiments").fetchone()[0]
            experiment_id = connection.execute(
                """
                INSERT INTO experiments (
                    id,
                    profile_name,
                    description,
                    broker_symbol,
                    data_symbol,
                    ending_equity,
                    realized_pnl,
                    trades,
                    closed_trades,
                    win_rate_pct,
                    profit_factor,
                    max_drawdown_pct,
                    total_costs,
                    ftmo_passed,
                    ftmo_reasons,
                    optimized_agents_json,
                    local_summary,
                    ai_summary,
                    next_experiments_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                [
                    next_id,
                    profile.name,
                    profile.description,
                    profile.broker_symbol,
                    profile.data_symbol,
                    result.ending_equity,
                    result.realized_pnl,
                    result.trades,
                    report.closed_trades,
                    report.win_rate_pct,
                    report.profit_factor,
                    report.max_drawdown_pct,
                    report.total_costs,
                    report.passed,
                    json.dumps(report.reasons),
                    self._serialize(optimized_agents),
                    local_summary,
                    ai_summary or "",
                    json.dumps(next_experiments),
                ],
            ).fetchone()[0]

            connection.execute(
                """
                INSERT INTO experiment_artifacts (
                    experiment_id,
                    trade_log,
                    trade_analysis,
                    signal_log,
                    signal_analysis,
                    shadow_log,
                    shadow_analysis
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    experiment_id,
                    str(artifacts.trade_log),
                    str(artifacts.trade_analysis),
                    str(artifacts.signal_log),
                    str(artifacts.signal_analysis),
                    str(artifacts.shadow_log) if artifacts.shadow_log is not None else "",
                    str(artifacts.shadow_analysis) if artifacts.shadow_analysis is not None else "",
                ],
            )
        return int(experiment_id)

    def record_agent_registry(self, experiment_id: int, records: list[AgentRegistryRecord]) -> None:
        if not records:
            return
        with self._connect() as connection:
            for record in records:
                connection.execute(
                    """
                    INSERT INTO agent_registry_events (
                        experiment_id,
                        profile_name,
                        agent_name,
                        source_type,
                        realized_pnl,
                        closed_trades,
                        win_rate_pct,
                        profit_factor,
                        max_drawdown_pct,
                        data_source,
                        verdict,
                        recommended_action
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        experiment_id,
                        record.profile_name,
                        record.agent_name,
                        record.source_type,
                        record.realized_pnl,
                        record.closed_trades,
                        record.win_rate_pct,
                        record.profit_factor,
                        record.max_drawdown_pct,
                        record.data_source,
                        record.verdict,
                        record.recommended_action,
                    ],
                )

                existing = connection.execute(
                    """
                    SELECT best_experiment_id, best_realized_pnl, best_profit_factor, best_closed_trades
                    FROM agent_registry
                    WHERE profile_name = ? AND agent_name = ? AND source_type = ?
                    """,
                    [record.profile_name, record.agent_name, record.source_type],
                ).fetchone()

                best_experiment_id = experiment_id
                best_realized_pnl = record.realized_pnl
                best_profit_factor = record.profit_factor
                best_closed_trades = record.closed_trades
                if existing is not None:
                    previous_best = (
                        float(existing[1] or 0.0),
                        float(existing[2] or 0.0),
                        int(existing[3] or 0),
                    )
                    candidate = (record.realized_pnl, record.profit_factor, record.closed_trades)
                    if previous_best >= candidate:
                        best_experiment_id = int(existing[0] or experiment_id)
                        best_realized_pnl = previous_best[0]
                        best_profit_factor = previous_best[1]
                        best_closed_trades = previous_best[2]

                connection.execute(
                    """
                    INSERT OR REPLACE INTO agent_registry (
                        profile_name,
                        agent_name,
                        source_type,
                        best_experiment_id,
                        last_experiment_id,
                        best_realized_pnl,
                        best_profit_factor,
                        best_closed_trades,
                        last_verdict,
                        last_recommended_action,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    [
                        record.profile_name,
                        record.agent_name,
                        record.source_type,
                        best_experiment_id,
                        experiment_id,
                        best_realized_pnl,
                        best_profit_factor,
                        best_closed_trades,
                        record.verdict,
                        record.recommended_action,
                    ],
                )

    def _catalog_status(self, descriptor: AgentDescriptor, record: AgentRegistryRecord | None) -> str:
        if record is None:
            return "draft" if descriptor.lifecycle_scope == "shadow" else "testing"
        if record.verdict == "promising":
            return "active" if descriptor.lifecycle_scope == "active" else "testing"
        if record.verdict == "needs_retest":
            return "testing"
        if record.verdict == "rejected":
            return "rejected"
        if record.verdict == "idle":
            return "draft"
        return "testing"

    def record_agent_lifecycle(
        self,
        *,
        experiment_id: int,
        profile,
        descriptors: list[AgentDescriptor],
        registry_records: list[AgentRegistryRecord],
        optimized_agents,
    ) -> None:
        record_map: dict[tuple[str, str], AgentRegistryRecord] = {}
        for record in registry_records:
            lifecycle_scope = "active" if record.source_type == "realized" else "shadow"
            record_map[(record.agent_name, lifecycle_scope)] = record

        serialized_params = self._serialize(optimized_agents)
        now = datetime.utcnow()

        with self._connect() as connection:
            next_version_id = int(connection.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM agent_versions").fetchone()[0])
            next_evaluation_id = int(connection.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM agent_evaluations").fetchone()[0])

            for index, descriptor in enumerate(descriptors):
                record = record_map.get((descriptor.agent_name, descriptor.lifecycle_scope))
                version_id = next_version_id + index
                evaluation_id = next_evaluation_id + index

                connection.execute(
                    """
                    INSERT INTO agent_versions (
                        id,
                        experiment_id,
                        profile_name,
                        agent_name,
                        lifecycle_scope,
                        class_name,
                        code_path,
                        parameters_json,
                        data_symbol,
                        broker_symbol
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        version_id,
                        experiment_id,
                        descriptor.profile_name,
                        descriptor.agent_name,
                        descriptor.lifecycle_scope,
                        descriptor.class_name,
                        descriptor.code_path,
                        serialized_params,
                        profile.data_symbol,
                        profile.broker_symbol,
                    ],
                )

                connection.execute(
                    """
                    INSERT INTO agent_evaluations (
                        id,
                        experiment_id,
                        profile_name,
                        agent_name,
                        lifecycle_scope,
                        evaluation_source,
                        realized_pnl,
                        closed_trades,
                        win_rate_pct,
                        profit_factor,
                        max_drawdown_pct,
                        data_source,
                        verdict,
                        recommended_action
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        evaluation_id,
                        experiment_id,
                        descriptor.profile_name,
                        descriptor.agent_name,
                        descriptor.lifecycle_scope,
                        record.source_type if record is not None else "none",
                        record.realized_pnl if record is not None else 0.0,
                        record.closed_trades if record is not None else 0,
                        record.win_rate_pct if record is not None else 0.0,
                        record.profit_factor if record is not None else 0.0,
                        record.max_drawdown_pct if record is not None else 0.0,
                        record.data_source if record is not None else "unknown",
                        record.verdict if record is not None else "idle",
                        record.recommended_action if record is not None else "No evaluation yet; run research first.",
                    ],
                )

                catalog_row = connection.execute(
                    """
                    SELECT first_seen_at
                    FROM agent_catalog
                    WHERE profile_name = ? AND agent_name = ? AND lifecycle_scope = ?
                    """,
                    [descriptor.profile_name, descriptor.agent_name, descriptor.lifecycle_scope],
                ).fetchone()
                first_seen_at = catalog_row[0] if catalog_row is not None else now

                connection.execute(
                    """
                    INSERT OR REPLACE INTO agent_catalog (
                        profile_name,
                        agent_name,
                        lifecycle_scope,
                        class_name,
                        code_path,
                        description,
                        variant_label,
                        timeframe_label,
                        session_label,
                        status,
                        is_active,
                        first_seen_at,
                        last_seen_at,
                        last_version_id,
                        last_evaluation_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        descriptor.profile_name,
                        descriptor.agent_name,
                        descriptor.lifecycle_scope,
                        descriptor.class_name,
                        descriptor.code_path,
                        descriptor.description,
                        descriptor.variant_label,
                        descriptor.timeframe_label,
                        descriptor.session_label,
                        self._catalog_status(descriptor, record),
                        descriptor.is_active,
                        first_seen_at,
                        now,
                        version_id,
                        evaluation_id,
                    ],
                )

    def list_agent_registry(self, profile_name: str) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    profile_name,
                    agent_name,
                    source_type,
                    best_experiment_id,
                    last_experiment_id,
                    best_realized_pnl,
                    best_profit_factor,
                    best_closed_trades,
                    last_verdict,
                    last_recommended_action
                FROM agent_registry
                WHERE profile_name = ?
                ORDER BY best_realized_pnl DESC, best_profit_factor DESC, best_closed_trades DESC
                """,
                [profile_name],
            ).fetchall()
        return [
            {
                "profile_name": row[0],
                "agent_name": row[1],
                "source_type": row[2],
                "best_experiment_id": row[3],
                "last_experiment_id": row[4],
                "best_realized_pnl": float(row[5] or 0.0),
                "best_profit_factor": float(row[6] or 0.0),
                "best_closed_trades": int(row[7] or 0),
                "last_verdict": row[8],
                "last_recommended_action": row[9],
            }
            for row in rows
        ]

    def list_agent_catalog(self, profile_name: str) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    profile_name,
                    agent_name,
                    lifecycle_scope,
                    class_name,
                    code_path,
                    description,
                    variant_label,
                    timeframe_label,
                    session_label,
                    status,
                    is_active,
                    first_seen_at,
                    last_seen_at,
                    last_version_id,
                    last_evaluation_id
                FROM agent_catalog
                WHERE profile_name = ?
                ORDER BY is_active DESC, status ASC, agent_name ASC
                """,
                [profile_name],
            ).fetchall()
        return [
            {
                "profile_name": row[0],
                "agent_name": row[1],
                "lifecycle_scope": row[2],
                "class_name": row[3],
                "code_path": row[4],
                "description": row[5],
                "variant_label": row[6] or "",
                "timeframe_label": row[7] or "",
                "session_label": row[8] or "",
                "status": row[9],
                "is_active": bool(row[10]),
                "first_seen_at": row[11],
                "last_seen_at": row[12],
                "last_version_id": row[13],
                "last_evaluation_id": row[14],
            }
            for row in rows
        ]

    def list_agent_catalog_profiles(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT profile_name
                FROM agent_catalog
                ORDER BY profile_name ASC
                """
            ).fetchall()
        return [str(row[0]) for row in rows]

    def list_active_catalog_agents(self, profile_name: str) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    profile_name,
                    agent_name,
                    lifecycle_scope,
                    class_name,
                    code_path,
                    description,
                    status,
                    is_active,
                    last_version_id,
                    last_evaluation_id
                FROM agent_catalog
                WHERE profile_name = ? AND is_active = TRUE
                ORDER BY agent_name ASC
                """,
                [profile_name],
            ).fetchall()
        return [
            {
                "profile_name": row[0],
                "agent_name": row[1],
                "lifecycle_scope": row[2],
                "class_name": row[3],
                "code_path": row[4],
                "description": row[5],
                "status": row[6],
                "is_active": bool(row[7]),
                "last_version_id": row[8],
                "last_evaluation_id": row[9],
            }
            for row in rows
        ]

    def get_latest_symbol_research_run(self, profile_name: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, profile_name, data_symbol, broker_symbol, data_source, recommended_names_json, created_at
                FROM symbol_research_runs
                WHERE profile_name = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                [profile_name],
            ).fetchone()
        if row is None:
            return None
        return {
            "id": int(row[0]),
            "profile_name": row[1],
            "data_symbol": row[2],
            "broker_symbol": row[3],
            "data_source": row[4],
            "recommended_names": json.loads(row[5] or "[]"),
            "created_at": row[6],
        }

    def list_symbol_research_profiles(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT profile_name
                FROM symbol_research_runs
                ORDER BY profile_name ASC
                """
            ).fetchall()
        return [str(row[0]) for row in rows]

    def list_symbol_research_runs(self, profile_name: str | None = None) -> list[dict[str, object]]:
        with self._connect() as connection:
            if profile_name:
                rows = connection.execute(
                    """
                    SELECT id, profile_name, data_symbol, broker_symbol, data_source, recommended_names_json, created_at
                    FROM symbol_research_runs
                    WHERE profile_name = ?
                    ORDER BY id ASC
                    """,
                    [profile_name],
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT id, profile_name, data_symbol, broker_symbol, data_source, recommended_names_json, created_at
                    FROM symbol_research_runs
                    ORDER BY id ASC
                    """
                ).fetchall()
        return [
            {
                "id": int(row[0]),
                "profile_name": row[1],
                "data_symbol": row[2],
                "broker_symbol": row[3],
                "data_source": row[4],
                "recommended_names": json.loads(row[5] or "[]"),
                "created_at": row[6],
            }
            for row in rows
        ]

    def get_symbol_execution_set_for_run(self, profile_name: str, symbol_research_run_id: int) -> dict[str, object] | None:
        with self._connect() as connection:
            header = connection.execute(
                """
                SELECT id, profile_name, symbol_research_run_id, selection_method, created_at
                FROM symbol_execution_sets
                WHERE profile_name = ? AND symbol_research_run_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                [profile_name, symbol_research_run_id],
            ).fetchone()
            if header is None:
                return None
            rows = connection.execute(
                """
                SELECT
                    candidate_name,
                    code_path,
                    policy_summary,
                    regime_filter_label,
                    execution_policy_json,
                    execution_overrides_json,
                    selection_rank
                FROM symbol_execution_set_items
                WHERE execution_set_id = ?
                ORDER BY selection_rank ASC, candidate_name ASC
                """,
                [header[0]],
            ).fetchall()
        return {
            "id": int(header[0]),
            "profile_name": header[1],
            "symbol_research_run_id": int(header[2]),
            "selection_method": header[3],
            "created_at": header[4],
            "items": [
                {
                    "candidate_name": row[0],
                    "code_path": row[1],
                    "policy_summary": row[2] or "",
                    "regime_filter_label": row[3] or "",
                    **json.loads(row[4] or "{}"),
                    "execution_overrides": json.loads(row[5] or "{}"),
                    "selection_rank": int(row[6] or 0),
                }
                for row in rows
            ],
        }

    def list_symbol_research_candidates_for_run(self, run_id: int) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    candidate_name,
                    description,
                    archetype,
                    code_path,
                    realized_pnl,
                    closed_trades,
                    win_rate_pct,
                    profit_factor,
                    max_drawdown_pct,
                    total_costs,
                    train_pnl,
                    validation_pnl,
                    validation_profit_factor,
                    validation_closed_trades,
                    test_pnl,
                    test_profit_factor,
                    test_closed_trades,
                    expectancy,
                    sharpe_ratio,
                    sortino_ratio,
                    calmar_ratio,
                    avg_win,
                    avg_loss,
                    payoff_ratio,
                    avg_hold_bars,
                    best_trade_share_pct,
                    equity_new_high_share_pct,
                    max_consecutive_losses,
                    equity_quality_score,
                    dominant_exit,
                    dominant_exit_share_pct,
                    walk_forward_windows,
                    walk_forward_pass_rate_pct,
                    walk_forward_avg_validation_pnl,
                    walk_forward_avg_test_pnl,
                    walk_forward_avg_validation_pf,
                    walk_forward_avg_test_pf,
                    component_count,
                    combo_outperformance_score,
                    combo_trade_overlap_pct,
                    best_regime,
                    best_regime_pnl,
                    worst_regime,
                    worst_regime_pnl,
                    dominant_regime_share_pct,
                    regime_stability_score,
                    regime_loss_ratio,
                    regime_trade_count_by_label,
                    regime_pnl_by_label,
                    regime_pf_by_label,
                    regime_win_rate_by_label,
                    variant_label,
                    timeframe_label,
                    session_label,
                    regime_filter_label,
                    execution_overrides_json,
                    recommended,
                    profile_name
                FROM symbol_research_candidates
                WHERE symbol_research_run_id = ?
                ORDER BY recommended DESC, realized_pnl DESC, profit_factor DESC, closed_trades DESC
                """,
                [run_id],
            ).fetchall()
        return [
            {
                "candidate_name": row[0],
                "description": row[1],
                "archetype": row[2],
                "code_path": row[3],
                "realized_pnl": float(row[4] or 0.0),
                "closed_trades": int(row[5] or 0),
                "win_rate_pct": float(row[6] or 0.0),
                "profit_factor": float(row[7] or 0.0),
                "max_drawdown_pct": float(row[8] or 0.0),
                "total_costs": float(row[9] or 0.0),
                "train_pnl": float(row[10] or 0.0),
                "validation_pnl": float(row[11] or 0.0),
                "validation_profit_factor": float(row[12] or 0.0),
                "validation_closed_trades": int(row[13] or 0),
                "test_pnl": float(row[14] or 0.0),
                "test_profit_factor": float(row[15] or 0.0),
                "test_closed_trades": int(row[16] or 0),
                "expectancy": float(row[17] or 0.0),
                "sharpe_ratio": float(row[18] or 0.0),
                "sortino_ratio": float(row[19] or 0.0),
                "calmar_ratio": float(row[20] or 0.0),
                "avg_win": float(row[21] or 0.0),
                "avg_loss": float(row[22] or 0.0),
                "payoff_ratio": float(row[23] or 0.0),
                "avg_hold_bars": float(row[24] or 0.0),
                "best_trade_share_pct": float(row[25] or 0.0),
                "equity_new_high_share_pct": float(row[26] or 0.0),
                "max_consecutive_losses": int(row[27] or 0),
                "equity_quality_score": float(row[28] or 0.0),
                "dominant_exit": row[29] or "",
                "dominant_exit_share_pct": float(row[30] or 0.0),
                "walk_forward_windows": int(row[31] or 0),
                "walk_forward_pass_rate_pct": float(row[32] or 0.0),
                "walk_forward_avg_validation_pnl": float(row[33] or 0.0),
                "walk_forward_avg_test_pnl": float(row[34] or 0.0),
                "walk_forward_avg_validation_pf": float(row[35] or 0.0),
                "walk_forward_avg_test_pf": float(row[36] or 0.0),
                "component_count": int(row[37] or 1),
                "combo_outperformance_score": float(row[38] or 0.0),
                "combo_trade_overlap_pct": float(row[39] or 0.0),
                "best_regime": row[40] or "",
                "best_regime_pnl": float(row[41] or 0.0),
                "worst_regime": row[42] or "",
                "worst_regime_pnl": float(row[43] or 0.0),
                "dominant_regime_share_pct": float(row[44] or 0.0),
                "regime_stability_score": float(row[45] or 0.0),
                "regime_loss_ratio": float(row[46] or 0.0),
                "regime_trade_count_by_label": row[47] or "{}",
                "regime_pnl_by_label": row[48] or "{}",
                "regime_pf_by_label": row[49] or "{}",
                "regime_win_rate_by_label": row[50] or "{}",
                "variant_label": row[51] or "",
                "timeframe_label": row[52] or "",
                "session_label": row[53] or "",
                "regime_filter_label": row[54] or "",
                "execution_overrides": json.loads(row[55] or "{}"),
                "recommended": bool(row[56]),
                "profile_name": row[57],
            }
            for row in rows
        ]

    def list_latest_symbol_research_candidates(self, profile_name: str) -> list[dict[str, object]]:
        latest = self.get_latest_symbol_research_run(profile_name)
        if latest is None:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    candidate_name,
                    description,
                    archetype,
                    code_path,
                    realized_pnl,
                    closed_trades,
                    win_rate_pct,
                    profit_factor,
                    max_drawdown_pct,
                    total_costs,
                    train_pnl,
                    validation_pnl,
                    validation_profit_factor,
                    validation_closed_trades,
                    test_pnl,
                    test_profit_factor,
                    test_closed_trades,
                    expectancy,
                    sharpe_ratio,
                    sortino_ratio,
                    calmar_ratio,
                    avg_win,
                    avg_loss,
                    payoff_ratio,
                    avg_hold_bars,
                    best_trade_share_pct,
                    equity_new_high_share_pct,
                    max_consecutive_losses,
                    equity_quality_score,
                    dominant_exit,
                    dominant_exit_share_pct,
                    walk_forward_windows,
                    walk_forward_pass_rate_pct,
                    walk_forward_avg_validation_pnl,
                    walk_forward_avg_test_pnl,
                    walk_forward_avg_validation_pf,
                    walk_forward_avg_test_pf,
                    component_count,
                    combo_outperformance_score,
                    combo_trade_overlap_pct,
                    best_regime,
                    best_regime_pnl,
                    worst_regime,
                    worst_regime_pnl,
                    dominant_regime_share_pct,
                    regime_stability_score,
                    regime_loss_ratio,
                    regime_trade_count_by_label,
                    regime_pnl_by_label,
                    regime_pf_by_label,
                    regime_win_rate_by_label,
                    variant_label,
                    timeframe_label,
                    session_label,
                    regime_filter_label,
                    execution_overrides_json,
                    recommended
                FROM symbol_research_candidates
                WHERE symbol_research_run_id = ?
                ORDER BY recommended DESC, realized_pnl DESC, profit_factor DESC, closed_trades DESC
                """,
                [latest["id"]],
            ).fetchall()
        return [
            {
                "candidate_name": row[0],
                "description": row[1],
                "archetype": row[2],
                "code_path": row[3],
                "realized_pnl": float(row[4] or 0.0),
                "closed_trades": int(row[5] or 0),
                "win_rate_pct": float(row[6] or 0.0),
                "profit_factor": float(row[7] or 0.0),
                "max_drawdown_pct": float(row[8] or 0.0),
                "total_costs": float(row[9] or 0.0),
                "train_pnl": float(row[10] or 0.0),
                "validation_pnl": float(row[11] or 0.0),
                "validation_profit_factor": float(row[12] or 0.0),
                "validation_closed_trades": int(row[13] or 0),
                "test_pnl": float(row[14] or 0.0),
                "test_profit_factor": float(row[15] or 0.0),
                "test_closed_trades": int(row[16] or 0),
                "expectancy": float(row[17] or 0.0),
                "sharpe_ratio": float(row[18] or 0.0),
                "sortino_ratio": float(row[19] or 0.0),
                "calmar_ratio": float(row[20] or 0.0),
                "avg_win": float(row[21] or 0.0),
                "avg_loss": float(row[22] or 0.0),
                "payoff_ratio": float(row[23] or 0.0),
                "avg_hold_bars": float(row[24] or 0.0),
                "best_trade_share_pct": float(row[25] or 0.0),
                "equity_new_high_share_pct": float(row[26] or 0.0),
                "max_consecutive_losses": int(row[27] or 0),
                "equity_quality_score": float(row[28] or 0.0),
                "dominant_exit": row[29] or "",
                "dominant_exit_share_pct": float(row[30] or 0.0),
                "walk_forward_windows": int(row[31] or 0),
                "walk_forward_pass_rate_pct": float(row[32] or 0.0),
                "walk_forward_avg_validation_pnl": float(row[33] or 0.0),
                "walk_forward_avg_test_pnl": float(row[34] or 0.0),
                "walk_forward_avg_validation_pf": float(row[35] or 0.0),
                "walk_forward_avg_test_pf": float(row[36] or 0.0),
                "component_count": int(row[37] or 1),
                "combo_outperformance_score": float(row[38] or 0.0),
                "combo_trade_overlap_pct": float(row[39] or 0.0),
                "best_regime": row[40] or "",
                "best_regime_pnl": float(row[41] or 0.0),
                "worst_regime": row[42] or "",
                "worst_regime_pnl": float(row[43] or 0.0),
                "dominant_regime_share_pct": float(row[44] or 0.0),
                "regime_stability_score": float(row[45] or 0.0),
                "regime_loss_ratio": float(row[46] or 0.0),
                "regime_trade_count_by_label": row[47] or "{}",
                "regime_pnl_by_label": row[48] or "{}",
                "regime_pf_by_label": row[49] or "{}",
                "regime_win_rate_by_label": row[50] or "{}",
                "variant_label": row[51] or "",
                "timeframe_label": row[52] or "",
                "session_label": row[53] or "",
                "regime_filter_label": row[54] or "",
                "execution_overrides": json.loads(row[55] or "{}"),
                "recommended": bool(row[56]),
            }
            for row in rows
        ]

    def record_symbol_execution_set(
        self,
        *,
        profile_name: str,
        symbol_research_run_id: int,
        selected_candidates: list[dict[str, object]],
        selection_method: str = "heuristic_top_non_overlapping",
    ) -> int:
        with self._connect() as connection:
            execution_set_id = int(
                connection.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM symbol_execution_sets").fetchone()[0]
            )
            connection.execute(
                """
                INSERT INTO symbol_execution_sets (
                    id,
                    profile_name,
                    symbol_research_run_id,
                    selection_method
                )
                VALUES (?, ?, ?, ?)
                """,
                [execution_set_id, profile_name, symbol_research_run_id, selection_method],
            )
            for index, row in enumerate(selected_candidates, start=1):
                connection.execute(
                    """
                    INSERT INTO symbol_execution_set_items (
                        execution_set_id,
                        profile_name,
                        candidate_name,
                        code_path,
                        policy_summary,
                        regime_filter_label,
                        execution_policy_json,
                        execution_overrides_json,
                        selection_rank
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        execution_set_id,
                        profile_name,
                        str(row["candidate_name"]),
                        str(row["code_path"]),
                        str(row.get("policy_summary", "")),
                        str(row.get("regime_filter_label", "")),
                        json.dumps(
                            {
                                "allowed_regimes": list(row.get("allowed_regimes", ()) or ()),
                                "blocked_regimes": list(row.get("blocked_regimes", ()) or ()),
                                "min_vol_percentile": float(row.get("min_vol_percentile", 0.0) or 0.0),
                                "max_vol_percentile": float(row.get("max_vol_percentile", 1.0) or 1.0),
                                "base_allocation_weight": float(row.get("base_allocation_weight", 1.0) or 1.0),
                                "max_risk_multiplier": float(row.get("max_risk_multiplier", 1.0) or 1.0),
                                "min_risk_multiplier": float(row.get("min_risk_multiplier", 0.0) or 0.0),
                            }
                        ),
                        json.dumps(row.get("execution_overrides", {})),
                        index,
                    ],
                )
        return execution_set_id

    def record_mt5_fill_event(
        self,
        *,
        event_timestamp,
        broker_symbol: str,
        requested_symbol: str,
        side: str,
        quantity: float,
        requested_price: float,
        fill_price: float,
        bid: float,
        ask: float,
        spread_points: float,
        slippage_points: float,
        slippage_bps: float,
        costs: float,
        reason: str,
        confidence: float,
        metadata: dict[str, object] | None = None,
        magic_number: int | None = None,
        comment: str | None = None,
        position_ticket: int | None = None,
    ) -> int:
        with self._connect() as connection:
            fill_id = int(connection.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM mt5_fill_events").fetchone()[0])
            connection.execute(
                """
                INSERT INTO mt5_fill_events (
                    id,
                    event_timestamp,
                    broker_symbol,
                    requested_symbol,
                    side,
                    quantity,
                    requested_price,
                    fill_price,
                    bid,
                    ask,
                    spread_points,
                    slippage_points,
                    slippage_bps,
                    costs,
                    reason,
                    confidence,
                    metadata_json,
                    magic_number,
                    comment,
                    position_ticket
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    fill_id,
                    event_timestamp,
                    broker_symbol,
                    requested_symbol,
                    side,
                    quantity,
                    requested_price,
                    fill_price,
                    bid,
                    ask,
                    spread_points,
                    slippage_points,
                    slippage_bps,
                    costs,
                    reason,
                    confidence,
                    self._serialize(metadata or {}),
                    magic_number,
                    comment,
                    position_ticket,
                ],
            )
        return fill_id

    def load_mt5_fill_calibration(self, broker_symbol: str, lookback_rows: int = 250) -> dict[str, float] | None:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT spread_points, slippage_bps
                FROM mt5_fill_events
                WHERE broker_symbol = ?
                ORDER BY event_timestamp DESC, id DESC
                LIMIT ?
                """,
                [broker_symbol, lookback_rows],
            ).fetchall()
        if len(rows) < 5:
            return None
        spreads = sorted(float(row[0] or 0.0) for row in rows)
        slippages = sorted(float(row[1] or 0.0) for row in rows)
        def _quantile(values: list[float], q: float) -> float:
            index = int((len(values) - 1) * q)
            return values[index]
        return {
            "count": float(len(rows)),
            "median_spread_points": _quantile(spreads, 0.50),
            "p75_spread_points": _quantile(spreads, 0.75),
            "median_slippage_bps": _quantile(slippages, 0.50),
            "p75_slippage_bps": _quantile(slippages, 0.75),
            "p90_slippage_bps": _quantile(slippages, 0.90),
        }

    def list_mt5_fill_symbols(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT broker_symbol
                FROM mt5_fill_events
                WHERE broker_symbol IS NOT NULL AND broker_symbol <> ''
                ORDER BY broker_symbol ASC
                """
            ).fetchall()
        return [str(row[0]) for row in rows]

    def load_mt5_fill_summary(self, broker_symbol: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS fill_count,
                    MIN(event_timestamp) AS first_fill_at,
                    MAX(event_timestamp) AS last_fill_at,
                    AVG(spread_points) AS avg_spread_points,
                    AVG(slippage_bps) AS avg_slippage_bps
                FROM mt5_fill_events
                WHERE broker_symbol = ?
                """
                ,
                [broker_symbol],
            ).fetchone()
        if row is None or int(row[0] or 0) <= 0:
            return None
        return {
            "broker_symbol": broker_symbol,
            "fill_count": int(row[0] or 0),
            "first_fill_at": row[1],
            "last_fill_at": row[2],
            "avg_spread_points": float(row[3] or 0.0),
            "avg_slippage_bps": float(row[4] or 0.0),
        }

    def list_mt5_fill_events(self, broker_symbol: str | None = None) -> list[dict[str, object]]:
        with self._connect() as connection:
            if broker_symbol:
                rows = connection.execute(
                    """
                    SELECT
                        id,
                        event_timestamp,
                        broker_symbol,
                        requested_symbol,
                        side,
                        quantity,
                        requested_price,
                        fill_price,
                        bid,
                        ask,
                        spread_points,
                        slippage_points,
                        slippage_bps,
                        costs,
                        reason,
                        confidence,
                        metadata_json,
                        magic_number,
                        comment,
                        position_ticket
                    FROM mt5_fill_events
                    WHERE broker_symbol = ?
                    ORDER BY event_timestamp ASC, id ASC
                    """,
                    [broker_symbol],
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT
                        id,
                        event_timestamp,
                        broker_symbol,
                        requested_symbol,
                        side,
                        quantity,
                        requested_price,
                        fill_price,
                        bid,
                        ask,
                        spread_points,
                        slippage_points,
                        slippage_bps,
                        costs,
                        reason,
                        confidence,
                        metadata_json,
                        magic_number,
                        comment,
                        position_ticket
                    FROM mt5_fill_events
                    ORDER BY event_timestamp ASC, id ASC
                    """
                ).fetchall()
        return [
            {
                "id": int(row[0]),
                "event_timestamp": row[1],
                "broker_symbol": row[2] or "",
                "requested_symbol": row[3] or "",
                "side": row[4] or "",
                "quantity": float(row[5] or 0.0),
                "requested_price": float(row[6] or 0.0),
                "fill_price": float(row[7] or 0.0),
                "bid": float(row[8] or 0.0),
                "ask": float(row[9] or 0.0),
                "spread_points": float(row[10] or 0.0),
                "slippage_points": float(row[11] or 0.0),
                "slippage_bps": float(row[12] or 0.0),
                "costs": float(row[13] or 0.0),
                "reason": row[14] or "",
                "confidence": float(row[15] or 0.0),
                "metadata": json.loads(row[16] or "{}"),
                "magic_number": int(row[17] or 0),
                "comment": row[18] or "",
                "position_ticket": int(row[19] or 0),
            }
            for row in rows
        ]

    def get_latest_symbol_execution_set(self, profile_name: str) -> dict[str, object] | None:
        with self._connect() as connection:
            header = connection.execute(
                """
                SELECT id, profile_name, symbol_research_run_id, selection_method, created_at
                FROM symbol_execution_sets
                WHERE profile_name = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                [profile_name],
            ).fetchone()
            if header is None:
                return None
            rows = connection.execute(
                """
                SELECT candidate_name, code_path, policy_summary, regime_filter_label, execution_policy_json, execution_overrides_json, selection_rank
                FROM symbol_execution_set_items
                WHERE execution_set_id = ?
                ORDER BY selection_rank ASC
                """,
                [header[0]],
            ).fetchall()
        return {
            "id": int(header[0]),
            "profile_name": header[1],
            "symbol_research_run_id": int(header[2]),
            "selection_method": header[3],
            "created_at": header[4],
            "items": [
                {
                    "candidate_name": row[0],
                    "code_path": row[1],
                    "policy_summary": row[2] or "",
                    "regime_filter_label": row[3] or "",
                    **json.loads(row[4] or "{}"),
                    "execution_overrides": json.loads(row[5] or "{}"),
                    "selection_rank": int(row[6] or 0),
                }
                for row in rows
            ],
        }

    def list_symbol_execution_set_profiles(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT profile_name
                FROM symbol_execution_sets
                ORDER BY profile_name ASC
                """
            ).fetchall()
        return [str(row[0]) for row in rows]

    def record_symbol_research_run(
        self,
        *,
        profile_name: str,
        data_symbol: str,
        broker_symbol: str,
        data_source: str,
        candidates,
        recommended_names: list[str],
    ) -> int:
        with self._connect() as connection:
            run_id = int(connection.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM symbol_research_runs").fetchone()[0])
            connection.execute(
                """
                INSERT INTO symbol_research_runs (
                    id,
                    profile_name,
                    data_symbol,
                    broker_symbol,
                    data_source,
                    recommended_names_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [run_id, profile_name, data_symbol, broker_symbol, data_source, json.dumps(recommended_names)],
            )
            for candidate in candidates:
                connection.execute(
                    """
                    INSERT INTO symbol_research_candidates (
                        symbol_research_run_id,
                        profile_name,
                        candidate_name,
                        description,
                        archetype,
                        code_path,
                        realized_pnl,
                        closed_trades,
                        win_rate_pct,
                        profit_factor,
                        max_drawdown_pct,
                        total_costs,
                        train_pnl,
                        validation_pnl,
                        validation_profit_factor,
                        validation_closed_trades,
                        test_pnl,
                        test_profit_factor,
                        test_closed_trades,
                        expectancy,
                        sharpe_ratio,
                        sortino_ratio,
                        calmar_ratio,
                        avg_win,
                        avg_loss,
                        payoff_ratio,
                        avg_hold_bars,
                        best_trade_share_pct,
                        equity_new_high_share_pct,
                        max_consecutive_losses,
                        equity_quality_score,
                        dominant_exit,
                        dominant_exit_share_pct,
                        walk_forward_windows,
                        walk_forward_pass_rate_pct,
                        walk_forward_avg_validation_pnl,
                        walk_forward_avg_test_pnl,
                        walk_forward_avg_validation_pf,
                        walk_forward_avg_test_pf,
                        component_count,
                        combo_outperformance_score,
                        combo_trade_overlap_pct,
                        best_regime,
                        best_regime_pnl,
                        worst_regime,
                        worst_regime_pnl,
                        dominant_regime_share_pct,
                        regime_stability_score,
                        regime_loss_ratio,
                        regime_trade_count_by_label,
                        regime_pnl_by_label,
                        regime_pf_by_label,
                        regime_win_rate_by_label,
                        variant_label,
                        timeframe_label,
                        session_label,
                        regime_filter_label,
                        execution_overrides_json,
                        recommended
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    [
                        run_id,
                        profile_name,
                        candidate.name,
                        candidate.description,
                        candidate.archetype,
                        candidate.code_path,
                        candidate.realized_pnl,
                        candidate.closed_trades,
                        candidate.win_rate_pct,
                        candidate.profit_factor,
                        candidate.max_drawdown_pct,
                        candidate.total_costs,
                        candidate.train_pnl,
                        candidate.validation_pnl,
                        candidate.validation_profit_factor,
                        candidate.validation_closed_trades,
                        candidate.test_pnl,
                        candidate.test_profit_factor,
                        candidate.test_closed_trades,
                        candidate.expectancy,
                        candidate.sharpe_ratio,
                        candidate.sortino_ratio,
                        candidate.calmar_ratio,
                        candidate.avg_win,
                        candidate.avg_loss,
                        candidate.payoff_ratio,
                        candidate.avg_hold_bars,
                        candidate.best_trade_share_pct,
                        candidate.equity_new_high_share_pct,
                        candidate.max_consecutive_losses,
                        candidate.equity_quality_score,
                        candidate.dominant_exit,
                        candidate.dominant_exit_share_pct,
                        candidate.walk_forward_windows,
                        candidate.walk_forward_pass_rate_pct,
                        candidate.walk_forward_avg_validation_pnl,
                        candidate.walk_forward_avg_test_pnl,
                        candidate.walk_forward_avg_validation_pf,
                        candidate.walk_forward_avg_test_pf,
                        candidate.component_count,
                        candidate.combo_outperformance_score,
                        candidate.combo_trade_overlap_pct,
                        candidate.best_regime,
                        candidate.best_regime_pnl,
                        candidate.worst_regime,
                        candidate.worst_regime_pnl,
                        candidate.dominant_regime_share_pct,
                        candidate.regime_stability_score,
                        candidate.regime_loss_ratio,
                        candidate.regime_trade_count_by_label,
                        candidate.regime_pnl_by_label,
                        candidate.regime_pf_by_label,
                        candidate.regime_win_rate_by_label,
                        candidate.variant_label,
                        candidate.timeframe_label,
                        candidate.session_label,
                        candidate.regime_filter_label,
                        json.dumps(candidate.execution_overrides or {}),
                        candidate.name in recommended_names,
                    ],
                )
        return run_id

    def promote_symbol_research_candidates(
        self,
        *,
        profile_name: str,
        data_symbol: str,
        broker_symbol: str,
        descriptors: list[AgentDescriptor],
        candidates,
        recommended_names: list[str],
        symbol_research_run_id: int,
    ) -> None:
        candidate_map = {candidate.name: candidate for candidate in candidates}
        now = datetime.utcnow()
        with self._connect() as connection:
            next_version_id = int(connection.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM agent_versions").fetchone()[0])
            next_evaluation_id = int(connection.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM agent_evaluations").fetchone()[0])

            for index, descriptor in enumerate(descriptors):
                candidate = candidate_map[descriptor.agent_name]
                version_id = next_version_id + index
                evaluation_id = next_evaluation_id + index
                status = "active" if descriptor.agent_name in recommended_names else ("testing" if candidate.realized_pnl > 0 else "rejected")
                recommended_action = (
                    "Promoted from symbol research into the active candidate set."
                    if descriptor.agent_name in recommended_names
                    else "Keep in testing." if candidate.realized_pnl > 0 else "Do not activate; redesign or leave archived."
                )

                connection.execute(
                    """
                    INSERT INTO agent_versions (
                        id,
                        experiment_id,
                        profile_name,
                        agent_name,
                        lifecycle_scope,
                        class_name,
                        code_path,
                        parameters_json,
                        data_symbol,
                        broker_symbol
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        version_id,
                        symbol_research_run_id,
                        profile_name,
                        descriptor.agent_name,
                        descriptor.lifecycle_scope,
                        descriptor.class_name,
                        descriptor.code_path,
                        json.dumps({"source": "symbol_research"}),
                        data_symbol,
                        broker_symbol,
                    ],
                )
                connection.execute(
                    """
                    INSERT INTO agent_evaluations (
                        id,
                        experiment_id,
                        profile_name,
                        agent_name,
                        lifecycle_scope,
                        evaluation_source,
                        realized_pnl,
                        closed_trades,
                        win_rate_pct,
                        profit_factor,
                        max_drawdown_pct,
                        data_source,
                        verdict,
                        recommended_action
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        evaluation_id,
                        symbol_research_run_id,
                        profile_name,
                        descriptor.agent_name,
                        descriptor.lifecycle_scope,
                        "symbol_research",
                        candidate.realized_pnl,
                        candidate.closed_trades,
                        candidate.win_rate_pct,
                        candidate.profit_factor,
                        candidate.max_drawdown_pct,
                        "symbol_research",
                        "promising" if descriptor.agent_name in recommended_names else ("needs_retest" if candidate.realized_pnl > 0 else "rejected"),
                        recommended_action,
                    ],
                )
                existing = connection.execute(
                    """
                    SELECT first_seen_at
                    FROM agent_catalog
                    WHERE profile_name = ? AND agent_name = ? AND lifecycle_scope = ?
                    """,
                    [profile_name, descriptor.agent_name, descriptor.lifecycle_scope],
                ).fetchone()
                first_seen_at = existing[0] if existing is not None else now
                connection.execute(
                    """
                    INSERT OR REPLACE INTO agent_catalog (
                        profile_name,
                        agent_name,
                        lifecycle_scope,
                        class_name,
                        code_path,
                        description,
                        variant_label,
                        timeframe_label,
                        session_label,
                        status,
                        is_active,
                        first_seen_at,
                        last_seen_at,
                        last_version_id,
                        last_evaluation_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        profile_name,
                        descriptor.agent_name,
                        descriptor.lifecycle_scope,
                        descriptor.class_name,
                        descriptor.code_path,
                        descriptor.description,
                        descriptor.variant_label,
                        descriptor.timeframe_label,
                        descriptor.session_label,
                        status,
                        descriptor.agent_name in recommended_names,
                        first_seen_at,
                        now,
                        version_id,
                        evaluation_id,
                    ],
                )

    def list_recent_experiments(self, profile_name: str, limit: int = 5) -> list[ExperimentSnapshot]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    created_at,
                    profile_name,
                    ending_equity,
                    realized_pnl,
                    closed_trades,
                    win_rate_pct,
                    profit_factor,
                    max_drawdown_pct,
                    ftmo_passed,
                    local_summary,
                    ai_summary
                FROM experiments
                WHERE profile_name = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                [profile_name, limit],
            ).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def get_best_experiment(self, profile_name: str) -> ExperimentSnapshot | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    created_at,
                    profile_name,
                    ending_equity,
                    realized_pnl,
                    closed_trades,
                    win_rate_pct,
                    profit_factor,
                    max_drawdown_pct,
                    ftmo_passed,
                    local_summary,
                    ai_summary
                FROM experiments
                WHERE profile_name = ?
                ORDER BY realized_pnl DESC, profit_factor DESC, closed_trades DESC, id DESC
                LIMIT 1
                """,
                [profile_name],
            ).fetchone()
        return self._row_to_snapshot(row) if row is not None else None

    def compare_latest_runs(self, profile_name: str) -> tuple[ExperimentSnapshot | None, ExperimentSnapshot | None]:
        recent = self.list_recent_experiments(profile_name, limit=2)
        if not recent:
            return None, None
        if len(recent) == 1:
            return recent[0], None
        return recent[0], recent[1]
