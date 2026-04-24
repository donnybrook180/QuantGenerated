# Prop Firm Non-Gambling Evidence Pack

Date: 2026-04-24

## Purpose

This document is intended to show that the trading activity in this environment is structured, research-driven, and risk-managed rather than gambling-style or "all-or-nothing" behavior.

It is written as a supporting summary for prop-firm compliance review and should be sent together with the referenced reports and deployment artifacts.

## Relevant Blue Guardian Rules

Blue Guardian publicly states that:

- EAs are allowed when they are configured around the trader's own strategy.
- Tick scalping, high-frequency trading, arbitrage bots, latency arbitrage, and similar exploitative behavior are prohibited.
- Gambling-style or "all or nothing" trading behavior is prohibited.
- News trading is restricted on funded accounts around high-impact news and FOMC events.

Official sources:

- Are EAs & Trade Copiers allowed?  
  https://help.blueguardian.com/en/articles/9661396-are-eas-trade-copiers-allowed
- What are Blue Guardian's policies and rules concerning scalping and tick scalping?  
  https://help.blueguardian.com/en/articles/14061126-what-are-blue-guardian-s-policies-and-rules-concerning-scalping-and-tick-scalping
- Is News Trading allowed?  
  https://help.blueguardian.com/en/articles/9661412-is-news-trading-allowed
- Other Rules  
  https://help.blueguardian.com/en/articles/9661512-other-rules

## Core Statement

This trading environment does not operate as gambling. It operates as a systematic strategy stack with:

- pre-deployment research and candidate selection,
- strategy-level acceptance or rejection rules,
- per-symbol risk caps,
- execution monitoring,
- trade-cost analysis,
- live guardrails,
- event-risk blocking,
- reduced-risk or blocked status for weaker strategies,
- and per-prop-firm runtime isolation.

## Evidence of Structured Process

### 1. Research before deployment

Live deployment is not created from discretionary impulse trades. It is based on research artifacts and execution validation.

Supporting files:

- [docs/prop_firm_launch_checklist.md](C:/Users/liset/PycharmProjects/QuantGenerated/docs/prop_firm_launch_checklist.md)
- [docs/live_operations_manual.md](C:/Users/liset/PycharmProjects/QuantGenerated/docs/live_operations_manual.md)
- [artifacts/system/reports/portfolio_allocator_backtest.txt](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/system/reports/portfolio_allocator_backtest.txt)
- [artifacts/system/reports/one_year_expectation.txt](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/system/reports/one_year_expectation.txt)

These documents show that the system uses explicit research, allocator logic, scenario analysis, and operational review rather than random position taking.

### 2. Only validated strategies are promoted to live

The live deployment artifacts show that symbols and strategies are explicitly marked as:

- `live_ready`,
- `reduced_risk_only`,
- or rejected / research-only.

Examples:

- [artifacts/deploy/eurusd/live.json](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/deploy/eurusd/live.json)
- [artifacts/deploy/xauusd/live.json](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/deploy/xauusd/live.json)
- [artifacts/deploy/jp225/live.json](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/deploy/jp225/live.json)
- [artifacts/deploy/us500/live.json](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/deploy/us500/live.json)

This is the opposite of gambling behavior: weaker deployments are reduced or blocked instead of being increased aggressively.

### 3. Live health, execution, and slippage are monitored

The system continuously records live status and execution quality.

Supporting files:

- [artifacts/system/reports/live_health_report.txt](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/system/reports/live_health_report.txt)
- [artifacts/system/reports/trade_cost_analysis.txt](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/system/reports/trade_cost_analysis.txt)
- [artifacts/system/reports/tca_impact_report.txt](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/system/reports/tca_impact_report.txt)
- [artifacts/system/reports/tca_adaptation_impact_report.txt](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/system/reports/tca_adaptation_impact_report.txt)

These reports show:

- fill counts,
- implementation shortfall,
- spread and slippage review,
- edge-retention review,
- and whether strategies should remain unchanged, be de-risked, or be replaced.

### 4. Prop-firm-specific isolation is enforced

The environment is designed so that each prop firm has its own runtime, database, MT5 login, and artifact stream.

Supporting files:

- [docs/live_operations_manual.md](C:/Users/liset/PycharmProjects/QuantGenerated/docs/live_operations_manual.md)
- [docs/prop_firm_launch_checklist.md](C:/Users/liset/PycharmProjects/QuantGenerated/docs/prop_firm_launch_checklist.md)

This shows deliberate controls and auditability, not casual or uncontrolled trading.

