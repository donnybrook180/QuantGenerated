from __future__ import annotations

import copy
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from quant_system.catalog_runtime import build_agents_from_catalog_paths
from quant_system.config import SystemConfig
from quant_system.execution.engine import AgentCoordinator
from quant_system.integrations.mt5 import MT5AccountModeInfo, MT5Client, MT5Error, MT5PositionInfo
from quant_system.live.models import DeploymentStrategy, SymbolDeployment
from quant_system.models import OrderRequest, Side
from quant_system.symbol_research import _build_features_with_events, _configure_symbol_execution


LOGGER = logging.getLogger(__name__)


def _mt5_timeframe_from_variant(variant_label: str, default_timeframe: str) -> str:
    if variant_label.startswith("5m"):
        return "M5"
    if variant_label.startswith("15m"):
        return "M15"
    if variant_label.startswith("30m"):
        return "M30"
    return default_timeframe


def _feature_regime_label(feature) -> str:
    trend_strength = feature.values.get("trend_strength", 0.0)
    atr_proxy = feature.values.get("atr_proxy", 0.0)
    if trend_strength >= 0.001:
        trend_label = "trend_up"
    elif trend_strength <= -0.001:
        trend_label = "trend_down"
    else:
        trend_label = "trend_flat"

    if atr_proxy >= 0.003:
        vol_label = "vol_high"
    elif atr_proxy <= 0.0012:
        vol_label = "vol_low"
    else:
        vol_label = "vol_mid"
    return f"{trend_label}_{vol_label}"


def _matches_regime(feature, regime_filter_label: str) -> bool:
    if not regime_filter_label:
        return True
    label = _feature_regime_label(feature)
    if regime_filter_label.startswith("exclude:"):
        excluded = regime_filter_label.removeprefix("exclude:")
        if excluded.startswith("trend_") and excluded.count("_") == 1:
            return not label.startswith(excluded + "_")
        if excluded.startswith("vol_") and excluded.count("_") == 1:
            return not label.endswith("_" + excluded)
        return label != excluded
    if regime_filter_label.startswith("trend_") and regime_filter_label.count("_") == 1:
        return label.startswith(regime_filter_label + "_")
    if regime_filter_label.startswith("vol_") and regime_filter_label.count("_") == 1:
        return label.endswith("_" + regime_filter_label)
    return label == regime_filter_label


def _session_name_from_variant(variant_label: str) -> str:
    _, _, session_label = variant_label.partition("_")
    return session_label or "all"


def _matches_session(feature, session_name: str) -> bool:
    hour = int(feature.values.get("hour_of_day", feature.timestamp.hour))
    if session_name == "all":
        return True
    if session_name == "europe":
        return hour in set(range(7, 13))
    if session_name == "us":
        return hour in set(range(13, 21))
    if session_name == "overlap":
        return hour in set(range(12, 17))
    if session_name == "open":
        return feature.values.get("in_regular_session", 0.0) >= 1.0 and 0 <= feature.values.get("minutes_from_open", -1.0) < 90
    if session_name == "power":
        return hour in {18, 19}
    if session_name == "midday":
        return hour in {15, 16, 17}
    return True


def _strategy_magic(base_magic: int, symbol: str, candidate_name: str) -> int:
    digest = hashlib.sha1(f"{symbol}|{candidate_name}".encode("utf-8")).hexdigest()
    suffix = int(digest[:6], 16) % 500000
    return base_magic * 10 + suffix


@dataclass(slots=True)
class StrategyAction:
    candidate_name: str
    signal_side: Side
    signal_timestamp: datetime | None
    confidence: float
    current_quantity: float
    intended_action: str
    magic_number: int


@dataclass(slots=True)
class LiveRunResult:
    symbol: str
    broker_symbol: str
    account_mode_label: str
    strategy_isolation_supported: bool
    actions: list[StrategyAction]


