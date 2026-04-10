# Stock Gap Open Reclaim Improvement Plan

## Why This Agent

`stock_gap_open_reclaim` is the best next stock agent to improve because:

- it already appears in the top `MSFT` gap-playbook rankings
- it matches the current selector logic better than generic trend agents
- it is structurally closer to how liquid large-cap gap names actually trade
- the current failure mode is not "completely dead"; it is "too few repeatable trades"

So this agent is a better target than adding more new stock families.

## Current Problem

The current agent logic is still too simple:

- it mostly checks `opening_gap_pct`
- then looks for `reclaimed_premarket_high/low` or `first_pullback_*`
- but it does not distinguish between:
  - clean trend gap
  - messy gap with immediate mean reversion
  - event-driven chaotic open
  - failed opening drive

This leads to:

- too few usable entries
- too many one-trade near-misses
- poor validation/test trade density

## Goal

Turn `stock_gap_open_reclaim` into a cleaner "trend continuation after structure retake" agent.

It should only trade when:

- a stock has a real gap
- the open has real participation
- price reclaims a meaningful level
- and the reclaim happens in the direction of intraday continuation, not random chop

## Feature Additions

Add these stock-specific features first.

### 1. Premarket Trend Quality

Needed fields:

- `premarket_return_pct`
- `premarket_close_position`
- `premarket_trend_strength`

Meaning:

- was premarket directional or noisy?
- did premarket finish near its high/low?

Desired use:

- long gap continuation prefers strong premarket up structure
- short gap continuation prefers strong premarket down structure

### 2. Open vs Premarket Structure

Needed fields:

- `open_outside_premarket_high`
- `open_outside_premarket_low`
- `open_inside_premarket_range`
- `open_drive_reentered_premarket_range`

Meaning:

- did the regular session open with true expansion or not?
- did price immediately lose structure after the open?

Desired use:

- avoid continuation trades if the open instantly falls back into messy premarket structure

### 3. Reclaim Quality

Needed fields:

- `reclaim_bar_range_pct`
- `reclaim_bar_close_strength`
- `reclaim_with_rel_vol`
- `reclaim_distance_from_vwap`

Meaning:

- was the reclaim strong or weak?
- did it happen with confirmation or on dead volume?

Desired use:

- only take reclaims that close strongly and are not too stretched from VWAP

### 4. Opening Drive State

Needed fields:

- `opening_drive_failed_up`
- `opening_drive_failed_down`
- `opening_drive_reclaim_up`
- `opening_drive_reclaim_down`

Meaning:

- did the opening drive fail completely?
- or did price break and then successfully retake?

Desired use:

- continuation entries should prefer "reclaim after test"
- avoid entries after a clearly failed drive

## Entry Logic v2

### Long

Only allow long if all are true:

- `opening_gap_pct >= 0.004`
- `relative_volume >= 1.0`
- `premarket_trend_strength > 0`
- `open_outside_premarket_high == 1` or `broke_premarket_high == 1`
- one of:
  - `reclaimed_premarket_high == 1`
  - `opening_drive_reclaim_up == 1`
  - `first_pullback_long == 1`
- `trend_strength > 0`
- `momentum_5 > 0`
- `vwap_distance >= -small_threshold`

Block long if any are true:

- `open_drive_reentered_premarket_range == 1`
- `opening_drive_failed_up == 1`
- reclaim happens too far above VWAP

### Short

Mirror image of long:

- negative gap
- negative premarket trend
- break/reclaim of premarket low
- `first_pullback_short` or `opening_drive_reclaim_down`
- not too far below VWAP
- block if drive clearly fails and reenters the premarket range

## Exit Logic v2

Current exits are too generic. For gap names, use tighter structure-aware exits.

### Proposed exits

- hard fail exit:
  - if long and price loses premarket high reclaim
  - if short and price loses premarket low reclaim
- early stale exit:
  - if continuation does not expand within `3-5` bars after entry
- partial/trailing behavior:
  - tighter than general trend agents
  - gap names should not be held too long if they stop expanding

### Holding profile

Recommended starting profile:

- `structure_exit_bars = 0 or 1`
- `stale_breakout_bars = 4-5`
- `max_holding_bars = 14-18`

This should fit gap continuation better than the broader stock defaults.

## First Implementation Slice

Do not build everything at once.

### Step 1

Add only these features:

- `premarket_return_pct`
- `premarket_close_position`
- `open_inside_premarket_range`
- `open_outside_premarket_high`
- `open_outside_premarket_low`
- `open_drive_reentered_premarket_range`

### Step 2

Update only `StockGapOpenReclaimAgent` to use them.

### Step 3

Test only:

- `MSFT`
- `NVDA`
- `TSLA`

And only within the stock selector playbook flow.

## Success Criteria

The update is useful if at least one of these improves:

- more than `1` closed trade for top `MSFT` gap variants
- non-zero validation/test trades
- lower best-trade concentration
- near-misses move from "single lucky trade" to "thin but repeatable"

If none of these improve, the next step should not be more tuning. Then the stock gap thesis is too weak for the current data.

## Recommended Order

1. Add the six new features.
2. Refactor `StockGapOpenReclaimAgent`.
3. Rerun `MSFT`.
4. If better, rerun stock selector batch.
5. Only then decide whether `NVDA` and `TSLA` should get the same upgrade.
