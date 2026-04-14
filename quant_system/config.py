from __future__ import annotations

from dataclasses import dataclass, field
import os

from quant_system.env import load_dotenv


load_dotenv()


def _env_tuple(name: str, default: str = "") -> tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(part.strip() for part in raw.split(",") if part.strip())


@dataclass(frozen=True, slots=True)
class AIEndpointConfig:
    slot_name: str
    provider: str
    model: str
    api_key: str
    api_base_url: str
    openrouter_site_url: str | None = None
    openrouter_app_name: str | None = None


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
    symbol: str = field(default_factory=lambda: os.getenv("MARKET_DATA_SYMBOL", "SPY"))
    initial_cash: float = field(default_factory=lambda: float(os.getenv("ACCOUNT_INITIAL_CASH", "100000")))
    bar_interval_seconds: float = 0.0
    fee_bps: float = field(default_factory=lambda: float(os.getenv("EXECUTION_FEE_BPS", "1.0")))
    commission_per_unit: float = field(default_factory=lambda: float(os.getenv("EXECUTION_COMMISSION_PER_UNIT", "2.5")))
    slippage_bps: float = field(default_factory=lambda: float(os.getenv("EXECUTION_SLIPPAGE_BPS", "2.0")))
    spread_points: float = field(default_factory=lambda: float(os.getenv("EXECUTION_SPREAD_POINTS", "0.0")))
    contract_size: float = field(default_factory=lambda: float(os.getenv("EXECUTION_CONTRACT_SIZE", "1.0")))
    commission_mode: str = field(default_factory=lambda: os.getenv("EXECUTION_COMMISSION_MODE", "legacy").lower())
    commission_per_lot: float = field(default_factory=lambda: float(os.getenv("EXECUTION_COMMISSION_PER_LOT", "0.0")))
    commission_notional_pct: float = field(default_factory=lambda: float(os.getenv("EXECUTION_COMMISSION_NOTIONAL_PCT", "0.0")))
    overnight_cost_per_lot_day: float = field(default_factory=lambda: float(os.getenv("EXECUTION_OVERNIGHT_COST_PER_LOT_DAY", "0.0")))
    live_trading_enabled: bool = field(default_factory=lambda: os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true")
    order_size: float = field(default_factory=lambda: float(os.getenv("EXECUTION_ORDER_SIZE", "0.1")))
    risk_per_trade_pct: float = field(default_factory=lambda: float(os.getenv("EXECUTION_RISK_PER_TRADE_PCT", "0.015")))
    min_bars_between_trades: int = field(default_factory=lambda: int(os.getenv("EXECUTION_MIN_BARS_BETWEEN_TRADES", "8")))
    max_holding_bars: int = field(default_factory=lambda: int(os.getenv("EXECUTION_MAX_HOLDING_BARS", "24")))
    stop_loss_atr_multiple: float = field(default_factory=lambda: float(os.getenv("EXECUTION_STOP_LOSS_ATR_MULTIPLE", "1.2")))
    take_profit_atr_multiple: float = field(default_factory=lambda: float(os.getenv("EXECUTION_TAKE_PROFIT_ATR_MULTIPLE", "2.4")))
    break_even_atr_multiple: float = field(default_factory=lambda: float(os.getenv("EXECUTION_BREAK_EVEN_ATR_MULTIPLE", "1.0")))
    trailing_stop_atr_multiple: float = field(default_factory=lambda: float(os.getenv("EXECUTION_TRAILING_STOP_ATR_MULTIPLE", "1.1")))
    stale_breakout_bars: int = field(default_factory=lambda: int(os.getenv("EXECUTION_STALE_BREAKOUT_BARS", "6")))
    stale_breakout_atr_fraction: float = field(default_factory=lambda: float(os.getenv("EXECUTION_STALE_BREAKOUT_ATR_FRACTION", "0.2")))
    structure_exit_bars: int = field(default_factory=lambda: int(os.getenv("EXECUTION_STRUCTURE_EXIT_BARS", "4")))
    mini_trades_enabled: bool = field(default_factory=lambda: os.getenv("MINI_TRADES", "false").lower() == "true")
    mini_trades_order_size: float = field(default_factory=lambda: float(os.getenv("MINI_TRADES_ORDER_SIZE", "0.01")))
    mini_trades_risk_per_trade_pct: float = field(default_factory=lambda: float(os.getenv("MINI_TRADES_RISK_PER_TRADE_PCT", "0.0025")))
    mini_trades_min_bars_between_trades: int = field(default_factory=lambda: int(os.getenv("MINI_TRADES_MIN_BARS_BETWEEN_TRADES", "2")))
    mini_trades_max_holding_bars: int = field(default_factory=lambda: int(os.getenv("MINI_TRADES_MAX_HOLDING_BARS", "8")))
    mini_trades_take_profit_atr_multiple: float = field(default_factory=lambda: float(os.getenv("MINI_TRADES_TAKE_PROFIT_ATR_MULTIPLE", "1.1")))
    mini_trades_break_even_atr_multiple: float = field(default_factory=lambda: float(os.getenv("MINI_TRADES_BREAK_EVEN_ATR_MULTIPLE", "0.2")))
    mini_trades_trailing_stop_atr_multiple: float = field(default_factory=lambda: float(os.getenv("MINI_TRADES_TRAILING_STOP_ATR_MULTIPLE", "0.35")))
    mini_trades_stale_breakout_bars: int = field(default_factory=lambda: int(os.getenv("MINI_TRADES_STALE_BREAKOUT_BARS", "2")))
    mini_trades_stale_breakout_atr_fraction: float = field(default_factory=lambda: float(os.getenv("MINI_TRADES_STALE_BREAKOUT_ATR_FRACTION", "0.04")))
    mini_trades_structure_exit_bars: int = field(default_factory=lambda: int(os.getenv("MINI_TRADES_STRUCTURE_EXIT_BARS", "1")))


@dataclass(slots=True)
class AgentConfig:
    trend_fast_window: int = 10
    trend_slow_window: int = 30
    mean_reversion_window: int = 8
    mean_reversion_threshold: float = 0.004
    min_trend_strength: float = field(default_factory=lambda: float(os.getenv("AGENT_MIN_TREND_STRENGTH", "0.0015")))
    min_relative_volume: float = field(default_factory=lambda: float(os.getenv("AGENT_MIN_RELATIVE_VOLUME", "0.8")))
    consensus_min_confidence: float = field(default_factory=lambda: float(os.getenv("AGENT_CONSENSUS_MIN_CONFIDENCE", "0.55")))


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
    poll_seconds: int = field(default_factory=lambda: int(os.getenv("MT5_POLL_SECONDS", "60")))
    allow_netting_multi_strategy: bool = field(
        default_factory=lambda: os.getenv("MT5_ALLOW_NETTING_MULTI_STRATEGY", "false").lower() == "true"
    )
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
    data_symbol: str = field(default_factory=lambda: os.getenv("MARKET_DATA_SYMBOL", "SPY"))
    broker_symbol: str = field(default_factory=lambda: os.getenv("MT5_BROKER_SYMBOL", "SPY"))
    timeframe_label: str = field(default_factory=lambda: f"{os.getenv('MARKET_DATA_MULTIPLIER', '5')}_{os.getenv('MARKET_DATA_TIMESPAN', 'minute')}")
    active_profiles: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            part.strip() for part in os.getenv("ACTIVE_STRATEGY_PROFILES", "eurusd").split(",") if part.strip()
        )
        )


