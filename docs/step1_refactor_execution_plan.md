# Step 1 Refactor Execution Plan

Date: 2026-04-25

## Purpose

This document turns Step 1 of the two-step program into an executable refactor plan.

Step 1 goal:

- make the project easier to read,
- easier to maintain,
- and structurally ready to handle prop firms independently.

This plan is intentionally file-by-file and migration-oriented.

## Refactor Rules

During Step 1:

- keep behavior stable unless a change is required to preserve architecture,
- prefer moves and decomposition over logic redesign,
- avoid mixing Blue Guardian-specific research improvements into this step,
- keep entrypoints working while internals move,
- and preserve artifact/report compatibility where possible.

## Target Structural Additions

New high-level areas to establish during Step 1:

```text
quant_system/
  venues/
    __init__.py
    models.py
    registry.py
    generic/
    blue_guardian/
    ftmo/
    fundednext/
```

And stronger separation inside:

- `research/`
- `live/`
- `core/`
- `agents/`

## Workstream A: Venue Boundary

### Objective

Create a first-class place for prop-firm-specific behavior.

### New files

- `quant_system/venues/__init__.py`
- `quant_system/venues/models.py`
- `quant_system/venues/registry.py`
- `quant_system/venues/generic/__init__.py`
- `quant_system/venues/generic/profile.py`
- `quant_system/venues/generic/rules.py`
- `quant_system/venues/generic/costs.py`
- `quant_system/venues/generic/symbols.py`
- `quant_system/venues/blue_guardian/__init__.py`
- `quant_system/venues/blue_guardian/profile.py`
- `quant_system/venues/blue_guardian/rules.py`
- `quant_system/venues/blue_guardian/costs.py`
- `quant_system/venues/blue_guardian/symbols.py`
- `quant_system/venues/ftmo/__init__.py`
- `quant_system/venues/ftmo/profile.py`
- `quant_system/venues/ftmo/rules.py`
- `quant_system/venues/ftmo/costs.py`
- `quant_system/venues/ftmo/symbols.py`
- `quant_system/venues/fundednext/__init__.py`
- `quant_system/venues/fundednext/profile.py`
- `quant_system/venues/fundednext/rules.py`
- `quant_system/venues/fundednext/costs.py`
- `quant_system/venues/fundednext/symbols.py`

### Initial responsibility

`models.py`
- shared venue dataclasses
- venue identity
- venue rule/cost/symbol contracts

`registry.py`
- resolve venue from config
- expose venue profile object

`<venue>/profile.py`
- compose venue-specific rules, symbol mapping, costs

`<venue>/rules.py`
- prop-firm restrictions and behavior flags

`<venue>/costs.py`
- venue-level cost defaults

`<venue>/symbols.py`
- symbol naming and mapping behavior

### Existing files to update

- [quant_system/config.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/config.py)
- [quant_system/costs.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/costs.py)
- [quant_system/integrations/mt5.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/integrations/mt5.py)

### Migration intent

Do not delete existing broker-family logic immediately.
First:

- add venue resolution in parallel,
- route new calls through venue registry,
- then shrink old inline venue logic.

## Workstream B: Split `symbol_research.py`

### Objective

Break the monolith into readable research modules.

### Source file

- [quant_system/symbol_research.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/symbol_research.py)

### Target files

- `quant_system/research/catalog.py`
- `quant_system/research/viability.py`
- `quant_system/research/selection.py`
- `quant_system/research/scoring.py`
- `quant_system/research/exports.py`
- `quant_system/research/splits.py`
- `quant_system/research/data_sources.py`
- `quant_system/research/reporting.py`
- `quant_system/research/runner.py`

### Move plan

`catalog.py`
- candidate specs
- family definitions
- variant builders
- sweep generators
- combination generators

`viability.py`
- viability thresholds
- sparse candidate checks
- promotion-tier logic
- candidate rejection reasons

`selection.py`
- execution candidate rows
- candidate selection score logic
- combo validity
- execution-set selection

`scoring.py`
- metric aggregation
- score calculators
- helper ranking metrics

