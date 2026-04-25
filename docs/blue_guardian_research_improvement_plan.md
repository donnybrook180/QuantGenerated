# Blue Guardian Research Improvement Plan

Date: 2026-04-25

## Goal

Improve symbol research so Blue Guardian-specific conclusions are based on:

- Blue Guardian MT5 broker data,
- prop-firm execution reality,
- funding / swap drag,
- slippage and spread stress,
- regime fit,
- and Blue Guardian rule compatibility.

This plan exists because the recent `EURUSD` rerun showed that a symbol previously accepted from cached research can become `research_only` when rerun on Blue Guardian MT5 data.

## Core Problem

The current research stack is strong at finding candidate-level edge, but it is still too optimistic for prop-firm deployment when:

- the broker feed differs from cache,
- the best candidate only works in a narrow regime,
- the strategy is sensitive to swap or spread,
- the strategy depends on breakout conditions that the live interpreter often blocks,
- or execution realism is not stress-tested hard enough before live promotion.

## Design Principles

1. Blue Guardian must be treated as its own venue.
2. Research edge and prop-firm viability must be evaluated separately.
3. No candidate should be promoted only because headline PnL or PF looks good.
4. Live promotion should require evidence of robustness under broker-specific conditions.
5. Research output must explain not only what won, but why a candidate is or is not deployable on Blue Guardian.

## Scope

Initial focus:

- `EURUSD`
- `XAUUSD`
- `JP225`
- `EU50`
- `US500`
- `BTC`
- `ETH`

Priority order for implementation and reruns:

1. `EURUSD`
2. `XAUUSD`
3. `JP225`
4. `EU50`
5. `US500`
6. `BTC`
7. `ETH`

## Phase 1: Data Isolation and Broker Sanity

### Objective

Ensure Blue Guardian research is built from Blue Guardian data, not polluted cache history from another venue.

### Actions

- Use a dedicated DB:
  - `AI_EXPERIMENT_DB_PATH=quant_data_blue_guardian.duckdb`
- Keep `PROP_BROKER=blue_guardian`
- Keep `MARKET_DATA_FETCH_POLICY=network_first`
- Keep a dedicated Blue Guardian MT5 terminal path
- Do not reuse mixed fill or research history from other prop firms

### Code / config touchpoints

- [quant_system/config.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/config.py)
- [docs/prop_firm_launch_checklist.md](C:/Users/liset/PycharmProjects/QuantGenerated/docs/prop_firm_launch_checklist.md)
- [docs/live_operations_manual.md](C:/Users/liset/PycharmProjects/QuantGenerated/docs/live_operations_manual.md)

### Deliverable

A Blue Guardian-only research/runtime context with clean storage and reproducible broker-based reruns.

## Phase 2: Broker Data Quality Layer

### Objective

Validate whether Blue Guardian MT5 data is usable and stable enough before candidate scoring.

### Actions

For each priority symbol, record:

- MT5 symbol resolution result
- available history depth
- timeframe completeness
- missing bars / suspicious gaps
- session alignment
- contract / point / spread snapshot
- symbol naming consistency between research and live deployment

### Required output

Add a broker data sanity section to symbol research output:

- `broker_data_source`
- `broker_symbol`
- `history_bars_loaded`
- `history_window_start`
- `history_window_end`
- `missing_bar_warnings`
- `session_alignment_notes`
- `contract_spec_notes`

### Suggested implementation points

- [quant_system/integrations/mt5.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/integrations/mt5.py)
- [quant_system/symbol_research.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/symbol_research.py)

## Phase 3: Split Research into Edge vs Prop-Firm Viability

### Objective

Separate raw strategy discovery from prop-firm deployment fitness.

### Current issue

A candidate can look attractive on:

- realized PnL
- profit factor
- expectancy

while still being poor for Blue Guardian because of:

- narrow regime dependence,
- thin validation/test evidence,
- execution fragility,
- or swap drag.

### New model

Introduce two layers:

1. `signal_quality`
   - pure strategy merit on broker data

2. `prop_viability`
   - Blue Guardian deployability filter

### New output fields

- `signal_quality_score`
- `prop_viability_score`
- `prop_viability_pass`
- `prop_viability_reasons`

### Suggested implementation points

- [quant_system/symbol_research.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/symbol_research.py)
- [quant_system/live/deploy.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/live/deploy.py)

## Phase 4: Funding / Swap Drag Integration

### Objective

Explicitly penalize strategies whose edge is too dependent on holding through negative carry.

### Why

The new `EURUSD` MT5 run already exposes broker-specific funding information. That should affect viability, especially for:

- `EURUSD`
- `XAUUSD`
- swing-style trades

### Actions

For each candidate, compute:

- average holding time
- long-side and short-side carry preference
- estimated swap drag for observed holding profile
- swap-adjusted expectancy

### New metrics

- `avg_hold_hours`
- `swap_long`
- `swap_short`
- `carry_preferred_side`
- `estimated_swap_drag_total`
- `estimated_swap_drag_per_trade`
- `swap_adjusted_expectancy`

### Viability rules

Down-rank or reject candidates when:

- they systematically hold the expensive side,
- and their edge disappears after estimated funding drag.

### Suggested implementation points

- [quant_system/costs.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/costs.py)
- [quant_system/integrations/mt5.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/integrations/mt5.py)
- [quant_system/symbol_research.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/symbol_research.py)

