from __future__ import annotations

from quant_system.config import SystemConfig
from quant_system.db.postgres import initialize_postgres_schema, test_postgres_connection


def main() -> int:
    config = SystemConfig()
    result = initialize_postgres_schema(config)
    health = test_postgres_connection(config)
    print("Postgres bootstrap complete.")
    print(f"Host: {result.host}")
    print(f"Port: {result.port}")
    print(f"Database: {result.database}")
    print(f"DSN: {result.dsn_without_password}")
    print(f"Connected user: {health['user']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