`exports.py`
- CSV/TXT export logic
- deployment row shaping
- execution-set export helpers

`splits.py`
- train/validation/test split logic
- walk-forward window helpers

`data_sources.py`
- symbol resolution
- source-preference handling
- broker/cache selection logic

`reporting.py`
- human-readable symbol research reports
- viability autopsy report generation

`runner.py`
- orchestration only
- candidate evaluation loop
- ranking
- report/export/deployment handoff

### Existing files to update

- [quant_system/research/app.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/research/app.py)
- [main_symbol_research.py](C:/Users/liset/PycharmProjects/QuantGenerated/main_symbol_research.py)
- tests touching research flow

### Migration intent

Phase the split:

1. extract pure helpers first
2. update imports
3. move orchestration last
4. keep `symbol_research.py` as a compatibility facade temporarily if needed

## Workstream C: Clarify App / Entry Boundaries

### Objective

Ensure root scripts orchestrate, not own business logic.

### Files to inspect and simplify

- [main.py](C:/Users/liset/PycharmProjects/QuantGenerated/main.py)
- [main_symbol_research.py](C:/Users/liset/PycharmProjects/QuantGenerated/main_symbol_research.py)
- [main_symbol_execute.py](C:/Users/liset/PycharmProjects/QuantGenerated/main_symbol_execute.py)
- [main_live_mt5.py](C:/Users/liset/PycharmProjects/QuantGenerated/main_live_mt5.py)
- [main_live_loop.py](C:/Users/liset/PycharmProjects/QuantGenerated/main_live_loop.py)
- [quant_system/app.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/app.py)

### Target direction

Move orchestration internals into:

- `quant_system/app/orchestration.py`
- `quant_system/app/profile_run.py`
- `quant_system/app/reporting.py`
- `quant_system/app/data_loading.py`

### Migration intent

Keep current CLI signatures stable.
Refactor internals only.

## Workstream D: Split Live Runtime

### Objective

Reduce width of live runtime and make it easier to reason about.

### Source file

- [quant_system/live/runtime.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/live/runtime.py)

### Target files

- `quant_system/live/runtime.py`
  - keep only top-level orchestration
- `quant_system/live/strategy_eval.py`
  - per-strategy evaluation
- `quant_system/live/interpreter_gate.py`
  - interpreter and regime gate logic
- `quant_system/live/allocation.py`
  - allocation and portfolio-weight logic
- `quant_system/live/reconcile.py`
  - desired-vs-current position reconciliation
- `quant_system/live/weekend_policy.py`
  - weekend entry/flatten policy
- `quant_system/live/order_sizing.py`
  - risk-budget and quantity sizing

### Move plan

From `runtime.py`, isolate:

- interpreter block reason logic
- strategy evaluation flow
- allocation scoring
- netting/position reconciliation
- order sizing calculations
- weekend handling

### Existing related files to revisit

- [quant_system/live/deploy.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/live/deploy.py)
- [quant_system/live/health.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/live/health.py)
- [quant_system/live/models.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/live/models.py)

## Workstream E: Reduce Agent Module Width

### Objective

Stop large agent modules from becoming another monolith layer.

### Current targets

- [quant_system/agents/forex.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/agents/forex.py)
- [quant_system/agents/crypto.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/agents/crypto.py)
- [quant_system/agents/us500.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/agents/us500.py)
- [quant_system/agents/xauusd.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/agents/xauusd.py)

### Target structure

```text
quant_system/agents/
  forex/
    __init__.py
    breakout.py
    reversion.py
    trend.py
  crypto/
    __init__.py
    breakout.py
    reversion.py
    trend.py
  us500/
    __init__.py
    momentum.py
    reversal.py
    session.py
  xauusd/
    __init__.py
    breakout.py
    reclaim.py
    trend.py
```

### Migration intent

Keep the factory stable:

- [quant_system/agents/factory.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/agents/factory.py)

Use package `__init__.py` files to preserve import compatibility during transition.

## Workstream F: Move Shared Logic To Better Homes

### Objective

Reduce hidden cross-layer dependencies.

### Files to review

