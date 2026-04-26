# Venue Drawdown Implementation Plan

Date: 2026-04-26

## Goal

Model prop-firm risk rules per venue, with drawdown enforcement as the first priority, so research, evaluation, and live trading do not rely on one shared global drawdown policy.

## Why

Current repo state:

- broker credentials, deployments, and live artifacts are venue-aware
- prop-firm risk rules are not yet venue-aware
- drawdown logic still falls back to global env settings in most places

This is risky because different prop firms use different loss models:

- static max loss
- daily loss based on start-of-day balance
- daily loss based on higher of balance/equity at reset
- trailing loss from a high-water mark

## Priority

First priority:

1. daily drawdown
2. total drawdown
3. drawdown reference basis
4. reset timing
5. lockout behavior

Later:

- news restrictions
- weekend rules
- minimum trading days
- payout restrictions
- consistency rules

## Implementation Phases

### Phase 1: Rule Schema

Extend venue rule modeling so each venue can define:

- daily drawdown limit percent
- total drawdown limit percent
- daily reference basis
- total reference basis
- reset timezone
- reset hour
- minimum trading days
- profit target percent
- lockout mode

Reference bases to support first:

- `starting_balance`
- `starting_equity`
- `day_start_balance`
- `day_start_equity`
- `day_start_highest_balance_or_equity`
- `peak_balance`
- `peak_equity`

### Phase 2: Venue Defaults

Define explicit venue defaults for:

- FTMO
- FundedNext
- Blue Guardian
- generic fallback

Important:

- these defaults are venue-level baselines
- account-model-specific overrides may still be needed later
- if a firm has multiple challenge models, the default should be conservative until sub-model selection exists

### Phase 3: Risk Engine

Upgrade `RiskManager` so it can:

- load venue rules
- track start-of-day balance and equity
- track peak balance and equity
- compute breach floors from venue-specific references
- respect venue-specific reset time
- expose breach reasons for reporting and incident logging

### Phase 4: Evaluation

Use venue drawdown rules in evaluation/reporting so backtest results are judged against the active venue, not only FTMO-style defaults.

### Phase 5: Research Integration

Use venue drawdown logic in research viability scoring:

- realized drawdown
- Monte Carlo drawdown median
- Monte Carlo drawdown p95

This lets the same candidate score differently across venues.

### Phase 6: Reporting

Expose current risk headroom in:

- live health report
- incidents
- journals
- evaluation summaries

## First Vertical Slice

This implementation pass starts with:

1. venue rule schema
2. FTMO / FundedNext / Blue Guardian drawdown defaults
3. venue-aware `RiskManager`
4. tests for static, daily, and trailing drawdown behavior

## Known Constraint

Some prop-firm rules are defined relative to account balance, not only equity.

The runtime can support this because:

- simulated snapshots expose `cash` as realized balance
- MT5 account snapshots expose `cash` as MT5 balance

However, account-model-specific rule variants are still not fully represented. This pass implements venue baselines first, then account-model overrides can be added on top.
