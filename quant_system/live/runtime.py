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
from quant_system.interpreter.app import build_market_interpreter_state
from quant_system.live.models import DeploymentStrategy, SymbolDeployment
from quant_system.models import OrderRequest, Side
from quant_system.regime import RegimeSnapshot, classify_regime, map_regime_label_to_unified, regime_allows_strategy


LOGGER = logging.getLogger(__name__)


def _candidate_archetype(strategy: DeploymentStrategy) -> str:
    name = strategy.candidate_name.lower()
    if "reclaim" in name:
        return "reclaim"
    if "reversion" in name:
        return "mean_reversion"
    if "breakout" in name:
        return "breakout"
    if "pullback" in name or "trend" in name:
        return "trend_pullback"
    return "unknown"


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


def _effective_risk_multiplier(snapshot: RegimeSnapshot, strategy: DeploymentStrategy) -> float:
    multiplier = snapshot.risk_multiplier
    if multiplier < strategy.min_risk_multiplier:
        multiplier = strategy.min_risk_multiplier
    if multiplier > strategy.max_risk_multiplier:
        multiplier = strategy.max_risk_multiplier
    return multiplier


def _estimated_stop_distance(strategy_config: SystemConfig, latest_feature, reference_price: float) -> float:
    if latest_feature is None:
        return 0.0
    atr_proxy = float(latest_feature.values.get("atr_proxy", 0.0) or 0.0)
    stop_multiple = float(strategy_config.execution.stop_loss_atr_multiple or 0.0)
    if atr_proxy <= 0.0 or stop_multiple <= 0.0 or reference_price <= 0.0:
        return 0.0
    return reference_price * atr_proxy * stop_multiple


def _is_strategy_regime_blocked(deployment: SymbolDeployment, strategy: DeploymentStrategy, snapshot: RegimeSnapshot) -> bool:
    return (
        bool(int(strategy.execution_overrides.get("tca_block_new_entries", 0) or 0))
        or
        (deployment.block_new_entries_in_event_risk and snapshot.regime_label == "event_risk")
        or snapshot.block_new_entries
        or snapshot.vol_percentile > deployment.max_symbol_vol_percentile
        or not regime_allows_strategy(
            snapshot,
            allowed_regimes=strategy.allowed_regimes,
            blocked_regimes=strategy.blocked_regimes,
            min_vol_percentile=strategy.min_vol_percentile,
            max_vol_percentile=strategy.max_vol_percentile,
        )
    )


def _interpreter_block_reason(strategy: DeploymentStrategy, interpreter_state) -> str:
    if interpreter_state is None:
        return ""
    archetype = _candidate_archetype(strategy)
    blocked = set(interpreter_state.blocked_archetypes or [])
    allowed = set(interpreter_state.allowed_archetypes or [])
    if interpreter_state.risk_posture == "defensive" and not allowed:
        return f"interpreter_defensive::{interpreter_state.no_trade_reason or interpreter_state.session_regime}"
    if archetype != "unknown" and archetype in blocked:
        return f"interpreter_blocked::{archetype}"
    if allowed and archetype != "unknown" and archetype not in allowed:
        return f"interpreter_not_allowed::{archetype}"
    return ""


def _allocator_score(strategy: DeploymentStrategy, signal_side: Side, confidence: float, snapshot: RegimeSnapshot) -> float:
    if signal_side == Side.FLAT:
        return 0.0
    unified_regime = map_regime_label_to_unified(snapshot.regime_label, snapshot.volatility_label, snapshot.structure_label)
    raw = confidence * max(_effective_risk_multiplier(snapshot, strategy), 0.0) * max(strategy.base_allocation_weight, 0.0)
    if strategy.allowed_regimes and (snapshot.regime_label in strategy.allowed_regimes or unified_regime in strategy.allowed_regimes):
        raw *= 1.15
    if strategy.regime_filter_label and strategy.regime_filter_label in {snapshot.regime_label, unified_regime}:
        raw *= 1.10
    return max(raw, 0.0)


