# Multi-Prop Env And Live Plan

Date: 2026-04-26

## Doel

De repo moet handiger worden voor wisselen tussen meerdere prop firms zonder steeds `.env` handmatig te herschrijven.

Gewenste operator-ervaring:

- voor research kies je precies 1 broker via `PROP_BROKER`
- in `.env` blijven de MT5 credentials van meerdere prop firms tegelijk staan
- voor live definieer je een lijst van prop firms
- live execution draait per prop firm in een eigen loop / eigen proces

## Waarom niet alles in 1 gedeelde live loop

De huidige codebase ondersteunt MT5 sessies per proces, maar nog niet schoon genoeg per broker binnen 1 gedeelde live runtime.

Belangrijk:

- `MT5Client` bewaakt 1 globale MT5 sessie per proces
- verschillende terminal/login/server combinaties kunnen niet tegelijk open blijven in hetzelfde proces
- live state, journals, incidents en autopsy/activity artifacts zijn nog niet volledig venue-aware

Daarom is de veilige operationele keuze:

- research: 1 broker tegelijk
- live: 1 proces per prop firm

## Gewenste `.env` interface

### Research

Research gebruikt:

```dotenv
PROP_BROKER=blue_guardian
```

Dat bepaalt:

- venue-aware profile namespace
- broker-backed research credentials
- venue-aware deployment output

### Live

Live gebruikt:

```dotenv
LIVE_PROP_BROKERS=ftmo,fundednext,blue_guardian
```

Dat is geen signaal om 1 MT5 process tegen 3 brokers tegelijk te laten draaien.
Het is een declaratieve lijst voor tooling of een supervisor die aparte broker-loops start.

### Broker credentials

Per broker moeten aparte env vars bestaan:

```dotenv
MT5_FTMO_LOGIN=
MT5_FTMO_PASSWORD=
MT5_FTMO_SERVER=
MT5_FTMO_TERMINAL_PATH=

MT5_FUNDEDNEXT_LOGIN=
MT5_FUNDEDNEXT_PASSWORD=
MT5_FUNDEDNEXT_SERVER=
MT5_FUNDEDNEXT_TERMINAL_PATH=

MT5_BLUE_GUARDIAN_LOGIN=
MT5_BLUE_GUARDIAN_PASSWORD=
MT5_BLUE_GUARDIAN_SERVER=
MT5_BLUE_GUARDIAN_TERMINAL_PATH=
```

De bestaande generieke fallback blijft voorlopig bestaan:

```dotenv
MT5_LOGIN=
MT5_PASSWORD=
MT5_SERVER=
MT5_TERMINAL_PATH=
```

## Gewenst runtime-model

### Research-model

Research is single-broker:

1. jij zet `PROP_BROKER`
2. research laadt exact die broker credentials
3. research schrijft venue-aware profile names en deployments

Voorbeeld:

- `PROP_BROKER=ftmo` -> profile `symbol::ftmo::eurusd`
- `PROP_BROKER=blue_guardian` -> profile `symbol::blue_guardian::eurusd`

### Live-model

Live is multi-broker via meerdere processen:

1. lees `LIVE_PROP_BROKERS`
2. start per broker een eigen live process
3. elk process laadt alleen:
   - zijn eigen MT5 credentials
   - zijn eigen venue deployments
   - zijn eigen live state

Dus:

- FTMO live loop verwerkt alleen `venue_key=ftmo`
- FundedNext live loop verwerkt alleen `venue_key=fundednext`
- Blue Guardian live loop verwerkt alleen `venue_key=blue_guardian`

## Status

Geïmplementeerd:

- broker-specifieke MT5 credential resolution via `PROP_BROKER`
- `LIVE_PROP_BROKERS` parsing in config
- venue-aware live state, journals, incidents, adaptation en activity artifacts
- `main_live_loop.py --broker <venue>`
- `main_live_mt5.py --broker <venue>`
- `main_live_supervisor.py` voor 1 proces per broker uit `LIVE_PROP_BROKERS`

## Concreet implementatieplan

### Phase 1: Config and env resolution

Doel:

- broker-specifieke credentials resolver bouwen
- `LIVE_PROP_BROKERS` parser toevoegen

Werk:

1. voeg helper toe zoals `resolve_mt5_credentials_for_venue(venue_key)`
2. normaliseer broker aliases via bestaande venue registry
3. laat resolver eerst broker-specifieke vars lezen
4. gebruik generieke `MT5_*` alleen als fallback
5. log expliciet wanneer fallback gebruikt wordt

Klaar als:

- config op basis van venue reproduceerbaar dezelfde MT5 settings oplevert

### Phase 2: Research path

Doel:

- research gebruikt automatisch broker-specifieke credentials van `PROP_BROKER`

Werk:

1. `SystemConfig` of research bootstrap moet MT5 credentials overriden op basis van `PROP_BROKER`
2. `main_symbol_research.py` hoeft verder niet te veranderen voor operator usage
3. README en docs moeten de research-flow simpel houden

Klaar als:

- jij alleen `PROP_BROKER` wisselt en research direct de juiste terminal/account gebruikt

### Phase 3: Live broker isolation

Doel:

- live per broker apart draaien

Werk:

1. bouw helper die deployments filtert op `venue_key`
2. bouw live config bootstrap per broker
3. maak een broker-specific entrypoint of supervisor:
   - `main_live_loop.py --broker ftmo`
   - `main_live_supervisor.py`
4. gebruik per process een eigen state path

Aanbevolen state-layout:

- `artifacts/live/ftmo/state/...`
- `artifacts/live/fundednext/state/...`
- `artifacts/live/blue_guardian/state/...`

Klaar als:

- brokers geen duplicate state, incidents of journals meer delen

### Phase 4: Venue-aware live artifacts

Doel:

- alle live artifacts per broker isoleren

Werk:

1. journals venue-aware maken
2. incidents venue-aware maken
3. autopsy/activity/adaptation state venue-aware maken
4. health reporting moet brokers apart tonen

Aanbevolen layout:

- `artifacts/live/ftmo/eurusd/journals/...`
- `artifacts/live/blue_guardian/eurusd/journals/...`

Klaar als:

- dezelfde symbolen bij verschillende brokers geen runtime-state meer delen

### Phase 5: Operator tooling

Doel:

- wisselen tussen brokers zonder `.env` geknoei

Werk:

1. voeg command toe voor config preview
2. voeg command toe voor live supervisor start
3. voeg command toe voor lijst actieve brokers/deployments

Voorbeelden:

```powershell
.\.venv\Scripts\python.exe tools\main_env_preview.py
.\.venv\Scripts\python.exe main_live_loop.py --broker blue_guardian
.\.venv\Scripts\python.exe main_live_supervisor.py
```

Klaar als:

- operator zonder codelezen kan zien welke broker/account/process actief is

## Aanbevolen `.env` voorbeeld

```dotenv
PROP_BROKER=blue_guardian
LIVE_PROP_BROKERS=ftmo,fundednext,blue_guardian

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

## Aanbevolen operator-usage

### Research

1. zet `PROP_BROKER`
2. run research
3. inspecteer venue-aware artifacts

### Live

1. zet `LIVE_PROP_BROKERS`
2. start 1 process per broker
3. monitor reports per broker

## Definition of Done

Dit plan is pas af als:

- jij voor research alleen `PROP_BROKER` hoeft te wijzigen
- jij meerdere broker credentials tegelijk in `.env` kunt laten staan
- live per broker apart draait zonder gedeelde runtime-state
- live tooling duidelijk toont welke broker/account actief is
- docs precies uitleggen hoe jij de repo moet gebruiken
