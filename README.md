# QuantGenerated

Personal multi-agent quant research trading system scaffold built around three isolated environments, now wired for Polygon historical data, DuckDB storage, Optuna optimization, and MT5 execution for FTMO-style workflows:

- `research`: feature engineering and alpha discovery
- `optimization`: walk-forward validation and parameter search
- `execution`: lightweight event-driven runtime with risk controls

## Architecture

### Monorepo Layers

De repo is nu functioneel opgesplitst in drie lagen binnen dezelfde codebase:

- `quant_system/core`
  - gedeelde models
  - risk/cost primitives
  - symbol resolution
  - execution primitives
- `quant_system/research`
  - symbol research
  - candidate selectie
  - walk-forward en plots
  - execution set export
- `quant_system/live`
  - deployment artifacts
  - MT5 live runtime
  - live journaling / incidents
  - polling loop

De bestaande `main_*.py` entrypoints blijven werken, maar lopen nu via deze research/live lagen.

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

### Primary entrypoints

Bovenaan in de repo staan nu alleen de scripts die je normaal zelf direct aanroept:

- `main.py`
- `main_symbol_research.py`
- `main_symbol_execute.py`
- `main_live_mt5.py`
- `main_live_loop.py`

Minder vaak gebruikte utility scripts staan nu in `tools/`.

```powershell
.\.venv\Scripts\python.exe main.py
```

This fetches historical bars from Polygon, persists them in DuckDB, runs Optuna walk-forward tuning, and then runs a local paper-trading style execution simulation on the stored dataset.

Batch runs now also add a small pause between profiles and retry Polygon requests with exponential backoff, so a single rate-limit event is less likely to kill the whole run.

You can also control how research data is loaded:

- `POLYGON_FETCH_POLICY=network_first`: default, try Polygon first and fall back to DuckDB cache on rate limits
- `POLYGON_FETCH_POLICY=cache_first`: use DuckDB cache first, only hit Polygon if cache is missing
- `POLYGON_FETCH_POLICY=cache_only`: never hit Polygon, fail if the cache is missing

For multi-symbol research on a rate-limited Polygon plan, `cache_first` is usually the right mode after you have seeded each symbol once.

After each run, the app now also:

- writes a local AI-style summary to `artifacts/profiles/<profile>/reports/ai_summary.txt`
- writes the next recommended experiments to `artifacts/profiles/<profile>/reports/next_experiment.txt`
- writes experiment memory to `artifacts/profiles/<profile>/reports/experiment_history.txt`
- writes latest-vs-previous comparisons to `artifacts/profiles/<profile>/reports/run_comparison.txt`
- writes per-agent status to `artifacts/profiles/<profile>/reports/agent_registry.txt`
- writes per-agent lifecycle catalog to `artifacts/profiles/<profile>/reports/agent_catalog.txt`
- stores the run, metrics, artifacts, and summaries in DuckDB for experiment memory

If `AI_API_KEY` is set in `.env`, the app also attempts an LLM-enriched summary. Without a key, it still writes deterministic local summaries.

## Symbol Research

Als je niet eerst zelf een vast profiel wilt kiezen, kun je ook direct research doen op alleen een symbool:

```powershell
.\.venv\Scripts\python.exe main_symbol_research.py C:XAUUSD XAUUSD
```

Of zet het symbool eenmalig in `.env` en run zonder argumenten:

```powershell
SYMBOL_RESEARCH_SYMBOL=XAUUSD
SYMBOL_RESEARCH_MODE=auto
```

`SYMBOL_RESEARCH_BROKER_SYMBOL` is alleen nodig als je bewust de automatische broker-mapping wilt overriden.

Daarna:

```powershell
.\.venv\Scripts\python.exe main_symbol_research.py
```

Voor symbol research kun je nu ook generieke aliassen gebruiken. De app mappt die automatisch naar een bruikbare Polygon-proxy en broker-symbol:

- `US500` -> data `SPY`, broker `US500.cash`
- `US100` -> data `QQQ`, broker `US100.cash`
- `GER40` -> data `DAX`, broker `GER40.cash`
- `XAUUSD` -> data `C:XAUUSD`, broker `XAUUSD`

