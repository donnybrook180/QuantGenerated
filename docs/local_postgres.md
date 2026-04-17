# Local Postgres

Deze repo kan nu een lokale Postgres gebruiken als eerste stap naar een gedeelde database-backend voor live/shared state.

## Wat dit nu doet

- start een lokale Postgres via Docker
- voegt app-config toe via `.env`
- bootstrap een eerste schema voor:
  - `experiments`
  - `experiment_artifacts`
  - `symbol_research_runs`
  - `symbol_research_candidates`
  - `symbol_execution_sets`
  - `symbol_execution_set_items`
  - `mt5_fill_events`

De bestaande runtime gebruikt nog steeds DuckDB. Dit is bewust een veilige eerste stap.

## 1. Zet env vars

Minimaal:

```env
POSTGRES_ENABLED=true
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=quant_generated
POSTGRES_USER=quant
POSTGRES_PASSWORD=quant
POSTGRES_SSLMODE=prefer
```

## 2. Start Docker Postgres

```powershell
docker compose -f docker-compose.postgres.yml up -d
```

Check health:

```powershell
docker compose -f docker-compose.postgres.yml ps
```

## 3. Bootstrap schema

```powershell
.\.venv\Scripts\python.exe main_postgres_bootstrap.py
```

Bij succes print de app:

- host
- port
- database
- DSN zonder wachtwoord
- connected user

## 4. Stoppen

```powershell
docker compose -f docker-compose.postgres.yml down
```

Wil je de database inclusief volume verwijderen:

```powershell
docker compose -f docker-compose.postgres.yml down -v
```

## Volgende migratiestap

De logische volgende stap is `ExperimentStore` dual-backend maken:

- Postgres voor live/shared metadata
- DuckDB voorlopig behouden voor `market_bars` en zware research scans
