from __future__ import annotations

from dataclasses import dataclass, field
import os

from quant_system.env import load_dotenv


load_dotenv()


@dataclass(slots=True)
class RiskConfig:
    max_daily_loss_pct: float = field(default_factory=lambda: float(os.getenv("RISK_MAX_DAILY_LOSS_PCT", "0.05")))
    max_total_drawdown_pct: float = field(default_factory=lambda: float(os.getenv("RISK_MAX_TOTAL_DRAWDOWN_PCT", "0.10")))
    cooldown_hours: int = 24
    max_position_size: float = field(default_factory=lambda: float(os.getenv("RISK_MAX_POSITION_SIZE", "1.0")))
    max_volatility: float = field(default_factory=lambda: float(os.getenv("RISK_MAX_VOLATILITY", "0.015")))
    min_equity_buffer_pct: float = field(default_factory=lambda: float(os.getenv("RISK_MIN_EQUITY_BUFFER_PCT", "0.005")))


@dataclass(slots=True)
class HeartbeatConfig:
    interval_seconds: int = 60
    stale_after_seconds: int = 90


@dataclass(slots=True)
class ExecutionConfig:
    symbol: str = field(default_factory=lambda: os.getenv("POLYGON_DATA_SYMBOL", "SPY"))
    initial_cash: float = field(default_factory=lambda: float(os.getenv("ACCOUNT_INITIAL_CASH", "100000")))
    bar_interval_seconds: float = 0.0
    fee_bps: float = field(default_factory=lambda: float(os.getenv("EXECUTION_FEE_BPS", "1.0")))
    commission_per_unit: float = field(default_factory=lambda: float(os.getenv("EXECUTION_COMMISSION_PER_UNIT", "2.5")))
    slippage_bps: float = field(default_factory=lambda: float(os.getenv("EXECUTION_SLIPPAGE_BPS", "2.0")))
    live_trading_enabled: bool = field(default_factory=lambda: os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true")
    order_size: float = field(default_factory=lambda: float(os.getenv("EXECUTION_ORDER_SIZE", "0.1")))
    min_bars_between_trades: int = field(default_factory=lambda: int(os.getenv("EXECUTION_MIN_BARS_BETWEEN_TRADES", "8")))
    max_holding_bars: int = field(default_factory=lambda: int(os.getenv("EXECUTION_MAX_HOLDING_BARS", "24")))


@dataclass(slots=True)
class AgentConfig:
    trend_fast_window: int = 10
    trend_slow_window: int = 30
    mean_reversion_window: int = 8
    mean_reversion_threshold: float = 0.004
    min_trend_strength: float = field(default_factory=lambda: float(os.getenv("AGENT_MIN_TREND_STRENGTH", "0.0015")))
    min_relative_volume: float = field(default_factory=lambda: float(os.getenv("AGENT_MIN_RELATIVE_VOLUME", "0.8")))
    consensus_min_confidence: float = field(default_factory=lambda: float(os.getenv("AGENT_CONSENSUS_MIN_CONFIDENCE", "1.1")))


@dataclass(slots=True)
class OptimizationConfig:
    train_bars: int = 80
    test_bars: int = 20
    step_bars: int = 20
    n_trials: int = 30
    sampler_seed: int = 42
    search_space: dict[str, tuple[int, int]] = field(
        default_factory=lambda: {
            "trend_fast_window": (5, 20),
            "trend_slow_window": (20, 60),
            "mean_reversion_window": (4, 15),
        }
    )


@dataclass(slots=True)
class MT5Config:
    symbol: str = field(default_factory=lambda: os.getenv("MT5_BROKER_SYMBOL", "SPY"))
    timeframe: str = field(default_factory=lambda: os.getenv("MT5_TIMEFRAME", "M5"))
    history_bars: int = field(default_factory=lambda: int(os.getenv("MT5_HISTORY_BARS", "500")))
    terminal_path: str | None = field(default_factory=lambda: os.getenv("MT5_TERMINAL_PATH"))
    login: int | None = field(default_factory=lambda: int(value) if (value := os.getenv("MT5_LOGIN")) else None)
    password: str | None = field(default_factory=lambda: os.getenv("MT5_PASSWORD"))
    server: str | None = field(default_factory=lambda: os.getenv("MT5_SERVER"))
    magic_number: int = 260405
    deviation: int = 10
    database_path: str = "quant_data.duckdb"


@dataclass(slots=True)
class InstrumentConfig:
    profile_name: str = field(default_factory=lambda: os.getenv("INSTRUMENT_PROFILE", "ftmo_us_equities"))
    data_symbol: str = field(default_factory=lambda: os.getenv("POLYGON_DATA_SYMBOL", "SPY"))
    broker_symbol: str = field(default_factory=lambda: os.getenv("MT5_BROKER_SYMBOL", "SPY"))
    timeframe_label: str = field(default_factory=lambda: f"{os.getenv('POLYGON_MULTIPLIER', '5')}_{os.getenv('POLYGON_TIMESPAN', 'minute')}")


@dataclass(slots=True)
class PolygonConfig:
    api_key: str | None = field(default_factory=lambda: os.getenv("POLYGON_API_KEY"))
    symbol: str = field(default_factory=lambda: os.getenv("POLYGON_DATA_SYMBOL", "SPY"))
    timespan: str = field(default_factory=lambda: os.getenv("POLYGON_TIMESPAN", "minute"))
    multiplier: int = field(default_factory=lambda: int(os.getenv("POLYGON_MULTIPLIER", "5")))
    history_days: int = field(default_factory=lambda: int(os.getenv("POLYGON_HISTORY_DAYS", "30")))
    adjusted: bool = field(default_factory=lambda: os.getenv("POLYGON_ADJUSTED", "true").lower() == "true")


@dataclass(slots=True)
class FTMOEvaluationConfig:
    profit_target_pct: float = field(default_factory=lambda: float(os.getenv("FTMO_PROFIT_TARGET_PCT", "0.10")))
    min_win_rate_pct: float = field(default_factory=lambda: float(os.getenv("FTMO_MIN_WIN_RATE_PCT", "35.0")))
    min_profit_factor: float = field(default_factory=lambda: float(os.getenv("FTMO_MIN_PROFIT_FACTOR", "1.2")))
    min_trades: int = field(default_factory=lambda: int(os.getenv("FTMO_MIN_TRADES", "10")))


@dataclass(slots=True)
class SystemConfig:
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    heartbeat: HeartbeatConfig = field(default_factory=HeartbeatConfig)
    agents: AgentConfig = field(default_factory=AgentConfig)
    optimization: OptimizationConfig = field(default_factory=OptimizationConfig)
    mt5: MT5Config = field(default_factory=MT5Config)
    polygon: PolygonConfig = field(default_factory=PolygonConfig)
    instrument: InstrumentConfig = field(default_factory=InstrumentConfig)
    ftmo: FTMOEvaluationConfig = field(default_factory=FTMOEvaluationConfig)
