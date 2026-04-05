from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import duckdb

from quant_system.models import MarketBar


@dataclass(slots=True)
class DuckDBMarketDataStore:
    database_path: str

    def __post_init__(self) -> None:
        self._initialize_schema()

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self.database_path)

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
