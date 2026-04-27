Date: 2026-04-27

## Goal

Use swap only to make simulated and reported net results more realistic.

Do not add:

- swap-specific selection penalties
- extra caution or rejection reasons for swap
- extra ranking heuristics based on swap

Swap should flow through the normal trade PnL, expectancy, equity, and drawdown metrics. Candidate selection should then change automatically because the underlying net results changed.

## Scope

First scope:

1. research/backtest trade PnL
2. research summary metrics
3. research selection using those net metrics
4. reporting of gross-vs-net swap impact

Not in first scope:

- live rollover policies
- forced pre-rollover exits
- swap-specific live blocks
- extra strategy penalties for holding overnight

## Design

### 1. Broker funding remains the source of truth

When broker funding context is available, use:

- `broker_swap_long`
- `broker_swap_short`
- `broker_swap_rollover3days`

Fallback only when broker swap is unavailable:

- `execution.overnight_cost_per_lot_day`

### 2. Apply swap directly inside simulated trade outcomes

For simulated trades that cross overnight boundaries:

- compute the number of charged rollover dates between entry and exit
- apply long or short swap based on the open position side
- apply the triple-rollover multiplier on the broker rollover weekday
- book the signed swap directly into trade PnL

This means:

- negative swap reduces net PnL
- positive swap increases net PnL

### 3. Selection logic stays simple

Selection must not add extra swap reasons.

The selection layer should work off the already-net metrics:

- `realized_pnl`
- `expectancy`
- `profit_factor`
- `equity_quality_score`
- Monte Carlo inputs derived from closed-trade PnL

If a strategy degrades because of swap, that should happen naturally through those metrics.

### 4. Reporting stays informative

Reports may still show:

- estimated/applied swap drag
- gross-vs-net delta
- swap-adjusted expectancy

But that information is explanatory only, not a separate gating mechanism.

## Implementation Phases

### Phase 1

- remove explicit swap-based viability reasons from research selection
- apply signed broker swap in `SimulatedBroker`
- thread broker funding context into research engine construction so the broker sees the active swap values
- add regression tests for overnight long/short trades and triple-rollover handling

### Phase 2

- align walk-forward and optimization simulations with the same swap-aware broker wiring
- add compact gross-vs-net reporting fields where missing

### Phase 3

- extend the same netting model into live reporting so research and live performance speak the same net language

## Definition Of Done For Phase 1

- overnight trades in research close with net PnL that includes broker swap
- positive carry can improve net PnL
- negative carry can reduce net PnL
- selection no longer adds swap-specific fail/caution reasons
- existing selection changes only because net metrics changed