## Phase 5: Slippage / Spread Stress Testing

### Objective

Make candidate acceptance robust to worse-than-ideal Blue Guardian execution.

### Actions

For each candidate, rerun viability scoring under multiple execution stress cases:

- base
- base + mild slippage stress
- base + medium slippage stress
- base + spread widening

### Proposed scenarios

- `shortfall +0.25 bps`
- `shortfall +0.50 bps`
- `shortfall +1.00 bps`
- broker spread x `1.25`
- broker spread x `1.50`

Exact levels can be symbol-class specific:

- forex: tighter increments
- indices/metals: spread-based stress
- crypto: wider stress bands

### New metrics

- `stress_expectancy_mild`
- `stress_expectancy_medium`
- `stress_expectancy_harsh`
- `stress_pf_mild`
- `stress_pf_medium`
- `stress_pf_harsh`
- `stress_survival_score`

### Acceptance rule

No live promotion unless the candidate remains viable under at least mild-to-medium stress.

### Suggested implementation points

- [quant_system/costs.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/costs.py)
- [quant_system/tca.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/tca.py)
- [quant_system/symbol_research.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/symbol_research.py)

## Phase 6: Blue Guardian Rule Compatibility

### Objective

Avoid promoting candidates that are likely to conflict with Blue Guardian restrictions even if they backtest well.

### Actions

Add prop-rule fit checks for:

- excessive news sensitivity
- very short holding periods that resemble prohibited styles
- trade clustering around restricted event windows
- dependence on execution speed or extremely small targets

### New metrics

- `prop_fit_score`
- `news_window_trade_share`
- `sub_short_hold_share`
- `micro_target_risk_flag`
- `execution_dependency_flag`

### Rule logic

Candidates should be marked:

- `pass`
- `caution`
- `fail`

with explicit reasons in reports.

### Suggested implementation points

- [quant_system/symbol_research.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/symbol_research.py)
- [quant_system/interpreter/features.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/interpreter/features.py)
- [artifacts/system/data/macro_calendar.csv](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/system/data/macro_calendar.csv)

## Phase 7: Regime Breadth and Live Interpreter Fit

### Objective

Reduce the mismatch between research winners and what the live interpreter will actually allow.

### Current issue

`EURUSD` previously promoted a breakout strategy, while the live interpreter often classifies current market structure as:

- `orderly_range`
- `range_rotation`

which blocks breakout and prefers mean reversion.

### Actions

Add a live-compatibility overlay:

- compare candidate family to likely interpreter-allowed archetypes
- down-rank candidates that only fit rarely-allowed live structures
- favor symbols with at least one viable strategy for common live regimes

### New metrics

- `interpreter_fit_score`
- `common_live_regime_fit`
- `blocked_by_interpreter_risk`

### Symbol-specific implications

- `EURUSD`: add more mean reversion / range rotation candidates
- `EU50`: test shorter-hold setups, but stress spreads harder
- `XAUUSD`: keep trend/expression families, but include swap drag and execution stress
- `JP225`: extra emphasis on session consistency and fill realism

### Suggested implementation points

- [quant_system/interpreter/engines.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/interpreter/engines.py)
- [quant_system/live/runtime.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/live/runtime.py)
- [quant_system/symbol_research.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/symbol_research.py)

## Phase 8: Reporting Improvements

### Objective

Make Blue Guardian research results actionable instead of forcing manual inference from raw candidate lists.

### New required report sections

Each symbol research report should include:

- `broker_data_summary`
- `swap_drag_summary`
- `execution_stress_summary`
- `prop_fit_summary`
- `interpreter_fit_summary`
- `why_promoted_for_blue_guardian`
- `why_rejected_for_blue_guardian`

### Deployment artifact expectations

Live deployment artifacts should expose:

- venue basis: `blue_guardian_mt5`
- viability label: `pass/caution/fail`
- top rejection / caution reasons

## Implementation Order

### Step 1

Improve `EURUSD` first:

- add mean reversion / range candidates
- add interpreter-fit scoring
- add swap/slippage stress output

### Step 2

Implement broker data sanity reporting for:

- `EURUSD`
- `XAUUSD`
- `JP225`

### Step 3

Add viability overlay and stress testing to all priority live symbols.

### Step 4

Rerun Blue Guardian research in this order:

1. `EURUSD`
2. `XAUUSD`
3. `JP225`
4. `EU50`
5. `US500`
6. `BTC`
7. `ETH`

### Step 5

After each rerun:

- inspect `symbol_research.txt`
- inspect `viability_autopsy.txt`
- inspect new `live.json`
- compare `prop_viability_score`
- compare `interpreter_fit_score`

## Definition of Success

This plan succeeds when:

- Blue Guardian research no longer reuses misleading cross-venue assumptions
- live promotion is based on robustness, not just headline PF/PnL
- research and live interpreter are directionally aligned
- swap / spread / slippage sensitivity is visible before deployment
- and live symbols are selected because they fit Blue Guardian specifically, not because they once worked well on cached data

## Immediate Next Build Tasks

1. Add Blue Guardian viability fields to candidate scoring in `quant_system/symbol_research.py`.
2. Add swap-drag estimation using MT5 funding data.
3. Add execution stress scenarios per symbol class.
4. Add interpreter-fit scoring against common live regimes.
5. Expand `EURUSD` candidate families toward mean reversion / range rotation compatibility.
