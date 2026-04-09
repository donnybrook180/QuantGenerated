from __future__ import annotations

from quant_system.agents.base import Agent
from quant_system.models import FeatureVector, Side, SignalEvent


class MacroEventRiskSentinelAgent(Agent):
    name = "macro_event_risk_sentinel"

    def __init__(self, allow_event_day: bool = True, allow_pre_event_window: bool = False, allow_post_event_window: bool = False) -> None:
        self.allow_event_day = allow_event_day
        self.allow_pre_event_window = allow_pre_event_window
        self.allow_post_event_window = allow_post_event_window

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        if not self.allow_event_day and feature.values.get("macro_high_impact_event_day", 0.0) >= 1.0:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 1.0, {"veto": "macro_event_day"})
        if not self.allow_pre_event_window and feature.values.get("macro_pre_event_window", 0.0) >= 1.0:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 1.0, {"veto": "macro_pre_event_window"})
        if not self.allow_post_event_window and feature.values.get("macro_post_event_window", 0.0) >= 1.0:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 1.0, {"veto": "macro_post_event_window"})
        return None


__all__ = ["MacroEventRiskSentinelAgent"]
