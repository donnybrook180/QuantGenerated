from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path

import duckdb
from quant_system.ai.models import ExperimentSnapshot


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
    ) -> None:
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
