from __future__ import annotations

from quant_system.agents.base import Agent
from quant_system.models import FeatureVector, Side, SignalEvent


class SessionEntryFilterAgent(Agent):
    name = "session_entry_filter"

    def __init__(self, allowed_hours: set[int]) -> None:
        self.allowed_hours = allowed_hours

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        hour = int(feature.values.get("hour_of_day", feature.timestamp.hour))
        if hour in self.allowed_hours:
            return None
        return SignalEvent(
            feature.timestamp,
            self.name,
            feature.symbol,
            Side.FLAT,
            1.0,
            {"veto": "session_entry_filter"},
        )
