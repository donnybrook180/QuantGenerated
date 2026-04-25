from __future__ import annotations

from quant_system.agents.base import Agent
from quant_system.agents.common import RollingCloseState, directional_metadata, scaled_confidence
from quant_system.models import FeatureVector, Side, SignalEvent


class US500FlatHighReversalAgent(Agent):
    name = "us500_flat_high_reversal"

    def __init__(
        self,
        max_abs_trend_strength: float = 0.00055,
        min_relative_volume: float = 0.82,
        allowed_hours: set[int] | None = None,
        min_z_score: float = 0.85,
    ) -> None:
        self.max_abs_trend_strength = max_abs_trend_strength
        self.min_relative_volume = min_relative_volume
        self.allowed_hours = allowed_hours or {15, 16, 17}
        self.min_z_score = min_z_score

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        session_position = feature.values.get("session_position", 0.5)
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        opening_window = feature.values.get("opening_window", 0.0)
        closing_window = feature.values.get("closing_window", 0.0)
        hour = int(feature.values.get("hour_of_day", 0.0))

        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or closing_window > 0.0
            or hour not in self.allowed_hours
            or relative_volume < self.min_relative_volume
        ):
            side = Side.FLAT
        elif (
            abs(trend_strength) <= self.max_abs_trend_strength
            and z_score >= self.min_z_score
            and vwap_distance >= 0.0002
            and momentum_5 <= 0.00025
            and momentum_20 <= 0.00035
            and 0.28 <= session_position <= 0.82
        ):
            side = Side.SELL
        elif z_score < 0.15 or vwap_distance < -0.0002 or momentum_5 < -0.00045:
            side = Side.BUY
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.16,
            (max(z_score - self.min_z_score, 0.0), 0.35),
            (max(vwap_distance, 0.0), 220),
            (max(self.max_abs_trend_strength - abs(trend_strength), 0.0), 800),
        )
        metadata = directional_metadata(
            side,
            short_entry=True,
            short_exit=True,
            trend_strength=trend_strength,
            z_score_20=z_score,
            vwap_distance=vwap_distance,
            session_position=session_position,
            hour_of_day=float(hour),
        )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, side, confidence if side != Side.FLAT else 0.0, metadata)


class US500FlatTapeMeanReversionAgent(Agent):
    name = "us500_flat_tape_mean_reversion"

    def __init__(
        self,
        lookback: int = 8,
        max_abs_trend_strength: float = 0.00055,
        min_relative_volume: float = 0.78,
        allowed_hours: set[int] | None = None,
        min_abs_z_score: float = 0.9,
    ) -> None:
        self.state = RollingCloseState(lookback)
        self.max_abs_trend_strength = max_abs_trend_strength
        self.min_relative_volume = min_relative_volume
        self.allowed_hours = allowed_hours or {15, 16, 17}
        self.min_abs_z_score = min_abs_z_score

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        close = feature.values["close"]
        self.state.append(close)
        if not self.state.ready:
            return None

        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        session_position = feature.values.get("session_position", 0.5)
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        opening_window = feature.values.get("opening_window", 0.0)
        closing_window = feature.values.get("closing_window", 0.0)
        hour = int(feature.values.get("hour_of_day", 0.0))

        rolling_mean = self.state.mean()
        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or closing_window > 0.0
            or hour not in self.allowed_hours
            or relative_volume < self.min_relative_volume
        ):
            side = Side.FLAT
        elif (
            abs(trend_strength) <= self.max_abs_trend_strength
            and abs(momentum_20) <= 0.00045
            and z_score >= self.min_abs_z_score
            and vwap_distance >= 0.00035
            and momentum_5 <= 0.0002
            and 0.25 <= session_position <= 0.85
            and close >= rolling_mean
        ):
            side = Side.SELL
        elif (
            abs(trend_strength) <= self.max_abs_trend_strength
            and abs(momentum_20) <= 0.00045
            and z_score <= -self.min_abs_z_score
            and vwap_distance <= -0.00035
            and momentum_5 >= -0.0002
            and 0.25 <= session_position <= 0.85
            and close <= rolling_mean
        ):
            side = Side.BUY
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.14,
            (max(abs(z_score) - self.min_abs_z_score, 0.0), 0.28),
            (max(abs(vwap_distance) - 0.00035, 0.0), 220),
            (max(self.max_abs_trend_strength - abs(trend_strength), 0.0), 900),
        )
        metadata = directional_metadata(
            side,
            short_entry=side == Side.SELL,
            short_exit=side == Side.BUY,
            trend_strength=trend_strength,
            z_score_20=z_score,
            vwap_distance=vwap_distance,
            rolling_mean=rolling_mean,
            session_position=session_position,
            hour_of_day=float(hour),
        )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, side, confidence if side != Side.FLAT else 0.0, metadata)


