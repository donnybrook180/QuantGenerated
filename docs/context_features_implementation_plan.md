## Context Features Implementation Plan

Date: 2026-04-09

### Goal
Shift research forward from "more strategy families" toward "better market context".

This codebase already has a useful first layer of context in [`quant_system/research/features.py`](/C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/research/features.py):
- `prior_day_*`
- `overnight_*`
- `opening_gap_pct`
- `minutes_from_open`
- `morning_session`, `midday_session`, `afternoon_session`

So the next step is not to start from zero.
It is to add the missing context that is most likely to improve weak symbols such as `US100`, `US500`, `EU50`, and `GER40`.

## Priority 1

### 1. Level Interaction Features
Add features that tell agents whether price is reclaiming, rejecting, or sweeping important levels.

Add to [`quant_system/research/features.py`](/C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/research/features.py):
- `reclaimed_prior_day_high`
- `reclaimed_prior_day_low`
- `reclaimed_overnight_high`
- `reclaimed_overnight_low`
- `failed_break_above_prior_day_high`
- `failed_break_below_prior_day_low`
- `failed_break_above_overnight_high`
- `failed_break_below_overnight_low`
- `distance_to_session_open`
- `distance_to_session_vwap` if a stable VWAP feature exists or can be added cheaply

Why:
- This is the missing layer for failed-bounce, reclaim, and false-break logic.
- It should help most for indices and metals.

Expected impact:
- `US100`
- `US500`
- `EU50`
- `GER40`
- `XAUUSD`

### 2. Day Structure Features
Add features that describe the type of day.

Add:
- `inside_day_context`
- `outside_day_context`
- `prior_day_trend_strength`
- `overnight_extension_pct`
- `opening_drive_range_pct`
- `opening_drive_direction`
- `opening_drive_vs_prior_day_close`

Why:
- Many index and FX setups depend less on the current bar and more on what kind of day is unfolding.
- This should reduce the need for many narrow session variants.

Expected impact:
- `US100`
- `US500`
- `EU50`
- `GER40`
- `EURUSD`
- `GBPUSD`

## Priority 2

### 3. Session State Features
The code already tags sessions, but not enough state progression.

Add:
- `session_range_pct`
- `session_range_expanding`
- `session_range_compression`
- `break_of_morning_range`
- `midday_reversal_state`
- `afternoon_continuation_state`

Why:
- This helps distinguish "trend day still alive" from "trend day already spent".
- It should especially help with overlap and midday logic.

Expected impact:
- `EURUSD`
- `GBPUSD`
- `US100`
- `US500`
- `JP225`

### 4. Event-Day Context
There is already some event-aware logic in parts of the system, but the feature layer can expose more explicit state.

Add:
- `high_impact_event_day`
- `pre_event_window`
- `post_event_window`
- `event_day_vol_expansion`

Why:
- This will improve agent behavior on days where standard breakout logic is structurally less reliable.
- It matters most for FX, indices, and metals.

Expected impact:
- `EURUSD`
- `GBPUSD`
- `USDJPY`
- `XAUUSD`
- `US100`
- `US500`

## Priority 3

### 5. Multi-Bar Pattern Features
Add simple pattern-state features instead of creating many dedicated agents.

Add:
- `higher_low_state`
- `lower_high_state`
- `two_leg_pullback_state`
- `compression_then_expansion_state`
- `reversal_after_extension_state`

Why:
- This captures some of the intent behind many current families without needing to brute-force many strategy variants.

Expected impact:
- `US100`
- `US500`
- `BTC`
- `ETH`
- `GBPUSD`

## Rollout Order

### Phase 1
Add only Priority 1 level-interaction features.

Then rerun:
- `US100`
- `US500`
- `EU50`
- `GER40`
- `XAUUSD`

Success criterion:
- at least one genuinely new viable candidate appears for `US100` or `US500`
- or one current weak execution set gains better set-quality metrics

### Phase 2
Add Priority 2 day-structure and session-state features.

Then rerun:
- `EURUSD`
- `GBPUSD`
- `USDJPY`
- `JP225`

Success criterion:
- more distinct regime coverage without exploding the number of families

### Phase 3
Only after Phases 1 and 2, add a small number of new agents that explicitly use these features.

Do not add many new families at once.
Add at most:
- 1 new index reclaim family
- 1 new index failed-break family
- 1 new FX session continuation/reversal family

## Concrete File Plan

### Modify
- [`quant_system/research/features.py`](/C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/research/features.py)
  - add new context calculations
  - keep names stable and simple

### Then modify
- [`quant_system/symbol_research.py`](/C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/symbol_research.py)
  - use the new context via a very small number of new targeted candidates
  - do not brute-force many more variants immediately

### Optional later
- new modules only if needed:
  - [`quant_system/agents/us100.py`](/C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/agents/us100.py)
  - [`quant_system/agents/us500.py`](/C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/agents/us500.py)
  - [`quant_system/agents/forex.py`](/C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/agents/forex.py)

## What Not To Do
- Do not add calendar-season logic as a primary driver.
- Do not add many more parameter variants before the context layer improves.
- Do not treat every weak symbol the same; indices need the most help first.

## Recommendation
Start with Priority 1 only.

If that does not materially improve `US100` or `US500`, the next bottleneck is likely not family count but data quality or bar-level information depth.
