# QuantGenerated

Personal multi-agent quant research trading system scaffold built around three isolated environments, now wired for Polygon historical data, DuckDB storage, Optuna optimization, and MT5 execution for FTMO-style workflows:

- `research`: feature engineering and alpha discovery
- `optimization`: walk-forward validation and parameter search
- `execution`: lightweight event-driven runtime with risk controls

## Architecture

### The Three-Body System

1. Research environment (`quant_system/research`)
   - point-in-time data checks
   - feature engineering library
   - signal generation inputs for agents
2. Optimization environment (`quant_system/optimization`)
   - walk-forward splits
   - parameter search scaffold
   - regime-aware validation metrics
3. Execution environment (`quant_system/execution`)
   - async event loop
   - simulated broker adapter
   - heartbeat, logging, and kill-switch

### Multi-agent model

The runtime uses multiple cooperating agents:

- `TrendAgent`: EMA-style trend filter
- `MeanReversionAgent`: short-horizon reversion filter
- `RiskSentinelAgent`: veto agent that blocks trades when volatility is too high

Agents emit `SignalEvent`s. The coordinator aggregates them into a single action and forwards approved orders to the broker adapter.

## Run

```powershell
.\.venv\Scripts\python.exe main.py
```

This fetches historical bars from Polygon, persists them in DuckDB, runs Optuna walk-forward tuning, and then runs a local paper-trading style execution simulation on the stored dataset.

After each run, the app now also:

- writes a local AI-style summary to `artifacts/<profile>_ai_summary.txt`
- writes the next recommended experiments to `artifacts/<profile>_next_experiment.txt`
- writes experiment memory to `artifacts/<profile>_experiment_history.txt`
- writes latest-vs-previous comparisons to `artifacts/<profile>_run_comparison.txt`
- stores the run, metrics, artifacts, and summaries in DuckDB for experiment memory

If `AI_API_KEY` is set in `.env`, the app also attempts an LLM-enriched summary. Without a key, it still writes deterministic local summaries.

## MT5 Test

Use this to test `XAUUSD`, `US500`, and `GER40` directly against your MetaTrader terminal without forcing live order placement:

```powershell
.\.venv\Scripts\python.exe main_mt5_test.py
```

The MT5 test runner:

- logs into your local MetaTrader terminal
- resolves the broker symbol for each requested profile
- fetches recent MT5 bars
- rebuilds features from MT5 data
- reports the latest agent decision and confidence per profile

Choose the tested profiles with `MT5_TEST_PROFILES` in `.env`, for example:

```powershell
MT5_TEST_PROFILES=xauusd_volatility,us500_trend,ger40_orb
```

## AI Chat

Gebruik de lokale AI/query-laag om vragen te stellen over je experiment history:

```powershell
.\.venv\Scripts\python.exe main_ai_chat.py "vergelijk XAUUSD en US500"
```

De chatlaag werkt eerst lokaal op basis van DuckDB experiment memory. Als `AI_API_KEY` is gezet, probeert hij het antwoord compacter te herformuleren via het model, zonder nieuwe metrics te verzinnen.

Voor OpenRouter gebruik je bijvoorbeeld:

```powershell
AI_PROVIDER=openrouter
AI_MODEL=openai/gpt-5-mini
AI_API_KEY=your_openrouter_key_here
OPENROUTER_SITE_URL=https://your-local-app.example
OPENROUTER_APP_NAME=QuantGenerated
```

Voor directe OpenAI kun je terugzetten naar:

```powershell
AI_PROVIDER=openai
AI_MODEL=gpt-5-mini
AI_API_KEY=your_openai_key_here
```

Controleer je provider/key snel met:

```powershell
.\.venv\Scripts\python.exe main_ai_doctor.py
```

Dat commando print de actieve AI-config en doet daarna een kleine testcall.

## Secrets

Vul je keys en brokergegevens in in `.env`. De echte `.env` staat in `.gitignore`, dus je secrets blijven lokaal. Gebruik `.env.example` als referentie.

```powershell
POLYGON_API_KEY=your_polygon_api_key_here
POLYGON_DATA_SYMBOL=SPY
POLYGON_TIMESPAN=minute
POLYGON_MULTIPLIER=5
POLYGON_HISTORY_DAYS=30
```

## Broker setup

Set these environment variables if MT5 is not already logged in locally:

```powershell
MT5_LOGIN=12345678
MT5_PASSWORD=your-password
MT5_SERVER=YourBroker-Server
MT5_TERMINAL_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
MT5_BROKER_SYMBOL=SPY
```

Live order placement is disabled by default. Enable it only after paper validation by setting `LIVE_TRADING_ENABLED=true` in `.env`.

## Instrument and FTMO config

Je configureert nu drie lagen expliciet in `.env`:

- `POLYGON_DATA_SYMBOL` voor research/backtest data
- `MT5_BROKER_SYMBOL` voor je echte FTMO/MT5 order routing
- kosten- en drawdownparameters zoals `EXECUTION_COMMISSION_PER_UNIT`, `EXECUTION_SLIPPAGE_BPS`, `RISK_MAX_DAILY_LOSS_PCT` en `RISK_MAX_TOTAL_DRAWDOWN_PCT`

Na elke run print de app ook een FTMO-evaluatie met:

- closed trades
- win rate
- profit factor
- max drawdown
- total costs
- pass/fail plus redenen

Er zijn nu drie profielstrategieën ingebouwd:

- `us500_trend`: `SPY` data, `US500.cash` broker, trend continuation
- `us100_trend`: `QQQ` data, `US100.cash` broker, trend continuation
- `ger40_orb`: `I:DAX` data, `GER40.cash` broker, opening range breakout
- `xauusd_volatility`: `C:XAUUSD` data, `XAUUSD` broker, volatility breakout

De actieve set kies je met `ACTIVE_STRATEGY_PROFILES` in `.env`.
Als Polygon voor een profiel geen data teruggeeft, kun je het dataticker per profiel overriden met:

- `US500_TREND_DATA_SYMBOL`
- `US100_TREND_DATA_SYMBOL`
- `GER40_ORB_DATA_SYMBOL`
- `XAUUSD_VOLATILITY_DATA_SYMBOL`

## FTMO guardrails

De backtest en optimizer houden nu expliciet rekening met:

- slippage in basis points
- commission per traded unit
- maximale daily loss
- maximale total drawdown

Dat maakt de selectie strenger, maar ook eerlijker. Het garandeert geen winstgevendheid; het voorkomt vooral dat je een strategy kiest die alleen op frictionless backtests goed lijkt.

## Next upgrades

- Add point-in-time correction metadata and corporate action handling on top of DuckDB.
- Extend the MT5 adapter with pending orders, stop-loss, and take-profit management.
- Add Telegram alert transport to `monitoring/heartbeat.py`.