class MT5LiveExecutor:
    def __init__(self, deployment: SymbolDeployment, config: SystemConfig) -> None:
        self.deployment = deployment
        self.config = config

    def _build_strategy_config(self, strategy: DeploymentStrategy) -> SystemConfig:
        strategy_config = copy.deepcopy(self.config)
        strategy_config.mt5.symbol = self.deployment.broker_symbol
        strategy_config.mt5.timeframe = _mt5_timeframe_from_variant(strategy.variant_label, strategy_config.mt5.timeframe)
        _configure_symbol_execution(strategy_config, self.deployment.symbol)
        for key, value in strategy.execution_overrides.items():
            setattr(strategy_config.execution, key, value)
        return strategy_config

    def _evaluate_strategy(self, client: MT5Client, strategy: DeploymentStrategy) -> tuple[Side, float, datetime | None]:
        strategy_config = self._build_strategy_config(strategy)
        bars = client.fetch_bars(bar_count=strategy_config.mt5.history_bars)
        features = _build_features_with_events(strategy_config, self.deployment.symbol, bars)
        session_name = _session_name_from_variant(strategy.variant_label)
        agents = build_agents_from_catalog_paths([strategy.code_path], strategy_config)
        coordinator = AgentCoordinator(agents, consensus_min_confidence=strategy_config.agents.consensus_min_confidence)
        last_side = Side.FLAT
        last_confidence = 0.0
        last_timestamp: datetime | None = None
        for feature in features:
            if not _matches_session(feature, session_name):
                continue
            if not _matches_regime(feature, strategy.regime_filter_label):
                continue
            context = coordinator.evaluate(feature)
            if context is None:
                continue
            last_side = context.side
            last_confidence = context.confidence
            last_timestamp = feature.timestamp
        return last_side, last_confidence, last_timestamp

    @staticmethod
    def _net_quantity(positions: list[MT5PositionInfo]) -> float:
        quantity = 0.0
        for position in positions:
            quantity += position.quantity if position.side == Side.BUY else -position.quantity
        return quantity

    def _reconcile_strategy(
        self,
        client: MT5Client,
        strategy: DeploymentStrategy,
        signal_side: Side,
        signal_timestamp: datetime | None,
        confidence: float,
        should_skip_duplicate: Callable[[StrategyAction], bool] | None = None,
    ) -> StrategyAction:
        magic_number = _strategy_magic(self.config.mt5.magic_number, self.deployment.symbol, strategy.candidate_name)
        positions = client.list_positions(magic_number=magic_number)
        current_quantity = self._net_quantity(positions)
        comment = strategy.candidate_name[:31]

        candidate_action = StrategyAction(strategy.candidate_name, signal_side, signal_timestamp, confidence, current_quantity, "hold", magic_number)
        if signal_side == Side.FLAT:
            return candidate_action

        order_size = self._build_strategy_config(strategy).execution.order_size * strategy.allocation_weight
        if order_size <= 0.0:
            candidate_action.intended_action = "skip_zero_size"
            return candidate_action

        desired_side = signal_side
        if current_quantity > 0 and desired_side == Side.BUY:
            candidate_action.intended_action = "hold_long"
            return candidate_action
        if current_quantity < 0 and desired_side == Side.SELL:
            candidate_action.intended_action = "hold_short"
            return candidate_action

        action_label = "open_long" if desired_side == Side.BUY else "open_short"
        candidate_action.intended_action = action_label
        if should_skip_duplicate is not None and should_skip_duplicate(candidate_action):
            candidate_action.intended_action = f"duplicate_skipped::{action_label}"
            return candidate_action

        for position in positions:
            if (position.side == Side.BUY and desired_side == Side.SELL) or (position.side == Side.SELL and desired_side == Side.BUY):
                if self.config.execution.live_trading_enabled:
                    client.send_market_order(
                        OrderRequest(
                            timestamp=bars_timestamp_now(),
                            symbol=self.deployment.broker_symbol,
                            side=Side.SELL if position.side == Side.BUY else Side.BUY,
                            quantity=position.quantity,
                            reason=f"close_{strategy.candidate_name}",
                            confidence=confidence,
                        ),
                        magic_number=magic_number,
                        comment=comment,
                        position_ticket=position.ticket,
                    )

        if self.config.execution.live_trading_enabled:
            client.send_market_order(
                OrderRequest(
                    timestamp=bars_timestamp_now(),
                    symbol=self.deployment.broker_symbol,
                    side=desired_side,
                    quantity=order_size,
                    reason=strategy.candidate_name,
                    confidence=confidence,
                    metadata={"strategy": strategy.candidate_name},
                ),
                magic_number=magic_number,
                comment=comment,
            )
        else:
            candidate_action.intended_action = f"dry_run_{action_label}"
        return candidate_action

    def run_once(self, should_skip_duplicate: Callable[[StrategyAction], bool] | None = None) -> LiveRunResult:
        actions: list[StrategyAction] = []
        account_mode_info: MT5AccountModeInfo | None = None

        bootstrap_config = self._build_strategy_config(self.deployment.strategies[0])
        bootstrap_client = MT5Client(bootstrap_config.mt5)
        try:
            bootstrap_client.initialize()
            account_mode_info = bootstrap_client.account_mode_info()
        finally:
            bootstrap_client.shutdown()

        if (
            account_mode_info is not None
            and not account_mode_info.strategy_isolation_supported
            and len(self.deployment.strategies) > 1
            and not self.config.mt5.allow_netting_multi_strategy
        ):
            for strategy in self.deployment.strategies:
                magic_number = _strategy_magic(self.config.mt5.magic_number, self.deployment.symbol, strategy.candidate_name)
                actions.append(
                    StrategyAction(
                        candidate_name=strategy.candidate_name,
                        signal_side=Side.FLAT,
                        signal_timestamp=None,
                        confidence=0.0,
                        current_quantity=0.0,
                        intended_action="netting_blocked_multi_strategy",
                        magic_number=magic_number,
                    )
                )
            return LiveRunResult(
                symbol=self.deployment.symbol,
                broker_symbol=self.deployment.broker_symbol,
                account_mode_label=account_mode_info.margin_mode_label,
                strategy_isolation_supported=account_mode_info.strategy_isolation_supported,
                actions=actions,
            )

        for strategy in self.deployment.strategies:
            strategy_config = self._build_strategy_config(strategy)
            client = MT5Client(strategy_config.mt5)
            try:
                client.initialize()
                signal_side, confidence, signal_timestamp = self._evaluate_strategy(client, strategy)
                actions.append(self._reconcile_strategy(client, strategy, signal_side, signal_timestamp, confidence, should_skip_duplicate))
            finally:
                client.shutdown()
        return LiveRunResult(
            symbol=self.deployment.symbol,
            broker_symbol=self.deployment.broker_symbol,
            account_mode_label=account_mode_info.margin_mode_label if account_mode_info is not None else "unknown",
            strategy_isolation_supported=account_mode_info.strategy_isolation_supported if account_mode_info is not None else False,
            actions=actions,
        )


def bars_timestamp_now():
    from datetime import UTC, datetime

    return datetime.now(UTC)
