from __future__ import annotations

from dataclasses import dataclass

from quant_system.research.stock_selector import StockSelectorRow


@dataclass(frozen=True, slots=True)
class StockPlaybookCandidate:
    symbol: str
    broker_symbol: str
    selector_score: float
    playbook: str
    playbook_score: float
    reasons: tuple[str, ...]
    allowed_agent_prefixes: tuple[str, ...]


def classify_stock_playbook(row: StockSelectorRow) -> StockPlaybookCandidate:
    if row.earnings_day or row.event_day:
        return StockPlaybookCandidate(
            symbol=row.symbol,
            broker_symbol=row.broker_symbol,
            selector_score=row.score,
            playbook="event",
            playbook_score=row.score + 0.5,
            reasons=row.reasons + ("playbook=event",),
            allowed_agent_prefixes=(
                "stock_news_momentum",
                "stock_event_open_drive",
                "stock_post_earnings_drift",
                f"{row.symbol.lower()}_stock_news_momentum",
                f"{row.symbol.lower()}_stock_event_open_drive",
                f"{row.symbol.lower()}_stock_post_earnings_drift",
                "momentum",
            ),
        )
    if abs(row.opening_gap_pct) >= 0.01 or row.relative_volume >= 1.1:
        return StockPlaybookCandidate(
            symbol=row.symbol,
            broker_symbol=row.broker_symbol,
            selector_score=row.score,
            playbook="gap",
            playbook_score=row.score,
            reasons=row.reasons + ("playbook=gap",),
            allowed_agent_prefixes=(
                "stock_gap_and_go",
                "stock_gap_open_reclaim",
                "stock_gap_fade",
                "stock_premarket_sweep_reversal",
                "stock_trend_breakout",
                f"{row.symbol.lower()}_stock_gap_and_go",
                f"{row.symbol.lower()}_stock_gap_open_reclaim",
                f"{row.symbol.lower()}_stock_gap_fade",
                f"{row.symbol.lower()}_stock_premarket_sweep_reversal",
                "momentum",
            ),
        )
    return StockPlaybookCandidate(
        symbol=row.symbol,
        broker_symbol=row.broker_symbol,
        selector_score=row.score,
        playbook="power_hour",
        playbook_score=row.score,
        reasons=row.reasons + ("playbook=power_hour",),
        allowed_agent_prefixes=(
            "stock_power_hour",
            "stock_trend_breakout",
            f"{row.symbol.lower()}_stock_power_hour",
            "momentum",
        ),
    )


def allow_candidate_for_playbook(candidate_name: str, playbook_candidate: StockPlaybookCandidate) -> bool:
    return any(candidate_name.startswith(prefix) for prefix in playbook_candidate.allowed_agent_prefixes)