Deze runner test meerdere archetypes op hetzelfde symbool, zoals trend, mean reversion, opening range breakout en volatility breakout. Daarna test hij ook combinaties van de best scorende losse archetypes. De resultaten komen in:

- `artifacts/research/<symbol>/reports/symbol_research.csv`
- `artifacts/research/<symbol>/reports/symbol_research.txt`

Candidate-level trade logs en analyses komen in:

- `artifacts/research/<symbol>/candidates/<candidate>_trades.csv`
- `artifacts/research/<symbol>/candidates/<candidate>_analysis.txt`

Plots komen in:

- `artifacts/research/<symbol>/plots/candidate_ranking.png`
- `artifacts/research/<symbol>/plots/validation_test_scatter.png`
- `artifacts/research/<symbol>/plots/regimes.png`
- `artifacts/research/<symbol>/plots/best_candidate_equity.png`

Voor forex en gold kun je nu ook een lokale macro-event kalender meegeven via:

```powershell
MACRO_EVENT_CALENDAR_ENABLED=true
MACRO_EVENT_CALENDAR_PATH=artifacts/system/data/macro_calendar.csv
MACRO_PRE_EVENT_MINUTES=60
MACRO_POST_EVENT_MINUTES=120
```

Het CSV-formaat is:

```csv
timestamp_utc,importance,currencies,event_code,description,symbols
2026-04-10T12:30:00Z,high,USD,CPI,US CPI,
2026-04-11T08:00:00Z,high,EUR,ECB_RATE,ECB rate decision,
2026-04-12T18:00:00Z,high,USD,FOMC_MINUTES,FOMC minutes,XAUUSD
```

Deze kalender voedt featurevelden zoals:

- `macro_event_count_1d`
- `macro_high_impact_event_day`
- `macro_pre_event_window`
- `macro_post_event_window`
- `macro_event_blackout`
- `macro_minutes_to_next_event`

Symbol research bepaalt nu zelf het symbooltype en kiest automatisch de horizon:

- crypto: minimaal `365` dagen
- metals / forex / indices: minimaal `180` dagen

Je kunt dit nog steeds overriden met `SYMBOL_RESEARCH_HISTORY_DAYS`, maar dat hoeft meestal niet.

Daarna splitst de app de data in:

- train: 60%
- validation: 20%
- test: 20%

Promotie en execution selection gebeuren nu op validation/test, niet meer alleen op de totale periode.

`SYMBOL_RESEARCH_MODE=auto` is de aanbevolen stand. Dan controleert de app zelf:

- ontbreken de benodigde timeframe-caches nog: `seed`
- zijn de benodigde caches al aanwezig: `full`

In `seed` mode haalt de app minder timeframe/session-varianten op. Zodra voldoende cache aanwezig is, schakelt hij in `auto` vanzelf door naar `full`.

Alleen als je bewust wilt forceren, gebruik je:

```powershell
SYMBOL_RESEARCH_MODE=seed
```

of:

```powershell
SYMBOL_RESEARCH_MODE=full
```

Voor zware research blijft dit nuttig:

```powershell
POLYGON_FETCH_POLICY=cache_first
```

zodat de volledige research zo veel mogelijk uit DuckDB-cache draait in plaats van Polygon opnieuw zwaar te belasten.

Na zo'n research-run kun je de gepromote winnaars direct uitvoeren als symbol-level active set:

```powershell
.\.venv\Scripts\python.exe main_symbol_execute.py C:XAUUSD
```

Om te zien welke execution subset symbol research heeft vastgezet:

```powershell
.\.venv\Scripts\python.exe tools\main_symbol_execution_set.py
```

Of voor een specifiek symbool:

```powershell
.\.venv\Scripts\python.exe tools\main_symbol_execution_set.py C:XAUUSD
```

Voor een advisory risk allocation over de nieuwste symbol research winnaars:

```powershell
.\.venv\Scripts\python.exe tools\main_portfolio_allocator.py
```

Of alleen voor specifieke symbolen/profielen:

```powershell
.\.venv\Scripts\python.exe tools\main_portfolio_allocator.py XAUUSD BTC
```

Dit gebruikt alleen de nieuwste, geldige symbol execution sets en weegt ze op research-robuustheid:

