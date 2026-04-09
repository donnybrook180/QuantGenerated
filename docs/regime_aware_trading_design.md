# Regime-Aware Trading Design

## Goal

Replace "one strategy for the whole year" behavior with a regime-aware system that:

- classifies the current market state from recent data
- activates only the strategies that fit that state
- scales position size to current volatility
- reports research and live results by regime instead of only as one blended annual total

This should sit above the existing strategy layer. Strategies keep generating signals. A new regime layer decides:

- whether a strategy is eligible now
- how much size it is allowed to take
- whether the symbol should be partially or fully de-risked

## Current Fit In This Codebase

The project already has partial building blocks:

- features are built in symbol research and live runtime
- live runtime already has a simple `_matches_regime(...)` filter in `quant_system/live/runtime.py`
- deployment artifacts already carry `regime_filter_label`
- research already exports candidate metrics, plots, and execution sets

What is missing is a proper regime model. Right now regime is effectively:

- static
- very coarse
- embedded inside candidate metadata
- not driven by explicit live classification
- not used for dynamic sizing

## Target Architecture

### 1. New Regime Domain Layer

Add a dedicated module:

- `quant_system/regime.py`

Core objects:

```python
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class RegimeSnapshot:
    timestamp: datetime
    symbol: str
    regime_label: str
    volatility_label: str
    structure_label: str
    realized_vol_20: float
    realized_vol_100: float
    vol_ratio: float
    vol_percentile: float
    atr_percent: float
    trend_strength: float
    range_efficiency: float
    risk_multiplier: float
    block_new_entries: bool = False
    metadata: dict[str, float | str] = field(default_factory=dict)
```

Recommended first regime labels:

- `calm_trend`
- `calm_range`
- `volatile_trend`
- `volatile_chop`
- `event_risk`

Supporting functions:

- `build_regime_snapshot(features: list[FeatureVector], symbol: str) -> RegimeSnapshot`
- `classify_regime(feature: FeatureVector) -> RegimeSnapshot`
- `regime_allows_strategy(snapshot: RegimeSnapshot, allowed_regimes: tuple[str, ...]) -> bool`
- `regime_risk_multiplier(snapshot: RegimeSnapshot) -> float`

### 2. Extend Feature Engineering

Feature vectors should contain explicit regime inputs. If not already present, add:

- `realized_vol_20`
- `realized_vol_100`
- `vol_ratio`
- `vol_percentile`
- `atr_percent`
- `trend_strength`
- `range_efficiency`
- `session_label`

These can be added where features are built for both research and live:

- `quant_system/symbol_research.py`
- `quant_system/live/runtime.py` via `_build_features_with_events(...)`

First version should stay simple and deterministic. No HMM or ML classifier needed yet.

### 3. Extend Deployment Metadata

Current deployment model:

- `quant_system/live/models.py`

Extend `DeploymentStrategy` with regime-aware metadata:

```python
allowed_regimes: tuple[str, ...] = ()
blocked_regimes: tuple[str, ...] = ()
min_vol_percentile: float = 0.0
max_vol_percentile: float = 1.0
base_allocation_weight: float = 1.0
max_risk_multiplier: float = 1.0
min_risk_multiplier: float = 0.0
```

Also extend `SymbolDeployment` with symbol-level regime policy:

```python
target_volatility: float = 0.0
max_symbol_vol_percentile: float = 0.98
block_new_entries_in_event_risk: bool = True
```

Reason:

- candidate-level selection should survive research
- live should not hardcode regime decisions outside deployment metadata

### 4. Research Changes

Research should stop evaluating candidates only on full-period totals.

Add regime-segmented evaluation to symbol research:

- compute each candidate's performance inside each regime bucket
- store regime robustness metrics
- only promote candidates if they are strong in at least one regime and not catastrophic in others

Add per-candidate regime metrics:

- `best_regime`
- `worst_regime`
- `regime_trade_count_by_label`
- `regime_pnl_by_label`
- `regime_pf_by_label`
- `regime_win_rate_by_label`
- `regime_stability_score`

