# Refactor Plan

## Probleembeeld

De huidige codebase voelt onlogisch omdat een paar grote problemen tegelijk spelen:

- `quant_system/symbol_research.py` is een monoliet en bevat te veel verantwoordelijkheden tegelijk.
- Root-entrypoints, `quant_system/app.py`, `quant_system/research/*` en `quant_system/live/*` overlappen functioneel.
- Grote agentmodules zoals `agents/forex.py`, `agents/us500.py` en `agents/crypto.py` zijn te breed geworden.
- Het is niet duidelijk waar je iets moet zoeken: research, selection, viability, exports en deployment zitten niet schoon gescheiden.

## Doel

De codebase moet worden opgesplitst in duidelijke subsystemen met stabiele boundaries:

- `core`: gedeelde types en primitives
- `research`: research flow, catalog, viability, selection, exports
- `interpreter`: marktinterpretatie
- `evaluation`: evaluatielogica
- `optimization`: walk-forward en parameter search
- `live`: deployment en runtime
- `agents`: alleen agent-definities en agent-factory
- `tools`: operator- en support-scripts

## Gewenste structuur

```text
quant_system/
  app/
    orchestration.py
    profile_run.py
    data_loading.py
    reporting.py

  core/
    config.py
    models.py
    symbols.py
    regime.py
    costs.py

  research/
    app.py
    runner.py
    catalog.py
    selection.py
    viability.py
    exports.py
    execution_sets.py
    data_sources.py
    splits.py
    scoring.py
    optimization_hooks.py
    artifacts.py
    features.py
    funding.py
    cross_asset.py
    stock_selector.py
    stock_playbooks.py

  interpreter/
    app.py
    engines.py
    features.py
    reporting.py
    models.py

  evaluation/
    report.py

  optimization/
    walk_forward.py

  live/
    app.py
    runtime.py
    deploy.py
    health.py
    journal.py
    activity.py
    adaptation.py
    autopsy.py
    models.py

  agents/
    base.py
    common.py
    factory.py
    session.py
    macro.py
    trend.py
    forex/
      __init__.py
      trend.py
      breakout.py
      reversion.py
      event.py
    crypto/
      __init__.py
      trend.py
      breakout.py
      reversion.py
    us500/
      __init__.py
      momentum.py
      reversal.py
      session.py
    stocks/
      __init__.py
      momentum.py
      gap.py
      event.py
    ger40/
      __init__.py
      breakout.py
      reversion.py
    us100/
      __init__.py
      trend.py
      reversal.py
    xauusd/
      __init__.py
      breakout.py
      reclaim.py
```

## Fase 1: `symbol_research.py` opsplitsen

Huidige bron:

- `quant_system/symbol_research.py`

Doel: van monoliet naar losse researchmodules.

### `quant_system/research/catalog.py`

Verplaatsen:

- `CandidateSpec`
- strategy family / direction metadata
- expliciete strategy catalog
- `_candidate_spec(...)`
- `_candidate_specs(...)`
- `_exit_family_specs(...)`
- `_parameter_sweep_specs(...)`
- `_second_pass_specs(...)`
- `_regime_improvement_specs(...)`
- `_near_miss_optimizer_specs(...)`
- `_combined_specs(...)`
- `_with_variant_name(...)`

### `quant_system/research/viability.py`

Verplaatsen:

- `_research_thresholds(...)`
- `_is_sparse_candidate(...)`
- `_meets_monte_carlo_viability(...)`
- `_meets_viability(...)`
- `_meets_regime_specialist_viability(...)`
- `_promotion_tier_for_row(...)`
- `_candidate_failure_reasons(...)`

### `quant_system/research/selection.py`

Verplaatsen:

- `_candidate_row_value(...)`
- `_execution_candidate_row(...)`
- `_execution_candidate_row_from_result(...)`
- `_selection_component_keys(...)`
- `_candidate_selection_score(...)`
- `_is_valid_execution_combo(...)`
- `_build_execution_candidate_sets(...)`
- `select_execution_candidates(...)`
- `select_sparse_execution_candidates(...)`
- `_tiered_fallback_candidates(...)`

### `quant_system/research/scoring.py`

Verplaatsen:

- `_aggregate_profit_factor(...)`
- `_metric_map_from_row(...)`
- `_score_result(...)`
- `_annotate_combo_results(...)`
- equity/regime-score helpers

### `quant_system/research/exports.py`

Verplaatsen:

- `_export_results(...)`
- `_export_viability_autopsy(...)`
- deployment-row formatting helpers

### `quant_system/research/runner.py`

Verplaatsen:

- hoofd-orchestration van symbol research
- feature loading
- candidate execution
- ranking
- deployment export
- report generation

### `quant_system/research/splits.py`

Verplaatsen:

- train/validation/test split helpers
- walk-forward split helpers
- execution validation split helpers

### `quant_system/research/data_sources.py`

Verplaatsen:

- symbol resolution
- cache loading
- externe datasource-keuzes
- timeframe cache helpers

### `quant_system/research/optimization_hooks.py`

Verplaatsen:

- near-miss optimizer
- local optimizer
- autopsy improvements
- second-pass glue

### `quant_system/research/artifacts.py`

Verplaatsen:

- plot/export artifact naming
- trade artifact helpers

## Fase 2: `quant_system/app.py` verkleinen

Huidige bron:

- `quant_system/app.py`

Doel: app-orchestration opsplitsen in kleine modules.

### `quant_system/app/profile_run.py`

Verplaatsen:

- profile loop
- profile resolution
- orchestration per profile

### `quant_system/app/data_loading.py`

Verplaatsen:

- cached bars laden
- MT5 bars laden
- timeframe mapping
- history sizing

### `quant_system/app/reporting.py`

Verplaatsen:

- report writes
- AI summary integration
- agent registry/catalog export

### `quant_system/app/orchestration.py`

Verplaatsen:

- end-to-end flow:
  - data load
  - feature build
  - optimization
  - execution
  - evaluation
  - reporting

### `quant_system/app.py`

Eindstatus:

- alleen `main()`
- alleen delegatie

## Fase 3: agentmodules opsplitsen

### Forex

Huidige bron:

- `quant_system/agents/forex.py`

Nieuwe indeling:

- `quant_system/agents/forex/trend.py`
- `quant_system/agents/forex/breakout.py`
- `quant_system/agents/forex/reversion.py`
- `quant_system/agents/forex/event.py`

### US500

Huidige bron:

- `quant_system/agents/us500.py`

Nieuwe indeling:

- `quant_system/agents/us500/momentum.py`
- `quant_system/agents/us500/reversal.py`
- `quant_system/agents/us500/session.py`

### Crypto

Huidige bron:

- `quant_system/agents/crypto.py`

Nieuwe indeling:

- `quant_system/agents/crypto/trend.py`
- `quant_system/agents/crypto/breakout.py`
- `quant_system/agents/crypto/reversion.py`

### Stocks

Huidige bron:

- `quant_system/agents/stocks.py`

Nieuwe indeling:

- `quant_system/agents/stocks/momentum.py`
- `quant_system/agents/stocks/gap.py`
- `quant_system/agents/stocks/event.py`

## Fase 4: boundaries normaliseren

Regels:

- code buiten `research/` importeert geen private research-helpers
- code buiten `live/` importeert niet rechtstreeks uit `live/runtime.py`
- root scripts importeren alleen publieke subsystem-entrypoints
- tests gebruiken zoveel mogelijk publieke modules of bewust bedoelde helpers

## Fase 5: entrypoints opschonen

Root-entrypoints houden als dunne wrappers:

- `main.py`
- `main_symbol_research.py`
- `main_symbol_execute.py`
- `main_live_mt5.py`
- `main_live_loop.py`

Regel:

- root = thin wrapper
- echte logica = subsystemmodule
- `tools/` = operator/support

## Fase 6: navigatiedocumentatie toevoegen

Toevoegen:

- `docs/architecture_map.md`

Inhoud:

- waar research logic staat
- waar live runtime staat
- waar agent-definities staan
- welke entrypoint waarvoor bedoeld is

Status:

- `docs/architecture_map.md` bestaat nu en beschrijft de huidige Step 1 boundary-indeling

## Prioriteit

Start met deze volgorde:

1. `symbol_research.py`
2. `quant_system/app.py`
3. `agents/forex.py`

Dat zijn de grootste bronnen van complexiteit en navigatiefrictie.

## Commitvolgorde

1. `refactor: extract research viability and selection modules`
2. `refactor: extract research exports and runner modules`
3. `refactor: slim down quant_system app orchestration`
4. `refactor: split forex agents by strategy family`
5. `refactor: split us500 and crypto agents by strategy family`
6. `docs: add architecture map and module boundaries`

## Werkregels tijdens refactor

- eerst verplaatsen, daarna hernoemen, daarna herschrijven
- geen gedragswijziging zonder test
- na elke stap test-suite draaien
- geen nieuwe grote verzamelmodules maken
- één verantwoordelijkheid per module
- liefst geen file boven ongeveer 800-1200 regels zonder expliciete reden

## Validatiecommand

Na elke stap draaien:

```powershell
.\.venv\Scripts\python.exe tools\main_test_functional_suite.py
```

## Startpunt voor een volgende sessie

Als er maar één stap wordt opgepakt, begin dan met:

- `quant_system/symbol_research.py` opsplitsen naar:
  - `quant_system/research/catalog.py`
  - `quant_system/research/viability.py`
  - `quant_system/research/selection.py`
  - `quant_system/research/exports.py`
  - `quant_system/research/runner.py`

Dat geeft de grootste winst in begrijpelijkheid en maakt de rest van de refactor veel eenvoudiger.