## Evidence Against "Gambling-Style" Behavior

### 1. No all-or-nothing framing

The one-year expectation note explicitly states that it is not a promise, not a statistically certain forecast, and that downside remains meaningful.

Supporting file:

- [artifacts/system/reports/one_year_expectation.txt](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/system/reports/one_year_expectation.txt)

This is consistent with risk-managed trading and inconsistent with gambling-style certainty claims.

### 2. Weaker symbols are constrained

The live book already distinguishes between stronger symbols and more cautious or reduced-risk deployments.

Example:

- [artifacts/deploy/us500/live.json](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/deploy/us500/live.json)

This indicates controlled exposure rather than doubling down on weak performance.

### 3. The system is built to block unsafe conditions

The deployment artifacts include event-risk blocking and regime restrictions. The live reports also show strategies being blocked by policy or interpreter logic when conditions are not suitable.

Supporting files:

- [artifacts/deploy/eurusd/live.json](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/deploy/eurusd/live.json)
- [artifacts/deploy/eu50/live.json](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/deploy/eu50/live.json)
- [artifacts/deploy/jp225/live.json](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/deploy/jp225/live.json)
- [artifacts/system/reports/live_health_report.txt](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/system/reports/live_health_report.txt)

### 4. Execution evidence is reviewed instead of ignored

The environment does not assume fills are perfect. It explicitly measures execution drag and slippage impact and uses adaptation logic when evidence is sufficient.

Supporting files:

- [artifacts/system/reports/trade_cost_analysis.txt](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/system/reports/trade_cost_analysis.txt)
- [artifacts/system/reports/tca_impact_report.txt](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/system/reports/tca_impact_report.txt)

Ignoring execution quality is common in gambling-style or reckless systems. This environment does the opposite.

## Practical Trading-Style Evidence

The current live stack is centered on named systematic strategies such as:

- `forex_breakout_momentum__30m_overlap`
- `trend__4h_overlap`
- `volatility_breakout__1h_all`
- `jp225_volatility_short_breakdown_asia_hours__4h_all`
- `volatility_breakout__5m_europe__exit_trend`

These are not described or deployed as random directional bets. They are rule-based strategies with validation summaries and live status controls in the deployment artifacts.

Supporting files:

- [artifacts/deploy/eurusd/live.json](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/deploy/eurusd/live.json)
- [artifacts/deploy/xauusd/live.json](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/deploy/xauusd/live.json)
- [artifacts/deploy/jp225/live.json](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/deploy/jp225/live.json)
- [artifacts/deploy/eu50/live.json](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/deploy/eu50/live.json)

## Suggested Submission Bundle

If a prop firm requests evidence, send this document together with:

1. [artifacts/system/reports/live_health_report.txt](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/system/reports/live_health_report.txt)
2. [artifacts/system/reports/trade_cost_analysis.txt](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/system/reports/trade_cost_analysis.txt)
3. [artifacts/system/reports/tca_impact_report.txt](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/system/reports/tca_impact_report.txt)
4. [artifacts/system/reports/one_year_expectation.txt](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/system/reports/one_year_expectation.txt)
5. [docs/live_operations_manual.md](C:/Users/liset/PycharmProjects/QuantGenerated/docs/live_operations_manual.md)
6. [docs/prop_firm_launch_checklist.md](C:/Users/liset/PycharmProjects/QuantGenerated/docs/prop_firm_launch_checklist.md)
7. The relevant live deployment file for the symbol under review, for example:
   - [artifacts/deploy/eurusd/live.json](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/deploy/eurusd/live.json)
   - [artifacts/deploy/xauusd/live.json](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/deploy/xauusd/live.json)
   - [artifacts/deploy/jp225/live.json](C:/Users/liset/PycharmProjects/QuantGenerated/artifacts/deploy/jp225/live.json)

## Short Cover Note

You can send the following summary with the bundle:

> My trading is systematic and research-based, not gambling-based.  
> I use rule-driven strategies that are validated before live deployment, monitored through trade-cost analysis, and constrained by live risk guardrails.  
> Weaker strategies are reduced or blocked rather than scaled aggressively.  
> I also maintain execution monitoring, event-risk blocking, and prop-firm-specific runtime isolation.  
> The attached reports and deployment artifacts document that process.

## Final Note

This pack is strongest when used as process evidence. It shows:

- the system is planned,
- the strategies are validated,
- the live environment is monitored,
- the risk is constrained,
- and the execution is reviewed.

That is the correct framing for demonstrating non-gambling behavior to a prop-firm compliance team.
