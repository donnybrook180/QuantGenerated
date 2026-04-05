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

Live order placement is disabled by default. Enable it only after paper validation by setting `live_trading_enabled=True` in [quant_system/config.py](C:\Users\liset\PycharmProjects\QuantGenerated\quant_system\config.py).

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
