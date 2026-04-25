from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from quant_system.config import SystemConfig
from quant_system.integrations.mt5 import MT5AccountModeInfo, MT5Client, MT5Error, MT5PositionInfo
from quant_system.interpreter.app import build_market_interpreter_state
from quant_system.live.allocation import allocate_symbol_exposure as _live_allocate_symbol_exposure
from quant_system.live.interpreter_gate import (
    allocator_score as _live_allocator_score,
    candidate_archetype as _live_candidate_archetype,
    effective_risk_multiplier as _live_effective_risk_multiplier,
    interpreter_block_reason as _live_interpreter_block_reason,
    is_strategy_regime_blocked as _live_is_strategy_regime_blocked,
)
from quant_system.live.models import DeploymentStrategy, SymbolDeployment
from quant_system.live.orchestration import run_live_cycle as _live_run_live_cycle
from quant_system.live.order_sizing import (
    compute_order_size as _live_compute_order_size,
    estimated_stop_distance as _live_estimated_stop_distance,
    protective_order_prices as _live_protective_order_prices,
)
from quant_system.live.reconcile import (
    net_quantity as _live_net_quantity,
    reconcile_strategy as _live_reconcile_strategy,
)
from quant_system.live.strategy_eval import (
    build_strategy_config as _live_build_strategy_config,
    evaluate_strategy as _live_evaluate_strategy,
    feature_regime_label as _live_feature_regime_label,
    matches_regime as _live_matches_regime,
    matches_session as _live_matches_session,
    session_name_from_variant as _live_session_name_from_variant,
)
from quant_system.live.weekend_policy import (
    is_weekend_entry_block as _live_is_weekend_entry_block,
    should_force_weekend_flatten as _live_should_force_weekend_flatten,
    weekend_flatten_cutoff as _live_weekend_flatten_cutoff,
)
from quant_system.models import OrderRequest, Side
from quant_system.regime import RegimeSnapshot


LOGGER = logging.getLogger(__name__)


_weekend_flatten_cutoff = _live_weekend_flatten_cutoff


_is_weekend_entry_block = _live_is_weekend_entry_block


_should_force_weekend_flatten = _live_should_force_weekend_flatten


_candidate_archetype = _live_candidate_archetype


def _mt5_timeframe_from_variant(variant_label: str, default_timeframe: str) -> str:
    if variant_label.startswith("5m"):
        return "M5"
    if variant_label.startswith("15m"):
        return "M15"
    if variant_label.startswith("30m"):
        return "M30"
    if variant_label.startswith("4h"):
        return "H4"
    return default_timeframe


def _feature_regime_label(feature) -> str:
    return _live_feature_regime_label(feature)


def _matches_regime(feature, regime_filter_label: str) -> bool:
    return _live_matches_regime(feature, regime_filter_label)


def _session_name_from_variant(variant_label: str) -> str:
    return _live_session_name_from_variant(variant_label)


def _matches_session(feature, session_name: str) -> bool:
    return _live_matches_session(feature, session_name)


def _strategy_magic(base_magic: int, symbol: str, candidate_name: str) -> int:
    digest = hashlib.sha1(f"{symbol}|{candidate_name}".encode("utf-8")).hexdigest()
    suffix = int(digest[:6], 16) % 500000
    return base_magic * 10 + suffix


_effective_risk_multiplier = _live_effective_risk_multiplier


def _estimated_stop_distance(strategy_config: SystemConfig, latest_feature, reference_price: float) -> float:
    return _live_estimated_stop_distance(strategy_config, latest_feature, reference_price)


def _protective_order_prices(
    strategy_config: SystemConfig,
    latest_feature,
    reference_price: float,
    side: Side,
) -> tuple[float, float]:
    return _live_protective_order_prices(strategy_config, latest_feature, reference_price, side)


_is_strategy_regime_blocked = _live_is_strategy_regime_blocked


_interpreter_block_reason = _live_interpreter_block_reason