Promotion logic should prefer:

- strong in one or more regimes
- enough trades in those regimes
- acceptable drawdown when the regime is active
- no severe collapse in nearby regimes

Concrete code touchpoints:

- `quant_system/symbol_research.py`
- candidate row schema
- export functions for research reports
- execution set selection logic

### 5. Live Runtime Changes

Current live evaluation in `quant_system/live/runtime.py`:

- fetch bars
- build features
- evaluate candidate
- reconcile order

Target flow:

1. Fetch bars
2. Build recent features
3. Build one `RegimeSnapshot` from the latest regime inputs
4. For each strategy:
   - check regime eligibility
   - check vol percentile bounds
   - scale order size by `risk_multiplier`
   - optionally block entries if regime is `event_risk` or `volatile_chop`
5. Reconcile positions
6. Log the regime used for the decision

Recommended runtime changes:

- add `regime_snapshot` to `LiveRunResult`
- add `regime_label`, `vol_percentile`, `risk_multiplier` to `StrategyAction`
- include regime data in live journal JSON

### 6. Dynamic Position Sizing

Volatility should directly affect size.

Target formula for first version:

```python
effective_order_size = (
    execution.order_size
    * strategy.base_allocation_weight
    * snapshot.risk_multiplier
)
```

Example multipliers:

- `calm_trend`: `1.00`
- `calm_range`: `0.80`
- `volatile_trend`: `0.50`
- `volatile_chop`: `0.15`
- `event_risk`: `0.00`

This is intentionally simple. It is enough for a first production version.

### 7. Journaling and Observability

Every live journal entry should record:

- regime label
- volatility percentile
- atr percent
- trend strength
- risk multiplier
- whether entry was blocked by regime

Every closed trade record should also carry:

- entry regime label
- exit regime label

That allows later analysis of:

- which regimes produced PnL
- which regimes should have been blocked
- whether sizing was too aggressive in high vol

### 8. Rollout Plan

#### Phase 1: Safe deterministic regime filter

Implement:

- `quant_system/regime.py`
- volatility/trend-based classification
- live gating
- dynamic size multiplier
- journal logging

Do not change strategy internals yet.

#### Phase 2: Research by regime

Implement:

- regime metrics in candidate evaluation
- regime-aware promotion
- regime-aware deployment export

This is the most important research upgrade.

#### Phase 3: Adaptive strategy library

Implement:

- some strategies specialized for calm trend
- some for range
- some disabled in high volatility

At this point the bot becomes a regime-aware allocator across strategies instead of one fixed yearly strategy.

## Recommended Minimal First Build

If we keep the first implementation deliberately small, do this first:

1. Add `quant_system/regime.py`
2. Create `RegimeSnapshot` from the latest feature
3. Add `allowed_regimes` to deployment strategy metadata
4. Scale live order size by `risk_multiplier`
5. Block new entries in `event_risk` and `volatile_chop`
6. Log regime data in live journals

This gives immediate behavior improvement without needing to redesign every agent.

## Specific File Plan

Add:

- `docs/regime_aware_trading_design.md`
- `quant_system/regime.py`

Update:

- `quant_system/live/models.py`
- `quant_system/live/runtime.py`
- `quant_system/live/journal.py`
- `quant_system/live/deploy.py`
- `quant_system/symbol_research.py`
- `quant_system/config.py`

Optional later:

- `quant_system/plotting.py` for regime plots
- `tools/main_symbol_execution_set.py` to show regime suitability

## Non-Goals For Version 1

Do not do these yet:

- hidden Markov models
- reinforcement learning
- monthly hardcoded season rules
- auto-retraining in live
- dozens of regime classes

Those are easy to overfit. Version 1 should stay interpretable.

## Practical Principle

The correct mental model is:

- strategies produce possible actions
- regime layer decides if those actions fit the current market
- risk layer decides how large the action may be

That is the right upgrade path from the current codebase.