class US500OvernightGapFadeAgent(Agent):
    name = "us500_overnight_gap_fade"

    def __init__(
        self,
        min_gap_pct: float = 0.0015,
        max_abs_trend_strength: float = 0.0007,
        min_relative_volume: float = 0.82,
    ) -> None:
        self.min_gap_pct = min_gap_pct
        self.max_abs_trend_strength = max_abs_trend_strength
        self.min_relative_volume = min_relative_volume

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        opening_window = feature.values.get("opening_window", 0.0)
        morning_session = feature.values.get("morning_session", 0.0)
        midday_session = feature.values.get("midday_session", 0.0)
        opening_gap_pct = feature.values.get("opening_gap_pct", 0.0)
        distance_to_prior_day_close = feature.values.get("distance_to_prior_day_close", 0.0)
        distance_to_overnight_high = feature.values.get("distance_to_overnight_high", 0.0)
        distance_to_overnight_low = feature.values.get("distance_to_overnight_low", 0.0)

        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or (morning_session < 1.0 and midday_session < 1.0)
            or relative_volume < self.min_relative_volume
        ):
            side = Side.FLAT
        elif (
            opening_gap_pct >= self.min_gap_pct
            and abs(trend_strength) <= self.max_abs_trend_strength
            and z_score >= 0.9
            and vwap_distance >= 0.0004
            and momentum_5 <= 0.0002
            and distance_to_prior_day_close > 0.0
            and distance_to_overnight_high <= 0.0001
        ):
            side = Side.SELL
        elif (
            opening_gap_pct <= -self.min_gap_pct
            and abs(trend_strength) <= self.max_abs_trend_strength
            and z_score <= -0.9
            and vwap_distance <= -0.0004
            and momentum_5 >= -0.0002
            and distance_to_prior_day_close < 0.0
            and distance_to_overnight_low >= -0.0001
        ):
            side = Side.BUY
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.16,
            (max(abs(opening_gap_pct) - self.min_gap_pct, 0.0), 120),
            (max(abs(z_score) - 0.9, 0.0), 0.25),
            (max(abs(vwap_distance) - 0.0004, 0.0), 180),
        )
        metadata = directional_metadata(
            side,
            short_entry=side == Side.SELL,
            short_exit=side == Side.BUY,
            opening_gap_pct=opening_gap_pct,
            distance_to_prior_day_close=distance_to_prior_day_close,
            distance_to_overnight_high=distance_to_overnight_high,
            distance_to_overnight_low=distance_to_overnight_low,
            vwap_distance=vwap_distance,
        )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, side, confidence if side != Side.FLAT else 0.0, metadata)


class US500FailedBreakdownReclaimAgent(Agent):
    name = "us500_failed_breakdown_reclaim"

    def __init__(
        self,
        max_abs_trend_strength: float = 0.0009,
        min_relative_volume: float = 0.82,
    ) -> None:
        self.max_abs_trend_strength = max_abs_trend_strength
        self.min_relative_volume = min_relative_volume

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        session_position = feature.values.get("session_position", 0.5)
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        opening_window = feature.values.get("opening_window", 0.0)
        closing_window = feature.values.get("closing_window", 0.0)
        morning_session = feature.values.get("morning_session", 0.0)
        midday_session = feature.values.get("midday_session", 0.0)
        failed_prior = feature.values.get("failed_break_below_prior_day_low", 0.0)
        failed_overnight = feature.values.get("failed_break_below_overnight_low", 0.0)
        reclaimed_prior = feature.values.get("reclaimed_prior_day_low", 0.0)
        reclaimed_overnight = feature.values.get("reclaimed_overnight_low", 0.0)

        trigger = max(failed_prior, failed_overnight, reclaimed_prior, reclaimed_overnight)

        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or closing_window > 0.0
            or (morning_session < 1.0 and midday_session < 1.0)
            or relative_volume < self.min_relative_volume
        ):
            side = Side.FLAT
        elif (
            trigger > 0.0
            and abs(trend_strength) <= self.max_abs_trend_strength
            and z_score <= -0.2
            and momentum_5 >= -0.0006
            and momentum_20 >= -0.0005
            and vwap_distance >= -0.0012
            and 0.15 <= session_position <= 0.65
        ):
            side = Side.BUY
        elif trend_strength < -0.0012 or momentum_20 < -0.001 or vwap_distance < -0.002:
            side = Side.SELL
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.16,
            (trigger, 0.35),
            (max(-z_score, 0.0), 0.12),
            (max(self.max_abs_trend_strength - abs(trend_strength), 0.0), 700),
        )
        metadata = directional_metadata(
            side,
            short_entry=False,
            short_exit=True,
            failed_break_below_prior_day_low=failed_prior,
            failed_break_below_overnight_low=failed_overnight,
            reclaimed_prior_day_low=reclaimed_prior,
            reclaimed_overnight_low=reclaimed_overnight,
            trend_strength=trend_strength,
            z_score_20=z_score,
            vwap_distance=vwap_distance,
        )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, side, confidence if side != Side.FLAT else 0.0, metadata)