_allocator_score = _live_allocator_score


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
        self.relax_gates_for_mini_trades = bool(config.execution.mini_trades_enabled)

    def _strategy_portfolio_weight(self, strategy: DeploymentStrategy) -> float:
        return self.strategy_portfolio_weights.get(strategy.candidate_name, self.portfolio_weight)

    def _build_strategy_config(self, strategy: DeploymentStrategy) -> SystemConfig:
        return _live_build_strategy_config(self.config, self.deployment, strategy, _mt5_timeframe_from_variant)

    def _evaluate_strategy(
        self, client: MT5Client, strategy: DeploymentStrategy
    ) -> tuple[Side, float, datetime | None, RegimeSnapshot, str, object | None]:
        return _live_evaluate_strategy(client, strategy, self._build_strategy_config(strategy), self.deployment.symbol)

    def _allocate_symbol_exposure(self, evaluated: list[EvaluatedStrategy]) -> None:
        _live_allocate_symbol_exposure(evaluated)

    @staticmethod
    def _net_quantity(positions: list[MT5PositionInfo]) -> float:
        return _live_net_quantity(positions)

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
        return _live_reconcile_strategy(
            client=client,
            strategy=strategy,
            deployment=self.deployment,
            config=self.config,
            interpreter_state=self.interpreter_state,
            relax_gates_for_mini_trades=self.relax_gates_for_mini_trades,
            signal_side=signal_side,
            signal_timestamp=signal_timestamp,
            confidence=confidence,
            snapshot=snapshot,
            allocation_fraction=allocation_fraction,
            allocator_score=allocator_score,
            account_equity=account_equity,
            latest_feature=latest_feature,
            strategy_portfolio_weight=self._strategy_portfolio_weight(strategy),
            strategy_magic_fn=_strategy_magic,
            strategy_action_cls=StrategyAction,
            effective_risk_multiplier_fn=_effective_risk_multiplier,
            is_weekend_entry_block_fn=_is_weekend_entry_block,
            should_force_weekend_flatten_fn=_should_force_weekend_flatten,
            interpreter_block_reason_fn=_interpreter_block_reason,
            is_strategy_regime_blocked_fn=_is_strategy_regime_blocked,
            build_strategy_config_fn=self._build_strategy_config,
            compute_order_size_fn=_live_compute_order_size,
            protective_order_prices_fn=_protective_order_prices,
            bars_timestamp_now_fn=bars_timestamp_now,
            should_skip_duplicate=should_skip_duplicate,
        )

    def run_once(self, should_skip_duplicate: Callable[[StrategyAction], bool] | None = None) -> LiveRunResult:
        return _live_run_live_cycle(
            deployment=self.deployment,
            config=self.config,
            portfolio_weight=self.portfolio_weight,
            interpreter_state=self.interpreter_state,
            relax_gates_for_mini_trades=self.relax_gates_for_mini_trades,
            strategy_portfolio_weight_fn=self._strategy_portfolio_weight,
            build_strategy_config_fn=self._build_strategy_config,
            evaluate_strategy_fn=self._evaluate_strategy,
            allocate_symbol_exposure_fn=self._allocate_symbol_exposure,
            reconcile_strategy_fn=self._reconcile_strategy,
            net_quantity_fn=self._net_quantity,
            strategy_magic_fn=_strategy_magic,
            strategy_action_cls=StrategyAction,
            allocator_score_fn=_allocator_score,
            effective_risk_multiplier_fn=_effective_risk_multiplier,
            is_strategy_regime_blocked_fn=_is_strategy_regime_blocked,
            interpreter_block_reason_fn=_interpreter_block_reason,
            evaluated_strategy_cls=EvaluatedStrategy,
            live_run_result_cls=LiveRunResult,
            should_skip_duplicate=should_skip_duplicate,
        )


def bars_timestamp_now():
    from datetime import UTC, datetime

    return datetime.now(UTC)
