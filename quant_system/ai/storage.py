from __future__ import annotations

import json
from datetime import datetime
from dataclasses import asdict, is_dataclass
from pathlib import Path

import duckdb
from quant_system.ai.models import AgentDescriptor, AgentRegistryRecord, ExperimentSnapshot


class ExperimentStore:
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        self._initialize_schema()

    def _connect(self):
        return duckdb.connect(self.database_path)

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
                    variant_label VARCHAR,
                    timeframe_label VARCHAR,
                    session_label VARCHAR,
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
            connection.execute("ALTER TABLE agent_catalog ADD COLUMN IF NOT EXISTS variant_label VARCHAR")
            connection.execute("ALTER TABLE agent_catalog ADD COLUMN IF NOT EXISTS timeframe_label VARCHAR")
            connection.execute("ALTER TABLE agent_catalog ADD COLUMN IF NOT EXISTS session_label VARCHAR")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS variant_label VARCHAR")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS timeframe_label VARCHAR")
            connection.execute("ALTER TABLE symbol_research_candidates ADD COLUMN IF NOT EXISTS session_label VARCHAR")
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
                    execution_overrides_json TEXT,
                    selection_rank INTEGER
                )
                """
            )
            connection.execute("ALTER TABLE symbol_execution_set_items ADD COLUMN IF NOT EXISTS execution_overrides_json TEXT")

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
                    variant_label,
                    timeframe_label,
                    session_label,
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
                "variant_label": row[17] or "",
                "timeframe_label": row[18] or "",
                "session_label": row[19] or "",
                "execution_overrides": json.loads(row[20] or "{}"),
                "recommended": bool(row[21]),
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
                        execution_overrides_json,
                        selection_rank
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        execution_set_id,
                        profile_name,
                        str(row["candidate_name"]),
                        str(row["code_path"]),
                        json.dumps(row.get("execution_overrides", {})),
                        index,
                    ],
                )
        return execution_set_id

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
                SELECT candidate_name, code_path, execution_overrides_json, selection_rank
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
                    "execution_overrides": json.loads(row[2] or "{}"),
                    "selection_rank": int(row[3] or 0),
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
                        variant_label,
                        timeframe_label,
                        session_label,
                        execution_overrides_json,
                        recommended
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        candidate.variant_label,
                        candidate.timeframe_label,
                        candidate.session_label,
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