@dataclass(slots=True)
class SymbolResearchConfig:
    symbol: str = field(
        default_factory=lambda: os.getenv("SYMBOL_RESEARCH_SYMBOL") or os.getenv("MARKET_DATA_SYMBOL", "SPY")
    )
    broker_symbol: str = field(default_factory=lambda: os.getenv("SYMBOL_RESEARCH_BROKER_SYMBOL", ""))
    history_days: int = field(default_factory=lambda: int(os.getenv("SYMBOL_RESEARCH_HISTORY_DAYS", "180")))
    mode: str = field(default_factory=lambda: os.getenv("SYMBOL_RESEARCH_MODE", "auto").lower())
    source_preference: str = field(default_factory=lambda: os.getenv("SYMBOL_RESEARCH_SOURCE_PREFERENCE", "broker_first").lower())


@dataclass(slots=True)
class MarketDataConfig:
    symbol: str = field(default_factory=lambda: os.getenv("MARKET_DATA_SYMBOL", "SPY"))
    timespan: str = field(default_factory=lambda: os.getenv("MARKET_DATA_TIMESPAN", "minute"))
    multiplier: int = field(default_factory=lambda: int(os.getenv("MARKET_DATA_MULTIPLIER", "5")))
    history_days: int = field(default_factory=lambda: int(os.getenv("MARKET_DATA_HISTORY_DAYS", "30")))
    adjusted: bool = field(default_factory=lambda: os.getenv("MARKET_DATA_ADJUSTED", "true").lower() == "true")
    fetch_policy: str = field(default_factory=lambda: os.getenv("MARKET_DATA_FETCH_POLICY", "network_first").lower())
    max_retries: int = field(default_factory=lambda: int(os.getenv("MARKET_DATA_MAX_RETRIES", "4")))
    retry_backoff_seconds: float = field(default_factory=lambda: float(os.getenv("MARKET_DATA_RETRY_BACKOFF_SECONDS", "2.0")))
    profile_pause_seconds: float = field(default_factory=lambda: float(os.getenv("PROFILE_PAUSE_SECONDS", "1.5")))


@dataclass(slots=True)
class MacroCalendarConfig:
    enabled: bool = field(default_factory=lambda: os.getenv("MACRO_EVENT_CALENDAR_ENABLED", "true").lower() == "true")
    calendar_path: str = field(default_factory=lambda: os.getenv("MACRO_EVENT_CALENDAR_PATH", "artifacts/system/data/macro_calendar.csv"))
    pre_event_minutes: int = field(default_factory=lambda: int(os.getenv("MACRO_PRE_EVENT_MINUTES", "60")))
    post_event_minutes: int = field(default_factory=lambda: int(os.getenv("MACRO_POST_EVENT_MINUTES", "120")))