@dataclass(slots=True)
class StrategyAction:
    candidate_name: str
    signal_side: Side
    signal_timestamp: datetime | None
    confidence: float
    current_quantity: float
    intended_action: str
    magic_number: int
    regime_label: str = ""
    vol_percentile: float = 0.0
    risk_multiplier: float = 0.0
    allocation_fraction: float = 0.0
    allocator_score: float = 0.0
    portfolio_weight: float = 1.0
    promotion_tier: str = "core"
    base_allocation_weight: float = 1.0
    effective_size_factor: float = 0.0
    risk_budget_cash: float = 0.0
    veto_reason: str = ""
    interpreter_reason: str = ""
    interpreter_bias: str = ""
    interpreter_confidence: float = 0.0


@dataclass(slots=True)
class LiveRunResult:
    symbol: str
    broker_symbol: str
    account_mode_label: str
    strategy_isolation_supported: bool
    actions: list[StrategyAction]
    regime_snapshot: RegimeSnapshot | None = None
    portfolio_weight: float = 1.0
    interpreter_state: object | None = None


@dataclass(slots=True)
class EvaluatedStrategy:
    strategy: DeploymentStrategy
    signal_side: Side
    signal_timestamp: datetime | None
    confidence: float
    snapshot: RegimeSnapshot
    allocator_score: float
    allocation_fraction: float = 0.0
    veto_reason: str = ""
    latest_feature: object | None = None


