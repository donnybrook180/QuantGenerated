## Data Upgrade Plan

Date: 2026-04-09

### Goal
Improve the data layer so research and live trading can make better decisions than the current OHLCV-only baseline.

This is not a "collect everything" plan.
It is a practical plan for the highest-value data upgrades for the current codebase.

## Current State

The system already has:
- cached bar storage in DuckDB
- feature generation from OHLCV bars
- some event flag plumbing
- MT5 integration
- live journals and fill-event storage

The main limitation is that difficult symbols still rely on too little context.

## Priority Order

1. 1-minute context bars for indices and gold
2. Real macro-event calendar with timestamped releases
3. Cross-asset context series
4. Execution-friction data
5. Data quality / completeness diagnostics

## Upgrade 1: 1-Minute Context Bars

### Why
Many intraday structures disappear on `5m` or `15m` aggregation:
- failed break
- opening drive reclaim
- liquidity sweep
- quick reversal after extension

This matters most for:
- `US100`
- `US500`
- `XAUUSD`
- later: `EURUSD`, `GBPUSD`, `USDJPY`

### What to add
Store `1m` bars alongside current research bars.

### Likely files
- [`quant_system/data/market_data.py`](/C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/data/market_data.py)
- [`quant_system/integrations/mt5.py`](/C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/integrations/mt5.py)
- [`quant_system/symbol_research.py`](/C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/symbol_research.py)
- [`quant_system/research/features.py`](/C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/research/features.py)

### Storage idea
Use the same DuckDB bar store, but add `1m` cache keys for selected symbols only.

### Practical scope
Start with:
- `US100`
- `US500`
- `XAUUSD`

### Intended use
Do not necessarily run every agent on 1-minute bars.
Use 1-minute bars mainly to compute better context features:
- opening drive high/low
- first reclaim after sweep
- faster session range evolution

## Upgrade 2: Timestamped Macro-Event Calendar

### Why
FX, indices, and gold behave differently around major macro releases.
Current `high_impact_event_day` is useful but too coarse.

### What to add
Store timestamped releases with:
- timestamp
- country / region
- event name
- impact level
- optional actual / forecast / previous

### Highest-value events
- CPI
- NFP
- FOMC
- ECB
- BoE
- BoJ
- PMI / ISM
- GDP flash releases

### Most impacted symbols
- `EURUSD`
- `GBPUSD`
- `USDJPY`
- `XAUUSD`
- `US100`
- `US500`

### Likely files
- [`quant_system/integrations/polygon_events.py`](/C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/integrations/polygon_events.py) or a new dedicated macro-event integration
- [`quant_system/research/features.py`](/C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/research/features.py)
- [`quant_system/live_support.py`](/C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/live_support.py)

### New features to derive
- `minutes_to_next_high_impact_event`
- `minutes_since_last_high_impact_event`
- `pre_event_window`
- `post_event_window`
- `us_macro_event_active`
- `uk_macro_event_active`
- `eu_macro_event_active`
- `jp_macro_event_active`

## Upgrade 3: Cross-Asset Context Series

### Why
Some symbols should not be interpreted in isolation.

For example:
- `US500` improves with `US100` / volatility / dollar context
- `XAUUSD` improves with rates / dollar / risk-off context
- FX pairs improve with dollar and rate-sensitive context

### Suggested context series
- `US100`
- `US500`
- `DXY` proxy
- `VIX` or volatility proxy
- `TNX` or rates proxy
- optionally `XAUUSD` as a risk-off context for indices

### Most impacted symbols
- `US100`
- `US500`
- `XAUUSD`
- `EURUSD`
- `USDJPY`

### Likely files
- [`quant_system/data/market_data.py`](/C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/data/market_data.py)
- [`quant_system/research/features.py`](/C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/research/features.py)

### New features to derive
- `peer_index_trend_strength`
- `peer_index_divergence`
- `dollar_context_trend`
- `vol_proxy_high`
- `rates_context_shift`

## Upgrade 4: Execution-Friction Data

### Why
This is critical for live truth.
Even good research can fail if spreads and slippage eat the edge.

### What to collect
- spread at signal time
- spread at order send time
- fill delay
- requested price vs fill price
- rejection / retry counts
- slippage by symbol and session

### Likely files
- [`quant_system/integrations/mt5.py`](/C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/integrations/mt5.py)
- [`quant_system/ai/storage.py`](/C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/ai/storage.py)
- [`quant_system/allocator_fill_backtest.py`](/C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/allocator_fill_backtest.py)

### Why this matters now
The current fill-aware backtest is still empty because no fills exist yet.
As soon as fills accumulate, these fields become the most important source of truth.

## Upgrade 5: Data Quality Diagnostics

### Why
Before adding more data, verify the current data is consistent.

### Checks to add
- missing bar ratio per symbol/timeframe
- session boundary correctness
- timezone consistency
- duplicate bar detection
- broker-vs-research symbol mapping mismatches
- overnight range completeness

### Likely files
- new diagnostic CLI under [`tools/`](/C:/Users/liset/PycharmProjects/QuantGenerated/tools)
- [`quant_system/data/market_data.py`](/C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/data/market_data.py)

## Symbol Impact Matrix

### Highest expected benefit
- `US100`
- `US500`
- `XAUUSD`
- `EURUSD`
- `GBPUSD`
- `USDJPY`

### Moderate expected benefit
- `EU50`
- `GER40`
- `JP225`

### Lower expected benefit
- `BTC`
- `ETH`

Crypto already behaves more naturally with current trend/volatility context, so data upgrades are less urgent there.

## Recommended Rollout

### Phase 1
Build `1m` context bars for:
- `US100`
- `US500`
- `XAUUSD`

Success criterion:
- new context features can be derived reliably from `1m`
- no data consistency issues

### Phase 2
Add timestamped macro-event calendar for:
- `EURUSD`
- `GBPUSD`
- `USDJPY`
- `XAUUSD`
- `US100`
- `US500`

Success criterion:
- event-window features available in feature generation and live support

### Phase 3
Add cross-asset context:
- `US100`
- `US500`
- `DXY`
- vol proxy
- rates proxy

Success criterion:
- context features available without breaking research speed

### Phase 4
Add execution-friction capture and use it in fill-aware evaluation

Success criterion:
- fill-aware backtest becomes meaningful once live fills arrive

## Recommendation

If only one data upgrade is built next, do this:

1. `1m` context bars for `US100`, `US500`, `XAUUSD`

If two are built, do this:

1. `1m` context bars
2. timestamped macro-event calendar

These two upgrades are the highest expected return for the current system.