- [quant_system/costs.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/costs.py)
- [quant_system/regime.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/regime.py)
- [quant_system/live_support.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/live_support.py)
- [quant_system/execution_tuning.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/execution_tuning.py)

### Target direction

Move:

- venue-specific cost defaults into `venues/*/costs.py`
- venue-specific restrictions into `venues/*/rules.py`
- symbol mapping into `venues/*/symbols.py`
- generic shared primitives into `core/`

## Workstream G: Documentation Cleanup

### Objective

Make the repo discoverable after the refactor.

### Files to update

- [README.md](C:/Users/liset/PycharmProjects/QuantGenerated/README.md)
- [docs/refactor_plan.md](C:/Users/liset/PycharmProjects/QuantGenerated/docs/refactor_plan.md)
- [docs/report_map.md](C:/Users/liset/PycharmProjects/QuantGenerated/docs/report_map.md)
- [docs/live_operations_manual.md](C:/Users/liset/PycharmProjects/QuantGenerated/docs/live_operations_manual.md)
- [docs/prop_firm_launch_checklist.md](C:/Users/liset/PycharmProjects/QuantGenerated/docs/prop_firm_launch_checklist.md)

### New docs to keep

- [docs/two_step_refactor_and_blue_guardian_plan.md](C:/Users/liset/PycharmProjects/QuantGenerated/docs/two_step_refactor_and_blue_guardian_plan.md)
- [docs/blue_guardian_research_improvement_plan.md](C:/Users/liset/PycharmProjects/QuantGenerated/docs/blue_guardian_research_improvement_plan.md)
- this document

## Safe Migration Order

### Phase 1

Create foundations first:

1. add `venues/` package
2. add new research module files
3. add new live helper module files

No major deletions yet.

### Phase 2

Move low-risk pure helpers:

1. extract research helpers from `symbol_research.py`
2. extract interpreter/runtime helper functions
3. extract venue resolution helpers

### Phase 3

Move orchestration:

1. shrink `symbol_research.py`
2. shrink `live/runtime.py`
3. shrink `quant_system/app.py`

### Phase 4

Update imports and tests:

1. repair imports
2. run targeted tests
3. update docs

### Phase 5

Compatibility cleanup:

1. remove dead wrappers only after new modules are stable
2. preserve CLI behavior
3. preserve artifact locations unless intentionally changed

## Refactor Milestones

### Milestone 1

Venue foundation exists and config can resolve a venue profile.

### Milestone 2

`symbol_research.py` is reduced to a thin facade or retired from main logic.

### Milestone 3

`live/runtime.py` becomes a coordinator, not a giant mixed logic file.

### Milestone 4

Large agent modules are split into packages.

### Milestone 5

Docs reflect the new module layout and navigation is improved.

## Minimal Test Strategy During Refactor

After each milestone, run targeted validation:

- symbol research tests
- live deploy/runtime tests
- interpreter tests
- evaluation report tests

Primary targets:

- [quant_system/test_live_deploy_runtime.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/test_live_deploy_runtime.py)
- [quant_system/test_interpreter_app.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/test_interpreter_app.py)
- [quant_system/test_interpreter_engines.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/test_interpreter_engines.py)
- [quant_system/test_research_end_to_end.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/test_research_end_to_end.py)
- [quant_system/test_symbol_research_exports.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/test_symbol_research_exports.py)
- [quant_system/test_evaluation_report.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/test_evaluation_report.py)

## Immediate Next Coding Order

1. Create `quant_system/venues/` foundation
2. Extract venue-related logic from `config.py`, `costs.py`, and MT5 broker-family handling
3. Split `symbol_research.py` into `catalog.py`, `viability.py`, `selection.py`, `exports.py`, `runner.py`
4. Split `live/runtime.py` into evaluator/gate/allocation/reconcile modules
5. Split broad agent modules into packages
6. Update docs and tests

## Done Condition For Step 1

Step 1 is complete when:

- the repo is easier to navigate,
- large files and classes are meaningfully reduced,
- prop firms have an explicit architectural home,
- research and live layers are cleaner,
- and Step 2 can be implemented without deepening the current mess.
