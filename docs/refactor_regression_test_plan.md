# Refactor Regression Test Plan

Date: 2026-04-25

## Purpose

This plan defines how to verify that the repository still behaves the same after Step 1 refactoring.

The goal is not to prove the refactor is "clean".
The goal is to prove that behavior did not unintentionally change while files, modules, and classes were being reorganized.

This plan is specifically for:

- Step 1 refactor work
- before the Blue Guardian research improvements in Step 2

That separation matters because Step 2 is expected to change behavior, while Step 1 should primarily preserve it.

## Testing Principles

1. Step 1 should preserve behavior unless a structural bug is being fixed deliberately.
2. Regressions must be checked at multiple layers:
   - unit logic
   - orchestration
   - artifact generation
   - live runtime decision behavior
3. We should compare outputs before and after refactor, not only rely on “tests still pass”.
4. Existing tests are the first guardrail, but not the only one.
5. A refactor is not complete if the project still “works” but outputs materially different deployment or research results without an intentional reason.

## What Must Stay Stable In Step 1

During Step 1 refactor, these behaviors should remain stable:

- symbol resolution
- venue / broker-family detection behavior
- cost profile behavior
- evaluation report logic
- interpreter regime logic
- research viability logic
- execution-set selection logic
- deployment artifact structure
- live runtime gate / action behavior
- MT5 integration routing behavior
- artifact/report output formats where not intentionally changed

## Regression Test Layers

## Layer 1: Existing Automated Test Suite

### Goal

Use the current test suite as the first safety net.

### Existing functional suite

The repo already has:

- [tools/main_test_functional_suite.py](C:/Users/liset/PycharmProjects/QuantGenerated/tools/main_test_functional_suite.py)

Run command:

```powershell
.\.venv\Scripts\python.exe tools\main_test_functional_suite.py
```

### Required baseline

Before Step 1 begins:

- run the full functional suite once
- record pass/fail status
- keep the output as the baseline result

After each milestone:

- rerun the same suite
- compare pass/fail status

### Core modules already covered

- evaluation
- optimization
- market data DuckDB behavior
- MT5 integration
- MT5 fill validation
- live deploy/runtime
- live TCA impact
- interpreter engines/app/reporting
- symbol research selection
- symbol research viability
- symbol research exports
- research end-to-end
- research artifacts
- threshold profiles
- research failure modes

## Layer 2: Expanded Step 1 Regression Suite

### Goal

Add a dedicated regression suite for refactor-sensitive behavior.

### Why

The existing suite is useful but not explicitly organized around architectural refactors.
We need a stable subset that is mandatory after every structural move.

### Proposed new runner

Add a new runner later in Step 1:

- `tools/main_test_refactor_regressions.py`

### Proposed minimum module set

- `quant_system.test_symbol_resolution`
- `quant_system.test_mt5_integration`
- `quant_system.test_evaluation_report`
- `quant_system.test_interpreter_engines`
- `quant_system.test_interpreter_app`
- `quant_system.test_live_deploy_runtime`
- `quant_system.test_symbol_research_selection`
- `quant_system.test_symbol_research_viability`
- `quant_system.test_symbol_research_exports`
- `quant_system.test_research_end_to_end`
- `quant_system.test_research_artifacts`
- `quant_system.test_research_failure_modes`
- `quant_system.test_symbol_research_regressions`

### Usage intent

This suite should be run:

- after each major file split,
- after venue-layer introduction,
- after runtime decomposition,
- and before merging any large refactor slice.

## Layer 3: Snapshot Comparison Tests

### Goal

Detect silent behavior changes even when tests still pass.

### Method

Before Step 1:

- generate baseline outputs for a small controlled set of runs

After each milestone:

- regenerate the same outputs
- diff them against baseline

### Recommended baseline outputs

#### 1. Symbol research outputs

Generate and preserve baseline artifacts for a small symbol set:

- `EURUSD`
- `XAUUSD`
- `JP225`

Preserve:

- `artifacts/research/<symbol>/reports/symbol_research.txt`
- `artifacts/research/<symbol>/reports/symbol_research.csv`
- `artifacts/research/<symbol>/reports/viability_autopsy.txt`
- `artifacts/deploy/<symbol>/live.json`

### Comparison rule

Differences are acceptable only when:

- timestamps differ,
- ordering changes without semantic impact,
- or a change is expected and documented.

Differences are not acceptable when:

- deployment status changes unexpectedly
- selected strategy changes unexpectedly
- viability tier distribution shifts unexpectedly
- output fields disappear

#### 2. Interpreter output snapshots

Preserve interpreter report outputs for representative symbols or fixture-driven scenarios.

Compare:

- allowed archetypes
- blocked archetypes
- directional bias
- risk posture
- explanation structure

#### 3. Live deployment output snapshots

For representative deployments, preserve:

- strategy list
- policy summary
- allowed / blocked regimes
- execution overrides
- symbol status

## Layer 4: Contract Tests For Refactor Boundaries

### Goal

Protect public interfaces while internals move.

### Interfaces to freeze during Step 1

#### 1. Entry scripts

These should keep working:

- [main.py](C:/Users/liset/PycharmProjects/QuantGenerated/main.py)
- [main_symbol_research.py](C:/Users/liset/PycharmProjects/QuantGenerated/main_symbol_research.py)
- [main_symbol_execute.py](C:/Users/liset/PycharmProjects/QuantGenerated/main_symbol_execute.py)
- [main_live_mt5.py](C:/Users/liset/PycharmProjects/QuantGenerated/main_live_mt5.py)
- [main_live_loop.py](C:/Users/liset/PycharmProjects/QuantGenerated/main_live_loop.py)

#### 2. Artifact locations

These should remain stable during Step 1:

- `artifacts/research/<symbol>/reports/...`
- `artifacts/research/<symbol>/plots/...`
- `artifacts/deploy/<symbol>/live.json`
- `artifacts/system/reports/...`

#### 3. Deployment JSON contract

`live.json` should preserve core keys:

- `profile_name`
- `symbol`
- `data_symbol`
- `broker_symbol`
- `research_run_id`
- `execution_set_id`
- `execution_validation_summary`
- `symbol_status`
- `strategies`

#### 4. Research report contract

`symbol_research.txt` and `symbol_research.csv` should preserve core semantic sections and fields even if internal generation code moves.

### Suggested tests

Add explicit contract tests for:

- deployment artifact schema
- research CSV required columns
- research TXT required sections
- interpreter state required fields

## Layer 5: Refactor Milestone Gates

### Goal

Define what must pass before moving to the next refactor milestone.

### Gate A: `venues/` foundation introduced

Must pass:

- full functional suite
- symbol resolution tests
- MT5 integration tests
- no output regression in deployment JSON for representative symbols

### Gate B: `symbol_research.py` partially split

Must pass:

- research selection tests
- research viability tests
- research exports tests
- research end-to-end tests
- baseline symbol research snapshots unchanged

### Gate C: `live/runtime.py` split

Must pass:

- live deploy/runtime tests
- interpreter tests
- live TCA tests
- deployment JSON snapshots unchanged

### Gate D: agent packages split

Must pass:

- research end-to-end tests
- live deploy/runtime tests
- factory/import compatibility checks

### Gate E: docs and final compatibility cleanup

Must pass:

- full functional suite
- snapshot comparisons for representative symbols
- manual smoke runs of main entrypoints

## Layer 6: Manual Smoke Tests

### Goal

Catch issues that unit tests miss.

### Required manual smoke checks after major milestones

#### 1. Symbol research smoke test

Run:

```powershell
.\.venv\Scripts\python.exe main_symbol_research.py EURUSD
```

Check:

- command completes
- report files are written
- deployment JSON is generated or updated
- output is structurally normal

#### 2. Execution-set visibility test

Run:

```powershell
.\.venv\Scripts\python.exe tools\main_symbol_execution_set.py
```

Check:

- output still loads
- execution sets are readable

#### 3. Live health report generation test

Run the relevant health/report workflow and check:

- `live_health_report.txt`
- `trade_cost_analysis.txt`
- `tca_impact_report.txt`

still generate and remain readable.

#### 4. MT5 config smoke test

Use MT5 integration tests and one manual configuration check to ensure venue refactor did not break:

- terminal path handling
- broker-family detection
- symbol mapping

## Layer 7: Baseline Artifact Archive

### Goal

Keep a stable before/after comparison set for Step 1.

### Recommendation

Before refactor starts, archive:

- a baseline test run result
- representative research artifacts
- representative deploy artifacts
- interpreter outputs

Suggested location:

- `artifacts/system/baselines/refactor_step1/`

Suggested contents:

- `functional_suite_baseline.txt`
- `eurusd_symbol_research.txt`
- `eurusd_symbol_research.csv`
- `eurusd_live.json`
- `xauusd_symbol_research.txt`
- `xauusd_live.json`
- `jp225_symbol_research.txt`
- `jp225_live.json`

These do not need to be committed forever, but they should exist during the refactor program.

## Layer 8: Failure Handling Rules

### If a test fails

- stop the current refactor slice
- identify whether the failure is:
  - import/move-only breakage
  - contract/schema breakage
  - semantic behavior change

### If snapshots differ

- classify the difference
- document whether it is:
  - expected and benign
  - expected but needs follow-up
  - unintended regression

No milestone should close with unexplained output drift.

## Proposed New Test Additions

These are worth adding during Step 1:

1. Deployment schema regression test
   - validates required keys and basic structure of `live.json`

2. Research report schema regression test
   - validates required columns in `symbol_research.csv`
   - validates required sections in `symbol_research.txt`

3. Venue registry regression test
   - once `venues/` exists, verifies venue resolution is stable

4. Entry script smoke runner
   - lightweight script to run critical entrypoints in a safe test mode

## Practical Run Order During Step 1

For each major PR or milestone:

1. Run the dedicated refactor regression suite
2. Run the full functional suite
3. Compare baseline snapshots
4. Run manual smoke checks
5. Only then continue

## Definition Of Done

The Step 1 refactor is regression-safe when:

- all required automated suites pass,
- representative outputs match baseline or have documented intended differences,
- entrypoints still work,
- artifact contracts remain stable,
- and no unexplained behavior drift appears in research, deployment, interpreter, or live runtime layers.

## Immediate Next Action

Before the first structural code move:

1. run and save the current functional suite output
2. archive baseline research/deploy artifacts for `EURUSD`, `XAUUSD`, and `JP225`
3. add the dedicated refactor regression runner