- validation/test kwaliteit
- walk-forward pass rate
- trade count
- drawdown
- regime-concentratie

De output komt ook in:

- `artifacts/system/reports/portfolio_allocator.txt`

Als een symbol research-run een `accepted` execution set vindt, exporteert hij nu ook automatisch een live deployment artifact:

- `artifacts/deploy/<symbol>/live.json`

Bijvoorbeeld:

- `artifacts/deploy/us500/live.json`
- `artifacts/deploy/xauusd/live.json`
- `artifacts/deploy/btc/live.json`

Die deployment artifacts zijn de brug tussen research en live. De live runner doet zelf geen research; hij leest alleen deze bestanden.

## Live Trading

Voor een eenmalige live/dry-run evaluatie:

```powershell
.\.venv\Scripts\python.exe main_live_mt5.py
```

Of voor één symbool:

```powershell
.\.venv\Scripts\python.exe main_live_mt5.py US500
```

Voor een doorlopende poll-loop:

```powershell
.\.venv\Scripts\python.exe main_live_loop.py
```

Of per symbool:

```powershell
.\.venv\Scripts\python.exe main_live_loop.py US500
```

Aanbevolen eerste stap:

```powershell
LIVE_TRADING_ENABLED=false
MT5_POLL_SECONDS=60
```

Dus eerst dry-run laten meelopen.

De live laag schrijft nu ook naar:

- `artifacts/live/<symbol>/journals/<timestamp>_journal.json`
- `artifacts/live/<symbol>/incidents/<timestamp>_incident.txt`
- `artifacts/live/state/loop_state.json`

### Hedging vs Netting

De live runner detecteert nu expliciet of je MT5-account:

- `hedging`
- of `netting`

is.

Belangrijk:

- op `hedging` ondersteunt broker-side positie-isolatie per strategie goed
- op `netting` is echte multi-strategy isolatie per symbool broker-side niet volledig mogelijk

Daarom geldt nu standaard:

- als je account `netting` is
- en een deployment heeft meerdere strategieën op hetzelfde symbool
- dan blokkeert de live runner echte execution voor dat symbool

Dat geeft dan acties zoals:

- `netting_blocked_multi_strategy`

Alleen als je bewust wilt overriden:

```powershell
MT5_ALLOW_NETTING_MULTI_STRATEGY=true
```

Maar dat is niet de veilige default.

## MT5 Test

Use this to test `XAUUSD`, `US500`, and `GER40` directly against your MetaTrader terminal without forcing live order placement:

```powershell
.\.venv\Scripts\python.exe tools\main_mt5_test.py
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
.\.venv\Scripts\python.exe tools\main_ai_chat.py "vergelijk XAUUSD en US500"
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

Voor fallback over meerdere keys/providers kun je een provider pool definiëren:

```powershell
AI_PROVIDER_ORDER=openrouter_1,openrouter_2,openai_1

AI_OPENROUTER_1_API_KEY=your_primary_openrouter_key
AI_OPENROUTER_1_MODEL=openai/gpt-5-mini

AI_OPENROUTER_2_API_KEY=your_secondary_openrouter_key
AI_OPENROUTER_2_MODEL=nvidia/nemotron-3-super-120b-a12b:free

AI_OPENAI_1_API_KEY=your_openai_key
AI_OPENAI_1_MODEL=gpt-5-mini
```

De AI-laag probeert deze slots in volgorde. Bij tijdelijke fouten zoals `429`, timeout of `5xx` gaat hij door naar de volgende slot. Bij succesvolle responses logt hij welke slot werkte.

Voor directe OpenAI kun je terugzetten naar:

```powershell
AI_PROVIDER=openai
AI_MODEL=gpt-5-mini
AI_API_KEY=your_openai_key_here
```

Controleer je provider/key snel met:

```powershell
.\.venv\Scripts\python.exe tools\main_ai_doctor.py
```

Dat commando print de actieve AI-config en doet daarna een kleine testcall.

Voor een overzicht van alle agents die de applicatie kent:

```powershell
.\.venv\Scripts\python.exe tools\main_agent_registry.py
```

Of voor een specifiek profiel:

```powershell
.\.venv\Scripts\python.exe tools\main_agent_registry.py ger40_orb
```

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
