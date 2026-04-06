from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class StrategyProfile:
    name: str
    data_symbol: str
    broker_symbol: str
    description: str


PROFILE_MAP: dict[str, StrategyProfile] = {
    "us500_trend": StrategyProfile(
        name="us500_trend",
        data_symbol="SPY",
        broker_symbol="US500.cash",
        description="US500 trend continuation via SPY proxy data",
    ),
    "us100_trend": StrategyProfile(
        name="us100_trend",
        data_symbol="QQQ",
        broker_symbol="US100.cash",
        description="US100 trend continuation via QQQ proxy data",
    ),
    "ger40_orb": StrategyProfile(
        name="ger40_orb",
        data_symbol="DAX",
        broker_symbol="GER40.cash",
        description="GER40 opening range breakout via DAX ETF proxy data",
    ),
    "xauusd_volatility": StrategyProfile(
        name="xauusd_volatility",
        data_symbol="C:XAUUSD",
        broker_symbol="XAUUSD",
        description="XAUUSD volatility breakout",
    ),
}


def resolve_profiles(active_profiles: tuple[str, ...]) -> list[StrategyProfile]:
    profiles: list[StrategyProfile] = []
    for name in active_profiles:
        if name not in PROFILE_MAP:
            continue
        profile = PROFILE_MAP[name]
        data_symbol = os.getenv(f"{name.upper()}_DATA_SYMBOL", profile.data_symbol)
        broker_symbol = os.getenv(f"{name.upper()}_BROKER_SYMBOL", profile.broker_symbol)
        profiles.append(
            StrategyProfile(
                name=profile.name,
                data_symbol=data_symbol,
                broker_symbol=broker_symbol,
                description=profile.description,
            )
        )
    return profiles