class US500FailedUpsideRejectShortAgent(Agent):
    name = "us500_failed_upside_reject_short"

    def __init__(
        self,
        min_negative_trend: float = 0.00035,
        min_relative_volume: float = 0.82,
    ) -> None:
        self.min_negative_trend = min_negative_trend
        self.min_relative_volume = min_relative_volume

    def on_feature(self, feature: FeatureVector) -> SignalEvent | None:
        trend_strength = feature.values.get("trend_strength", 0.0)
        momentum_5 = feature.values.get("momentum_5", 0.0)
        momentum_20 = feature.values.get("momentum_20", 0.0)
        z_score = feature.values.get("z_score_20", 0.0)
        vwap_distance = feature.values.get("vwap_distance", 0.0)
        session_position = feature.values.get("session_position", 0.5)
        relative_volume = feature.values.get("relative_volume", 1.0)
        in_regular_session = feature.values.get("in_regular_session", 0.0)
        opening_window = feature.values.get("opening_window", 0.0)
        closing_window = feature.values.get("closing_window", 0.0)
        morning_session = feature.values.get("morning_session", 0.0)
        midday_session = feature.values.get("midday_session", 0.0)
        failed_prior = feature.values.get("failed_break_above_prior_day_high", 0.0)
        failed_overnight = feature.values.get("failed_break_above_overnight_high", 0.0)
        reclaimed_prior = feature.values.get("reclaimed_prior_day_high", 0.0)
        reclaimed_overnight = feature.values.get("reclaimed_overnight_high", 0.0)

        trigger = max(failed_prior, failed_overnight, reclaimed_prior, reclaimed_overnight)

        if (
            in_regular_session < 1.0
            or opening_window > 0.0
            or closing_window > 0.0
            or (morning_session < 1.0 and midday_session < 1.0)
            or relative_volume < self.min_relative_volume
        ):
            side = Side.FLAT
        elif (
            trigger > 0.0
            and trend_strength <= -self.min_negative_trend
            and momentum_20 <= 0.00015
            and momentum_5 <= 0.0005
            and z_score >= -0.1
            and vwap_distance <= 0.0008
            and session_position <= 0.78
        ):
            side = Side.SELL
        elif trend_strength > 0.0004 or momentum_20 > 0.00035 or z_score <= -1.0:
            side = Side.BUY
        else:
            side = Side.FLAT

        confidence = scaled_confidence(
            0.18,
            (trigger, 0.34),
            (max(-trend_strength, 0.0), 170),
            (max(z_score, 0.0), 0.14),
        )
        metadata = directional_metadata(
            side,
            short_entry=side == Side.SELL,
            short_exit=side == Side.BUY,
            failed_break_above_prior_day_high=failed_prior,
            failed_break_above_overnight_high=failed_overnight,
            reclaimed_prior_day_high=reclaimed_prior,
            reclaimed_overnight_high=reclaimed_overnight,
            trend_strength=trend_strength,
            z_score_20=z_score,
            vwap_distance=vwap_distance,
        )
        return SignalEvent(feature.timestamp, self.name, feature.symbol, side, confidence if side != Side.FLAT else 0.0, metadata)
