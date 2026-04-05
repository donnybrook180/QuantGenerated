from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"
    FLAT = "flat"


@dataclass(slots=True)
class MarketBar:
    timestamp: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(slots=True)
class FeatureVector:
    timestamp: datetime
    symbol: str
    values: dict[str, float]


@dataclass(slots=True)
class SignalEvent:
    timestamp: datetime
    agent_name: str
    symbol: str
    side: Side
    confidence: float
    metadata: dict[str, float | str] = field(default_factory=dict)


@dataclass(slots=True)
class OrderRequest:
    timestamp: datetime
    symbol: str
    side: Side
    quantity: float
    reason: str


@dataclass(slots=True)
class FillEvent:
    timestamp: datetime
    symbol: str
    side: Side
    quantity: float
    price: float
    costs: float = 0.0


@dataclass(slots=True)
class Position:
    symbol: str
    quantity: float = 0.0
    average_price: float = 0.0


@dataclass(slots=True)
class PortfolioSnapshot:
    timestamp: datetime
    cash: float
    equity: float
    unrealized_pnl: float
    realized_pnl: float
    drawdown: float
