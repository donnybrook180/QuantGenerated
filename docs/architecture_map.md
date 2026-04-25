# Architecture Map

This document is the shortest path to the current Step 1 repo layout.

## Root Entry Points

The repo-root scripts are thin wrappers:

- `main.py`
  - delegates to `quant_system.app`
- `main_symbol_research.py`
  - delegates to `quant_system.research.cli`
- `main_symbol_execute.py`
  - delegates to `quant_system.research.app`
- `main_live_mt5.py`
  - delegates to `quant_system.live.app`
- `main_live_loop.py`
  - delegates to `quant_system.live.loop_app`

Rule of thumb:

- root scripts are for CLI stability
- subsystem modules own the real logic

## Research

Primary home: `quant_system/research/`

Use these files first:

- `cli.py`
  - symbol-research CLI entrypoint
- `app.py`
  - symbol execute / app-facing research entry helpers
- `runner.py`
  - research execution flow
- `orchestration.py`
  - broader research coordination
- `selection.py`
  - execution-set shaping and candidate selection
- `viability.py`
  - promotion and viability gates
- `exports.py`
  - CSV/TXT/deployment artifact writing
- `data_sources.py`
  - cache/broker/source resolution
- `splits.py`
  - train/validation/test split helpers
- `reporting.py`
  - text reporting helpers

Compatibility note:

- `quant_system/symbol_research.py` still exists as a compatibility facade for legacy imports

## Live

Primary home: `quant_system/live/`

Use these files first:

- `app.py`
  - single-run live app helpers
- `loop_app.py`
  - polling loop orchestration and live-cycle reporting
- `runtime.py`
  - top-level live executor coordination
- `strategy_eval.py`
  - per-strategy signal evaluation
- `interpreter_gate.py`
  - interpreter/regime gating
- `allocation.py`
  - symbol exposure allocation
- `order_sizing.py`
  - size and risk-budget calculations
- `reconcile.py`
  - desired vs current position reconciliation
- `weekend_policy.py`
  - weekend flatten / block policy
- `deploy.py`
  - `live.json` loading and shaping
- `journal.py`
  - journals and incidents

## Profile App Flow

Primary home:

- `quant_system/profile_app.py`
- `quant_system/profile_data.py`
- `quant_system/profile_runtime.py`
- `quant_system/profile_reporting.py`

Compatibility note:

- `quant_system/app.py` remains a thin facade for existing imports

## Venues

Primary home: `quant_system/venues/`

Key files:

- `models.py`
  - shared venue contracts
- `registry.py`
  - venue resolution and profile lookup
- `generic/`
- `blue_guardian/`
- `ftmo/`
- `fundednext/`

Use this layer for:

- venue identity
- fill routing defaults
- venue-specific rules
- venue-specific cost or symbol behavior

## Agents

Primary home: `quant_system/agents/`

Stable public import modules remain:

- `crypto.py`
- `forex.py`
- `us500.py`
- `xauusd.py`

They now delegate to narrower internal packages:

- `crypto_setups/`
- `forex_setups/`
- `us500_setups/`
- `xauusd_setups/`

Other markets that still use single files today:

- `ger40.py`
- `us100.py`
- `stocks.py`
- `strategies.py`

## Artifact Flow

Research writes mainly to:

- `artifacts/research/<symbol>/...`
- `artifacts/deploy/<symbol>/live.json`

Live writes mainly to:

- `artifacts/live/<symbol>/...`
- `artifacts/system/reports/...`

Profile runs write mainly to:

- `artifacts/profiles/<profile>/...`

## Navigation Shortcuts

If you want to:

- run symbol research: start at `main_symbol_research.py`, then `quant_system/research/cli.py`
- inspect candidate selection: go to `quant_system/research/selection.py`
- inspect viability rules: go to `quant_system/research/viability.py`
- inspect live one-shot execution: go to `quant_system/live/app.py`
- inspect live loop behavior: go to `quant_system/live/loop_app.py`
- inspect venue routing: go to `quant_system/venues/registry.py`
- inspect profile orchestration: go to `quant_system/profile_app.py`
