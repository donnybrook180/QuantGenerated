# Repo Usage Guide

Date: 2026-04-26

Dit document legt uit hoe je deze repo praktisch gebruikt voor:

- research
- venue-aware deployments
- live execution
- multi-prop workflow

Gebruik dit document als operator-handleiding.

## Kernidee

De repo werkt het beste met deze mentale scheiding:

1. research kiest per run 1 prop firm
2. deployments worden per prop firm opgeslagen
3. live execution draait per prop firm apart

Dus:

- 1 codebase
- meerdere brokers
- research per broker
- live per broker

## Belangrijkste environment variables

### Research broker

Voor research gebruik je:

```dotenv
PROP_BROKER=blue_guardian
```

Die waarde bepaalt welke prop-firm context wordt gebruikt.

### Live brokers

Voor live gebruik je:

```dotenv
LIVE_PROP_BROKERS=ftmo,fundednext,blue_guardian
```

Dit is de lijst brokers die jij live wilt draaien.

### MT5 credentials

Je bewaart de MT5 credentials van meerdere brokers tegelijk in `.env`.

Voorbeeld:

```dotenv
MT5_FTMO_LOGIN=...
MT5_FTMO_PASSWORD=...
MT5_FTMO_SERVER=...
MT5_FTMO_TERMINAL_PATH=C:\Path\To\FTMO\terminal64.exe

MT5_FUNDEDNEXT_LOGIN=...
MT5_FUNDEDNEXT_PASSWORD=...
MT5_FUNDEDNEXT_SERVER=...
MT5_FUNDEDNEXT_TERMINAL_PATH=C:\Path\To\FundedNext\terminal64.exe

MT5_BLUE_GUARDIAN_LOGIN=...
MT5_BLUE_GUARDIAN_PASSWORD=...
MT5_BLUE_GUARDIAN_SERVER=...
MT5_BLUE_GUARDIAN_TERMINAL_PATH=C:\Path\To\BlueGuardian\terminal64.exe
```

## Hoe jij research draait

### Standaard flow

1. zet in `.env`:

```dotenv
PROP_BROKER=blue_guardian
```

2. run symbol research:

```powershell
.\.venv\Scripts\python.exe main_symbol_research.py EURUSD
```

3. inspecteer:

- `artifacts/research/eurusd/reports/symbol_research.txt`
- `artifacts/research/eurusd/reports/viability_autopsy.txt`
- venue-aware deployment artifact

### Wat je mag verwachten

Research schrijft:

- symbol research reports
- viability autopsy
- venue-aware deployment

Venue-aware profile namespace voorbeeld:

- `symbol::blue_guardian::eurusd`

Venue-aware deployment voorbeeld:

- `artifacts/deploy/blue_guardian/eurusd/live.json`

## Hoe jij tussen prop firms wisselt voor research

Je wijzigt alleen:

```dotenv
PROP_BROKER=ftmo
```

of:

```dotenv
PROP_BROKER=fundednext
```

of:

```dotenv
PROP_BROKER=blue_guardian
```

Daarna run je research opnieuw.

Je hoeft niet steeds:

- logins te herschrijven
- passwords te verplaatsen
- terminal paths te vervangen

## Hoe jij live gebruikt

### Belangrijke regel

Draai live per broker in een eigen loop / eigen proces.

Dus niet:

- 1 gedeelde MT5 process voor alle brokers

Maar wel:

- 1 live process voor FTMO
- 1 live process voor FundedNext
- 1 live process voor Blue Guardian

## Aanbevolen live workflow

### 1. Controleer deployments

Controleer of de juiste venue deployments bestaan:

- `artifacts/deploy/ftmo/...`
- `artifacts/deploy/fundednext/...`
- `artifacts/deploy/blue_guardian/...`

### 2. Start live per broker

Aanbevolen patroon:

```powershell
.\.venv\Scripts\python.exe main_live_loop.py --broker ftmo
.\.venv\Scripts\python.exe main_live_loop.py --broker fundednext
.\.venv\Scripts\python.exe main_live_loop.py --broker blue_guardian
```

Of laat de brokerlijst uit `.env` automatisch starten:

```powershell
.\.venv\Scripts\python.exe main_live_supervisor.py
```

Praktisch betekent dat:

- 1 proces met FTMO broker-config
- 1 proces met FundedNext broker-config
- 1 proces met Blue Guardian broker-config

### 3. Eenmalige live run per broker

Voor een enkele cycle:

```powershell
.\.venv\Scripts\python.exe main_live_mt5.py --broker blue_guardian
```

## Welke reports jij gebruikt

Gebruik als hoofdvolgorde:

1. `docs/live_operations_manual.md`
2. `artifacts/system/reports/live_health_report.txt`
3. `artifacts/system/reports/trade_cost_analysis.txt`
4. `artifacts/system/reports/tca_impact_report.txt`
5. `artifacts/system/reports/execution_adaptation_report.txt`
6. `artifacts/system/reports/live_research_queue.txt`

## Welke artifacts belangrijk zijn

### Research artifacts

- `artifacts/research/<symbol>/reports/symbol_research.txt`
- `artifacts/research/<symbol>/reports/symbol_research.csv`
- `artifacts/research/<symbol>/reports/viability_autopsy.txt`

### Deployment artifacts

- `artifacts/deploy/<venue>/<symbol>/live.json`

### Live artifacts

- journals
- incidents
- adaptation/activity artifacts

## Dagelijkse operator-routine

1. kies of wijzig `PROP_BROKER` als je research wilt doen
2. run symbol research
3. check de research reports
4. check de venue-aware deployment
5. laat live per broker apart draaien
6. lees health en TCA reports

## Veelvoorkomende taken

### Research draaien voor Blue Guardian

```dotenv
PROP_BROKER=blue_guardian
```

```powershell
.\.venv\Scripts\python.exe main_symbol_research.py EURUSD
```

### Research draaien voor FTMO

```dotenv
PROP_BROKER=ftmo
```

```powershell
.\.venv\Scripts\python.exe main_symbol_research.py XAUUSD
```

### Execution set bekijken

```powershell
.\.venv\Scripts\python.exe tools\main_symbol_execution_set.py
```

### Agent-overzicht bekijken

```powershell
.\.venv\Scripts\python.exe tools\main_agent_registry.py
```

## Wat je niet moet doen

Niet doen:

- brokers live door elkaar laten lopen in 1 MT5 sessie
- research artifacts van verschillende prop firms als equivalent behandelen
- venue deployments handmatig overschrijven
- live incidenten van broker A interpreteren als data van broker B

## Praktische vuistregels

- `PROP_BROKER` is voor research
- `LIVE_PROP_BROKERS` is voor live planning
- live execution blijft broker-per-proces
- `main_live_supervisor.py` start 1 live loop per broker uit `LIVE_PROP_BROKERS`
- vergelijk brokers op rapportuitkomsten, niet op gemixte ruwe state

## Aanbevolen extra documenten

Gebruik daarnaast:

- `docs/live_operations_manual.md`
- `docs/prop_firm_launch_checklist.md`
- `docs/architecture_map.md`
- `docs/report_map.md`
