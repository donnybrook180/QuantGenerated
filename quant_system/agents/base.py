from __future__ import annotations

from abc import ABC, abstractmethod

from quant_system.models import FeatureVector, SignalEvent


class Agent(ABC):
    name: str

    @abstractmethod
    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        raise NotImplementedError
