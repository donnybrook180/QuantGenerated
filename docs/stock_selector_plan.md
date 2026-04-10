# Stock Selector Plan

## Goal

Improve stock performance by moving away from static single-name research toward a daily stock selection workflow.

Instead of asking:
- "Is AAPL a good permanent live symbol?"

the system should ask:
- "Which stocks are the best trading candidates today?"

## Why this is better

The current stock workflow is weak because:
- static large-cap names often do not produce enough repeated intraday edge
- the best stock opportunities are usually conditional
  - event day
  - large gap
  - high relative volume
  - unusual range expansion
- stock alpha is often in selection first, strategy second

## Target workflow

1. Build a daily candidate universe
2. Score and rank today's stocks
3. Keep only the top names
4. Run stock intraday agents only on those names
5. Export research/deploy artifacts only for the selected names

## Phase 1: Daily stock selector

Create a selector that ranks stocks for the current day using:

- premarket / opening gap size
- relative volume
- ATR / range expansion
- event/news presence
- liquidity filter

Suggested outputs per symbol:

- `selector_score`
- `gap_pct`
- `relative_volume`
- `atr_proxy`
- `event_day`
- `earnings_day`
- `news_count`
- `liquidity_score`

Suggested first pass:

- only consider liquid US stocks
- focus on large caps and highly active names
- return top `5` to `15`

## Phase 2: Selector artifacts

Write daily selector output to:

- `artifacts/system/reports/stock_selector_today.txt`
- `artifacts/system/reports/stock_selector_today.csv`

That report should include:

- rank
- symbol
- score
- main reasons selected

## Phase 3: Research integration

Allow stock research to accept:

- one explicit symbol
- or a selector-driven list

Example:

- `python main_symbol_research.py AAPL`
- or
- `python tools/main_stock_selector.py`
- then research top selected names only

## Phase 4: Live policy

Do not keep stocks permanently live by default.

Instead:

- stocks are `research_only` unless they are selected today
- only selected stocks are allowed into temporary live deployment

This avoids carrying dead symbols all year.

## Phase 5: Strategy policy

Use the selector as a gate above existing stock agents:

- `stock_gap_and_go`
- `stock_gap_fade`
- `stock_trend_breakout`
- `stock_power_hour_continuation`
- event-driven stock agents

Do not build many new stock agents before the selector exists.

## Suggested technical design

### New module

- `quant_system/research/stock_selector.py`

Functions:

- `build_stock_selector_universe(...)`
- `score_stock_candidate(...)`
- `select_top_stock_candidates(...)`
- `write_stock_selector_report(...)`

### New CLI

- `tools/main_stock_selector.py`

Purpose:

- run the selector
- print ranked stocks
- write artifacts

### Data sources

Prefer current local stack:

- DuckDB cached bars
- MT5 bars if needed
- optional stock event flags if available

No hard dependency on Polygon should remain.

## First version scope

Keep version 1 simple.

Universe:

- `AAPL`
- `AMD`
- `META`
- `MSFT`
- `NVDA`
- `TSLA`

Optional later expansion:

- additional liquid Nasdaq / NYSE names

Selection logic:

- minimum liquidity
- minimum recent range
- minimum relative volume
- optional event/news bonus
- top 3 to 5 names only

## Success criteria

The selector is useful if:

- it regularly returns only a few strong candidates
- those candidates produce more viable stock research than static single-name runs
- the resulting stock deployments look better than the current `research_only` outcomes

## Recommended order

1. Build selector report
2. Validate selector rankings manually
3. Research only selected names
4. Compare against static stock research
5. Only then consider live deployment
