from __future__ import annotations

from quant_system.agents.base import Agent
from quant_system.agents.common import RollingCloseState, scaled_confidence
from quant_system.models import FeatureVector, Side, SignalEvent


class EventAwareRiskSentinelAgent(Agent):
    name = "event_risk_sentinel"

    def __init__(self, allow_high_impact_day: bool = False, allow_event_blackout: bool = False) -> None:
        self.allow_high_impact_day = allow_high_impact_day
        self.allow_event_blackout = allow_event_blackout

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        if not self.allow_event_blackout and feature.values.get("event_blackout", 0.0) >= 1.0:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 1.0, {"veto": "event_blackout"})
        if not self.allow_high_impact_day and feature.values.get("high_impact_event_day", 0.0) >= 1.0:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 1.0, {"veto": "high_impact_news"})
        return None


class StockTrendBreakoutAgent(Agent):
    name = "stock_trend_breakout"

    def __init__(
        self,
        fast_window: int = 10,
        slow_window: int = 30,
        min_relative_volume: float = 1.0,
        min_atr_proxy: float = 0.003,
        max_news_count: float = 5.0,
        min_momentum_5: float = 0.0,
        min_momentum_20: float = 0.0,
    ) -> None:
        self.fast_values = RollingCloseState(fast_window)
        self.slow_values = RollingCloseState(slow_window)
        self.min_relative_volume = min_relative_volume
        self.min_atr_proxy = min_atr_proxy
        self.max_news_count = max_news_count
        self.min_momentum_5 = min_momentum_5
        self.min_momentum_20 = min_momentum_20

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        self.fast_values.append(close)
        self.slow_values.append(close)
        if not self.fast_values.ready or not self.slow_values.ready:
            return None
        if (
            feature.values.get("in_regular_session", 0.0) < 1.0
            or feature.values.get("event_blackout", 0.0) >= 1.0
            or feature.values.get("relative_volume", 1.0) < self.min_relative_volume
            or feature.values.get("news_count_1d", 0.0) > self.max_news_count
        ):
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})

        fast = self.fast_values.mean()
        slow = self.slow_values.mean()
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        if (
            fast > slow
            and momentum_5 >= self.min_momentum_5
            and momentum_20 >= self.min_momentum_20
            and atr_proxy >= self.min_atr_proxy
        ):
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.BUY,
                scaled_confidence(0.0, (abs(momentum_5), 160), (abs(momentum_20), 160), (atr_proxy, 180)),
                {"atr_proxy": atr_proxy, "momentum_20": momentum_20},
            )
        if (
            fast < slow
            and momentum_5 <= -self.min_momentum_5
            and momentum_20 <= -self.min_momentum_20
            and atr_proxy >= self.min_atr_proxy
        ):
            return SignalEvent(
                feature.timestamp,
                self.name,
                feature.symbol,
                Side.SELL,
                scaled_confidence(0.0, (abs(momentum_5), 160), (abs(momentum_20), 160), (atr_proxy, 180)),
                {"atr_proxy": atr_proxy, "momentum_20": momentum_20},
            )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})


class StockNewsMomentumAgent(Agent):
    name = "stock_news_momentum"

    def __init__(self, min_relative_volume: float = 1.4, min_atr_proxy: float = 0.004) -> None:
        self.min_relative_volume = min_relative_volume
        self.min_atr_proxy = min_atr_proxy

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        if feature.values.get("in_regular_session", 0.0) < 1.0:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
        high_impact = feature.values.get("high_impact_event_day", 0.0) >= 1.0
        earnings_day = feature.values.get("earnings_event_day", 0.0) >= 1.0
        if not (high_impact or earnings_day):
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
        rel_vol = feature.values.get("relative_volume", 1.0)
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        if rel_vol < self.min_relative_volume or atr_proxy < self.min_atr_proxy:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
        if momentum_5 > 0 and trend_strength > 0:
            side = Side.BUY
        elif momentum_5 < 0 and trend_strength < 0:
            side = Side.SELL
        else:
            side = Side.FLAT
        return SignalEvent(
            feature.timestamp,
            self.name,
            feature.symbol,
            side,
            scaled_confidence(0.0, (abs(momentum_5), 150), (atr_proxy, 180), (rel_vol - 1.0, 60)),
            {
                "news_count_1d": feature.values.get("news_count_1d", 0.0),
                "earnings_event_day": feature.values.get("earnings_event_day", 0.0),
            },
        )


class StockPostEarningsDriftAgent(Agent):
    name = "stock_post_earnings_drift"

    def __init__(self, min_relative_volume: float = 1.1, max_minutes_from_open: float = 150.0) -> None:
        self.min_relative_volume = min_relative_volume
        self.max_minutes_from_open = max_minutes_from_open

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        if feature.values.get("in_regular_session", 0.0) < 1.0:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
        minutes_from_open = feature.values.get("minutes_from_open", -1.0)
        if minutes_from_open < 0 or minutes_from_open > self.max_minutes_from_open:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
        if feature.values.get("event_blackout", 0.0) >= 1.0:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
        if feature.values.get("earnings_event_day", 0.0) < 1.0:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
        rel_vol = feature.values.get("relative_volume", 1.0)
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        if rel_vol < self.min_relative_volume or atr_proxy < 0.003:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
        if momentum_5 > 0 and momentum_20 > 0:
            side = Side.BUY
        elif momentum_5 < 0 and momentum_20 < 0:
            side = Side.SELL
        else:
            side = Side.FLAT
        return SignalEvent(
            feature.timestamp,
            self.name,
            feature.symbol,
            side,
            scaled_confidence(0.0, (abs(momentum_5), 160), (abs(momentum_20), 140), (rel_vol - 1.0, 70)),
            {"earnings_event_day": feature.values.get("earnings_event_day", 0.0)},
        )