@dataclass(slots=True)
class FTMOEvaluationConfig:
    profit_target_pct: float = field(default_factory=lambda: float(os.getenv("FTMO_PROFIT_TARGET_PCT", "0.10")))
    min_win_rate_pct: float = field(default_factory=lambda: float(os.getenv("FTMO_MIN_WIN_RATE_PCT", "35.0")))
    min_profit_factor: float = field(default_factory=lambda: float(os.getenv("FTMO_MIN_PROFIT_FACTOR", "1.2")))
    min_trades: int = field(default_factory=lambda: int(os.getenv("FTMO_MIN_TRADES", "10")))


@dataclass(slots=True)
class AIConfig:
    enabled: bool = field(default_factory=lambda: os.getenv("AI_ENABLE", "true").lower() == "true")
    provider: str = field(default_factory=lambda: os.getenv("AI_PROVIDER", "openai").lower())
    model: str = field(default_factory=lambda: os.getenv("AI_MODEL", "gpt-5-mini"))
    api_key: str | None = field(
        default_factory=lambda: (
            os.getenv("AI_API_KEY")
            or os.getenv("AI_OPENAI_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("OPENROUTER_API_KEY")
        )
    )
    api_base_url: str = field(
        default_factory=lambda: os.getenv(
            "AI_API_BASE_URL",
            "https://openrouter.ai/api/v1" if os.getenv("AI_PROVIDER", "openai").lower() == "openrouter" else "https://api.openai.com/v1",
        )
    )
    openrouter_site_url: str | None = field(default_factory=lambda: os.getenv("OPENROUTER_SITE_URL"))
    openrouter_app_name: str | None = field(default_factory=lambda: os.getenv("OPENROUTER_APP_NAME", "QuantGenerated"))
    max_context_chars: int = field(default_factory=lambda: int(os.getenv("AI_MAX_CONTEXT_CHARS", "12000")))
    experiment_database_path: str = field(default_factory=lambda: os.getenv("AI_EXPERIMENT_DB_PATH", "quant_data.duckdb"))
    history_lookback: int = field(default_factory=lambda: int(os.getenv("AI_HISTORY_LOOKBACK", "8")))
    provider_order: tuple[str, ...] = field(default_factory=lambda: _env_tuple("AI_PROVIDER_ORDER"))

    def endpoint_pool(self) -> list[AIEndpointConfig]:
        endpoints: list[AIEndpointConfig] = []

        if self.provider_order:
            for slot_name in self.provider_order:
                provider_name, _, slot_index = slot_name.rpartition("_")
                provider = provider_name.lower()
                index = slot_index or "1"
                env_prefix = f"AI_{provider.upper()}_{index}"
                api_key = os.getenv(f"{env_prefix}_API_KEY")
                if not api_key:
                    continue
                model = os.getenv(f"{env_prefix}_MODEL", self.model)
                base_url = os.getenv(
                    f"{env_prefix}_API_BASE_URL",
                    "https://openrouter.ai/api/v1" if provider == "openrouter" else "https://api.openai.com/v1",
                )
                site_url = os.getenv(f"{env_prefix}_SITE_URL") or self.openrouter_site_url
                app_name = os.getenv(f"{env_prefix}_APP_NAME") or self.openrouter_app_name
                endpoints.append(
                    AIEndpointConfig(
                        slot_name=slot_name,
                        provider=provider,
                        model=model,
                        api_key=api_key,
                        api_base_url=base_url,
                        openrouter_site_url=site_url,
                        openrouter_app_name=app_name,
                    )
                )

        if endpoints:
            return endpoints

        if self.api_key and self.provider in {"openai", "openrouter"}:
            endpoints.append(
                AIEndpointConfig(
                    slot_name=f"{self.provider}_primary",
                    provider=self.provider,
                    model=self.model,
                    api_key=self.api_key,
                    api_base_url=self.api_base_url,
                    openrouter_site_url=self.openrouter_site_url,
                    openrouter_app_name=self.openrouter_app_name,
                )
            )
        return endpoints


@dataclass(slots=True)
class SystemConfig:
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    heartbeat: HeartbeatConfig = field(default_factory=HeartbeatConfig)
    agents: AgentConfig = field(default_factory=AgentConfig)
    optimization: OptimizationConfig = field(default_factory=OptimizationConfig)
    mt5: MT5Config = field(default_factory=MT5Config)
    market_data: MarketDataConfig = field(default_factory=MarketDataConfig)
    macro_calendar: MacroCalendarConfig = field(default_factory=MacroCalendarConfig)
    instrument: InstrumentConfig = field(default_factory=InstrumentConfig)
    symbol_research: SymbolResearchConfig = field(default_factory=SymbolResearchConfig)
    ftmo: FTMOEvaluationConfig = field(default_factory=FTMOEvaluationConfig)
    ai: AIConfig = field(default_factory=AIConfig)
