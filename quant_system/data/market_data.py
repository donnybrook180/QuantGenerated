from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import shutil
import tempfile
from pathlib import Path

import duckdb

from quant_system.models import MarketBar


@dataclass(slots=True)
class DuckDBMarketDataStore:
    database_path: str
    read_only: bool = False

    def __post_init__(self) -> None:
        if not self.read_only:
            self._initialize_schema()

    def _connect(self) -> duckdb.DuckDBPyConnection:
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
                CREATE TABLE IF NOT EXISTS market_bars (
                    symbol VARCHAR NOT NULL,
                    timeframe VARCHAR NOT NULL,
                    ts TIMESTAMP NOT NULL,
                    open DOUBLE NOT NULL,
                    high DOUBLE NOT NULL,
                    low DOUBLE NOT NULL,
                    close DOUBLE NOT NULL,
                    volume DOUBLE NOT NULL,
                    source VARCHAR NOT NULL,
                    ingested_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (symbol, timeframe, ts)
                )
                """
            )

    def upsert_bars(self, bars: list[MarketBar], timeframe: str, source: str) -> None:
        if not bars:
            return
        if self.read_only:
            raise RuntimeError("Cannot upsert bars with a read-only DuckDBMarketDataStore.")
        rows = [
            (
                bar.symbol,
                timeframe,
                bar.timestamp.replace(tzinfo=None),
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                source,
                datetime.now(UTC).replace(tzinfo=None),
            )
            for bar in bars
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO market_bars
                (symbol, timeframe, ts, open, high, low, close, volume, source, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def load_bars(self, symbol: str, timeframe: str, limit: int) -> list[MarketBar]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ts, open, high, low, close, volume
                FROM market_bars
                WHERE symbol = ? AND timeframe = ?
                ORDER BY ts ASC
                LIMIT ?
                """,
                [symbol, timeframe, limit],
            ).fetchall()
        return [
            MarketBar(
                timestamp=row[0].replace(tzinfo=UTC),
                symbol=symbol,
                open=row[1],
                high=row[2],
                low=row[3],
                close=row[4],
                volume=row[5],
            )
            for row in rows
            if row[4] > 0 and row[2] >= row[3]
        ]

    def load_bars_before(self, symbol: str, timeframe: str, end_ts: datetime, limit: int) -> list[MarketBar]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ts, open, high, low, close, volume
                FROM market_bars
                WHERE symbol = ? AND timeframe = ? AND ts <= ?
                ORDER BY ts DESC
                LIMIT ?
                """,
                [symbol, timeframe, end_ts.replace(tzinfo=None), limit],
            ).fetchall()
        rows = list(reversed(rows))
        return [
            MarketBar(
                timestamp=row[0].replace(tzinfo=UTC),
                symbol=symbol,
                open=row[1],
                high=row[2],
                low=row[3],
                close=row[4],
                volume=row[5],
            )
            for row in rows
            if row[4] > 0 and row[2] >= row[3]
        ]

    def load_last_bar_before(self, symbol: str, timeframe: str, ts: datetime) -> MarketBar | None:
        bars = self.load_bars_before(symbol, timeframe, ts, 1)
        return bars[-1] if bars else None
