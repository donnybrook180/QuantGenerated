from __future__ import annotations

from types import SimpleNamespace

from quant_system.live.allocation import allocate_symbol_exposure
from quant_system.live.interpreter_gate import (
    allocator_score,
    candidate_archetype,
    interpreter_block_reason,
)
from quant_system.models import Side


def test_candidate_archetype_detects_breakout_family() -> None:
    strategy = SimpleNamespace(candidate_name="forex_breakout_momentum__30m_overlap")
    assert candidate_archetype(strategy) == "breakout"


def test_interpreter_block_reason_blocks_explicit_breakout_block() -> None:
    strategy = SimpleNamespace(candidate_name="forex_breakout_momentum__30m_overlap")
    interpreter_state = SimpleNamespace(
        blocked_archetypes=["breakout"],
        allowed_archetypes=[],
        risk_posture="normal",
        no_trade_reason="",
        session_regime="overlap",
    )
    assert interpreter_block_reason(strategy, interpreter_state) == "interpreter_blocked::breakout"


def test_allocator_score_rewards_allowed_regime() -> None:
    strategy = SimpleNamespace(
        candidate_name="trend__4h_overlap",
        min_risk_multiplier=0.5,
        max_risk_multiplier=1.5,
        base_allocation_weight=1.0,
        allowed_regimes={"trend_up_vol_high", "orderly_trend"},
        regime_filter_label="orderly_trend",
    )
    snapshot = SimpleNamespace(
        risk_multiplier=1.0,
        regime_label="trend_up_vol_high",
        volatility_label="vol_high",
        structure_label="trend_up",
    )
    score = allocator_score(strategy, Side.BUY, 0.8, snapshot)
    assert score > 0.8


def test_allocate_symbol_exposure_keeps_only_dominant_side() -> None:
    long_item = SimpleNamespace(signal_side=Side.BUY, allocator_score=2.0, allocation_fraction=0.0)
    short_item = SimpleNamespace(signal_side=Side.SELL, allocator_score=1.0, allocation_fraction=0.0)
    allocate_symbol_exposure([long_item, short_item])
    assert long_item.allocation_fraction == 1.0
    assert short_item.allocation_fraction == 0.0