class MT5LiveExecutor:
    def __init__(
        self,
        deployment: SymbolDeployment,
        config: SystemConfig,
        portfolio_weight: float = 1.0,
        strategy_portfolio_weights: dict[str, float] | None = None,
    ) -> None:
        self.deployment = deployment
        self.config = config
        self.portfolio_weight = max(portfolio_weight, 0.0)
        self.strategy_portfolio_weights = {str(key): max(float(value), 0.0) for key, value in (strategy_portfolio_weights or {}).items()}
        self.interpreter_state = build_market_interpreter_state(deployment, config)

    def _strategy_portfolio_weight(self, strategy: DeploymentStrategy) -> float:
        return self.strategy_portfolio_weights.get(strategy.candidate_name, self.portfolio_weight)

    def _build_strategy_config(self, strategy: DeploymentStrategy) -> SystemConfig:
        from quant_system.live_support import configure_symbol_execution

        strategy_config = copy.deepcopy(self.config)
        strategy_config.mt5.symbol = self.deployment.broker_symbol
        strategy_config.mt5.timeframe = _mt5_timeframe_from_variant(strategy.variant_label, strategy_config.mt5.timeframe)
        configure_symbol_execution(strategy_config, self.deployment.symbol)
        for key, value in strategy.execution_overrides.items():
            setattr(strategy_config.execution, key, value)
        return strategy_config

    def _evaluate_strategy(
        self, client: MT5Client, strategy: DeploymentStrategy
    ) -> tuple[Side, float, datetime | None, RegimeSnapshot, str, object | None]:
        from quant_system.live_support import build_features_with_events

        strategy_config = self._build_strategy_config(strategy)
        bars = client.fetch_bars(bar_count=strategy_config.mt5.history_bars)
        features = build_features_with_events(strategy_config, self.deployment.symbol, bars)
        latest_feature = features[-1] if features else None
        snapshot = classify_regime(self.deployment.symbol, bars, latest_feature)
        session_name = _session_name_from_variant(strategy.variant_label)
        agents = build_agents_from_catalog_paths([strategy.code_path], strategy_config)
        coordinator = AgentCoordinator(agents, consensus_min_confidence=strategy_config.agents.consensus_min_confidence)
        last_side = Side.FLAT
        last_confidence = 0.0
        last_timestamp: datetime | None = None
        last_veto_reason = ""
        for feature in features:
            if not _matches_session(feature, session_name):
                continue
            if not _matches_regime(feature, strategy.regime_filter_label):
                continue
            context = coordinator.evaluate(feature)
            if context is None:
                if coordinator.last_veto_reason:
                    last_veto_reason = coordinator.last_veto_reason
                continue
            last_side = context.side
            last_confidence = context.confidence
            last_timestamp = feature.timestamp
            last_veto_reason = ""
        return last_side, last_confidence, last_timestamp, snapshot, last_veto_reason, latest_feature

    def _allocate_symbol_exposure(self, evaluated: list[EvaluatedStrategy]) -> None:
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
            # If both sides are active, require the dominant side to clearly win.
            if opposing_total > 0.0 and dominant_total < opposing_total * 1.10:
                continue
            item.allocation_fraction = item.allocator_score / dominant_total

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
        snapshot: RegimeSnapshot,
        allocation_fraction: float,
        allocator_score: float,
        account_equity: float,
        latest_feature,
        should_skip_duplicate: Callable[[StrategyAction], bool] | None = None,
    ) -> StrategyAction:
        magic_number = _strategy_magic(self.config.mt5.magic_number, self.deployment.symbol, strategy.candidate_name)
        positions = client.list_positions(magic_number=magic_number)
        current_quantity = self._net_quantity(positions)
        comment = strategy.candidate_name[:31]

        candidate_action = StrategyAction(
            strategy.candidate_name,
            signal_side,
            signal_timestamp,
            confidence,
            current_quantity,
            "hold",
            magic_number,
            regime_label=snapshot.regime_label,
            vol_percentile=snapshot.vol_percentile,
            risk_multiplier=_effective_risk_multiplier(snapshot, strategy),
            allocation_fraction=allocation_fraction,
            allocator_score=allocator_score,
            portfolio_weight=self._strategy_portfolio_weight(strategy),
            promotion_tier=strategy.promotion_tier,
            base_allocation_weight=strategy.base_allocation_weight,
            risk_budget_cash=0.0,
            veto_reason="",
            interpreter_reason="",
            interpreter_bias=self.interpreter_state.directional_bias,
            interpreter_confidence=self.interpreter_state.confidence,
        )
        if signal_side == Side.FLAT:
            return candidate_action

        interpreter_reason = _interpreter_block_reason(strategy, self.interpreter_state)
        if current_quantity == 0.0 and interpreter_reason:
            candidate_action.intended_action = f"policy_blocked::{interpreter_reason}"
            candidate_action.interpreter_reason = interpreter_reason
            return candidate_action

        if current_quantity == 0.0 and _is_strategy_regime_blocked(self.deployment, strategy, snapshot):
            candidate_action.intended_action = f"regime_blocked::{snapshot.regime_label}"
            return candidate_action

        candidate_action.effective_size_factor = (
            candidate_action.portfolio_weight
            * allocation_fraction
            * candidate_action.risk_multiplier
        )
        strategy_config = self._build_strategy_config(strategy)
        candidate_action.risk_budget_cash = (
            account_equity
            * max(strategy_config.execution.risk_per_trade_pct, 0.0)
            * candidate_action.effective_size_factor
        )
        market_snapshot = client.market_snapshot()
        reference_price = market_snapshot.ask if desired_side == Side.BUY else market_snapshot.bid
        stop_distance = _estimated_stop_distance(strategy_config, latest_feature, reference_price)
        order_size = 0.0
        if candidate_action.risk_budget_cash > 0.0 and stop_distance > 0.0 and strategy_config.execution.contract_size > 0.0:
            order_size = candidate_action.risk_budget_cash / (stop_distance * strategy_config.execution.contract_size)
        else:
            order_size = (
                strategy_config.execution.order_size
                * candidate_action.effective_size_factor
            )
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
        regime_snapshot: RegimeSnapshot | None = None
        evaluated: list[EvaluatedStrategy] = []
        client_cache: dict[str, MT5Client] = {}

        def _client_for_strategy(strategy: DeploymentStrategy) -> MT5Client:
            strategy_config = self._build_strategy_config(strategy)
            cache_key = f"{strategy_config.mt5.symbol}|{strategy_config.mt5.timeframe}"
            client = client_cache.get(cache_key)
            if client is None:
                client = MT5Client(strategy_config.mt5)
                client.initialize()
                client_cache[cache_key] = client
            return client

        try:
            bootstrap_client = _client_for_strategy(self.deployment.strategies[0])
            account_mode_info = bootstrap_client.account_mode_info()
            account_snapshot = bootstrap_client.account_snapshot()
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
                            regime_label="",
                            vol_percentile=0.0,
                            risk_multiplier=0.0,
                            allocation_fraction=0.0,
                            allocator_score=0.0,
                            portfolio_weight=self._strategy_portfolio_weight(item.strategy),
                        )
                    )
                return LiveRunResult(
                    symbol=self.deployment.symbol,
                    broker_symbol=self.deployment.broker_symbol,
                    account_mode_label=account_mode_info.margin_mode_label,
                    strategy_isolation_supported=account_mode_info.strategy_isolation_supported,
                    actions=actions,
                    regime_snapshot=regime_snapshot,
                    portfolio_weight=self.portfolio_weight,
                )

            for strategy in self.deployment.strategies:
                client = _client_for_strategy(strategy)
                signal_side, confidence, signal_timestamp, snapshot, veto_reason, latest_feature = self._evaluate_strategy(client, strategy)
                if self.interpreter_state.regime_snapshot is not None:
                    snapshot = self.interpreter_state.regime_snapshot
                if regime_snapshot is None:
                    regime_snapshot = snapshot
                interpreter_reason = _interpreter_block_reason(strategy, self.interpreter_state)
                score = 0.0 if (_is_strategy_regime_blocked(self.deployment, strategy, snapshot) or interpreter_reason) else _allocator_score(
                    strategy, signal_side, confidence, snapshot
                )
                evaluated.append(
                    EvaluatedStrategy(
                        strategy=strategy,
                        signal_side=signal_side,
                        signal_timestamp=signal_timestamp,
                        confidence=confidence,
                        snapshot=snapshot,
                        allocator_score=score,
                        veto_reason=interpreter_reason or veto_reason,
                        latest_feature=latest_feature,
                    )
                )

            self._allocate_symbol_exposure(evaluated)

            for item in evaluated:
                client = _client_for_strategy(item.strategy)
                if item.signal_side != Side.FLAT and item.allocator_score > 0.0 and item.allocation_fraction <= 0.0:
                    magic_number = _strategy_magic(self.config.mt5.magic_number, self.deployment.symbol, item.strategy.candidate_name)
                    current_quantity = self._net_quantity(client.list_positions(magic_number=magic_number))
                    actions.append(
                        StrategyAction(
                            candidate_name=item.strategy.candidate_name,
                            signal_side=item.signal_side,
                            signal_timestamp=item.signal_timestamp,
                            confidence=item.confidence,
                            current_quantity=current_quantity,
                            intended_action="allocator_blocked_opposing_side",
                            magic_number=magic_number,
                            regime_label=item.snapshot.regime_label,
                            vol_percentile=item.snapshot.vol_percentile,
                            risk_multiplier=_effective_risk_multiplier(item.snapshot, item.strategy),
                            allocation_fraction=0.0,
                            allocator_score=item.allocator_score,
                            portfolio_weight=self.portfolio_weight,
                            promotion_tier=item.strategy.promotion_tier,
                            base_allocation_weight=item.strategy.base_allocation_weight,
                            effective_size_factor=0.0,
                            risk_budget_cash=0.0,
                            veto_reason=item.veto_reason,
                            interpreter_reason=_interpreter_block_reason(item.strategy, self.interpreter_state),
                            interpreter_bias=self.interpreter_state.directional_bias,
                            interpreter_confidence=self.interpreter_state.confidence,
                        )
                    )
                    continue
                action = self._reconcile_strategy(
                    client,
                    item.strategy,
                    item.signal_side,
                    item.signal_timestamp,
                    item.confidence,
                    item.snapshot,
                    item.allocation_fraction if item.allocation_fraction > 0.0 else item.strategy.allocation_weight,
                    item.allocator_score,
                    account_snapshot.equity,
                    item.latest_feature,
                    should_skip_duplicate,
                )
                action.veto_reason = item.veto_reason
                if not action.interpreter_reason:
                    action.interpreter_reason = _interpreter_block_reason(item.strategy, self.interpreter_state)
                action.interpreter_bias = self.interpreter_state.directional_bias
                action.interpreter_confidence = self.interpreter_state.confidence
                actions.append(action)
            return LiveRunResult(
                symbol=self.deployment.symbol,
                broker_symbol=self.deployment.broker_symbol,
                account_mode_label=account_mode_info.margin_mode_label if account_mode_info is not None else "unknown",
                strategy_isolation_supported=account_mode_info.strategy_isolation_supported if account_mode_info is not None else False,
                actions=actions,
                regime_snapshot=regime_snapshot,
                portfolio_weight=self.portfolio_weight,
                interpreter_state=self.interpreter_state,
            )
        finally:
            for client in client_cache.values():
                try:
                    client.shutdown()
                except Exception:
                    pass


def bars_timestamp_now():
    from datetime import UTC, datetime

    return datetime.now(UTC)
