from __future__ import annotations

from quant_system.models import Side


def allocate_symbol_exposure(evaluated: list[object]) -> None:
    buy_total = sum(item.allocator_score for item in evaluated if item.signal_side == Side.BUY)
    sell_total = sum(item.allocator_score for item in evaluated if item.signal_side == Side.SELL)
    dominant_side = Side.FLAT
    dominant_total = 0.0
    opposing_total = 0.0
    if buy_total > 0.0 or sell_total > 0.0:
        if buy_total >= sell_total:
            dominant_side = Side.BUY
            dominant_total = buy_total
            opposing_total = sell_total
        else:
            dominant_side = Side.SELL
            dominant_total = sell_total
            opposing_total = buy_total

    for item in evaluated:
        item.allocation_fraction = 0.0
        if item.signal_side == Side.FLAT or item.allocator_score <= 0.0:
            continue
        if dominant_side == Side.FLAT or dominant_total <= 0.0:
            continue
        if item.signal_side != dominant_side:
            continue
        if opposing_total > 0.0 and dominant_total < opposing_total * 1.10:
            continue
        item.allocation_fraction = item.allocator_score / dominant_total
