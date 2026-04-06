# MQL5 EAs

This folder contains MetaTrader 5 Expert Advisors intended for the MT5 Strategy Tester.

## GER40 ORB

File:

- `mql5/Experts/GER40_ORB_EA.mq5`

What it does:

- builds the first 30-minute opening range
- only takes long breakouts
- only allows the `14:00`, `14:15`, and `14:40` style entries via inputs
- uses ATR-based stop loss and take profit
- includes FTMO-style daily loss and total drawdown locks

## How to test in MetaTrader

1. Open MetaEditor from your MT5 / FTMO terminal.
2. Copy `GER40_ORB_EA.mq5` into your terminal's `MQL5/Experts` folder.
3. Compile it in MetaEditor.
4. Open Strategy Tester in MT5.
5. Select:
   - Expert Advisor: `GER40_ORB_EA`
   - Symbol: your broker's GER40 symbol
   - Model: real ticks when possible
   - Timeframe: `M5`
6. Adjust the input session times if your broker server time differs from the research assumptions.

## Important

The EA uses broker server time, not UTC. If your MT5 server time is offset, you must change:

- `InpSessionOpenHour`
- `InpSessionOpenMinute`
- `InpEntryHour`

before trusting test results.