class StockGapFadeAgent(Agent):
    name = "stock_gap_fade"

    def __init__(self, min_gap_proxy: float = 0.004, min_relative_volume: float = 1.05) -> None:
        self.min_gap_proxy = min_gap_proxy
        self.min_relative_volume = min_relative_volume

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        if feature.values.get("in_regular_session", 0.0) < 1.0:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
        minutes_from_open = feature.values.get("minutes_from_open", -1.0)
        if minutes_from_open < 5 or minutes_from_open > 120:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
        if feature.values.get("event_blackout", 0.0) >= 1.0:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
        rel_vol = feature.values.get("relative_volume", 1.0)
        z_score = feature.values.get("z_score_20", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        if rel_vol < self.min_relative_volume or atr_proxy < self.min_gap_proxy:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
        if z_score >= 2.0 and momentum_5 < 0:
            side = Side.SELL
        elif z_score <= -2.0 and momentum_5 > 0:
            side = Side.BUY
        else:
            side = Side.FLAT
        return SignalEvent(
            feature.timestamp,
            self.name,
            feature.symbol,
            side,
            scaled_confidence(0.0, (abs(z_score), 35), (atr_proxy, 180), (rel_vol - 1.0, 70)),
            {"z_score_20": z_score},
        )


class StockGapAndGoAgent(Agent):
    name = "stock_gap_and_go"

    def __init__(
        self,
        min_relative_volume: float = 1.2,
        min_atr_proxy: float = 0.0035,
        min_momentum_5: float = 0.0,
        min_momentum_20: float = 0.0,
        max_minutes_from_open: float = 90.0,
    ) -> None:
        self.min_relative_volume = min_relative_volume
        self.min_atr_proxy = min_atr_proxy
        self.min_momentum_5 = min_momentum_5
        self.min_momentum_20 = min_momentum_20
        self.max_minutes_from_open = max_minutes_from_open

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        if feature.values.get("in_regular_session", 0.0) < 1.0:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
        minutes_from_open = feature.values.get("minutes_from_open", -1.0)
        if minutes_from_open < 5 or minutes_from_open > self.max_minutes_from_open:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
        if feature.values.get("event_blackout", 0.0) >= 1.0:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
        rel_vol = feature.values.get("relative_volume", 1.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        atr_proxy = feature.values.get("atr_proxy", 0.0)
        if rel_vol < self.min_relative_volume or atr_proxy < self.min_atr_proxy:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
        if momentum_5 >= self.min_momentum_5 and momentum_20 >= self.min_momentum_20 and trend_strength > 0:
            side = Side.BUY
        elif momentum_5 <= -self.min_momentum_5 and momentum_20 <= -self.min_momentum_20 and trend_strength < 0:
            side = Side.SELL
        else:
            side = Side.FLAT
        return SignalEvent(
            feature.timestamp,
            self.name,
            feature.symbol,
            side,
            scaled_confidence(0.0, (abs(momentum_5), 150), (abs(momentum_20), 140), (rel_vol - 1.0, 70)),
            {"minutes_from_open": minutes_from_open},
        )


class StockPowerHourContinuationAgent(Agent):
    name = "stock_power_hour_continuation"

    def __init__(
        self,
        min_relative_volume: float = 0.95,
        min_momentum_20: float = 0.003,
        min_momentum_5: float = 0.0,
        allowed_hours: tuple[int, ...] = (18, 19),
    ) -> None:
        self.min_relative_volume = min_relative_volume
        self.min_momentum_20 = min_momentum_20
        self.min_momentum_5 = min_momentum_5
        self.allowed_hours = allowed_hours

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        if feature.values.get("in_regular_session", 0.0) < 1.0:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
        hour = int(feature.values.get("hour_of_day", feature.timestamp.hour))
        if hour not in self.allowed_hours:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
        rel_vol = feature.values.get("relative_volume", 1.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        trend_strength = feature.values.get("trend_strength", 0.0)
        if rel_vol < self.min_relative_volume:
            return SignalEvent(feature.timestamp, self.name, feature.symbol, Side.FLAT, 0.0, {})
        if momentum_5 >= self.min_momentum_5 and momentum_20 >= self.min_momentum_20 and trend_strength > 0:
            side = Side.BUY
        elif momentum_5 <= -self.min_momentum_5 and momentum_20 <= -self.min_momentum_20 and trend_strength < 0:
            side = Side.SELL
        else:
            side = Side.FLAT
        return SignalEvent(
            feature.timestamp,
            self.name,
            feature.symbol,
            side,
            scaled_confidence(0.0, (abs(momentum_5), 140), (abs(momentum_20), 120), (rel_vol - 1.0, 50)),
            {"hour_of_day": float(hour)},
        )
