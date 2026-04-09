from __future__ import annotations

import sys

import _bootstrap  # noqa: F401
import MetaTrader5 as mt5

from quant_system.config import SystemConfig
from quant_system.symbols import resolve_symbol_request


def _fmt_last_error() -> str:
    return str(mt5.last_error())


def main() -> int:
    config = SystemConfig()
    requested = [item.strip() for item in sys.argv[1:] if item.strip()]
    symbols = requested or ["US500", "US100", "EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTC"]

    kwargs: dict[str, object] = {}
    if config.mt5.terminal_path:
        kwargs["path"] = config.mt5.terminal_path
    if config.mt5.login is not None:
        kwargs["login"] = config.mt5.login
    if config.mt5.password:
        kwargs["password"] = config.mt5.password
    if config.mt5.server:
        kwargs["server"] = config.mt5.server

    print(f"terminal_path: {config.mt5.terminal_path}")
    print(f"mt5.symbol: {config.mt5.symbol}")
    print(f"initialize kwargs: {sorted(kwargs.keys())}")

    ok = mt5.initialize(**kwargs)
    print(f"initialize: {ok}")
    print(f"last_error: {_fmt_last_error()}")
    if not ok:
        return 1

    try:
        print(f"version: {mt5.version()}")
        terminal_info = mt5.terminal_info()
        account_info = mt5.account_info()
        print(f"terminal_info: {terminal_info}")
        print(f"account_info: {account_info}")

        all_symbols = mt5.symbols_get()
        print(f"symbols_get count: {len(all_symbols) if all_symbols is not None else 'None'}")
        if all_symbols:
            preview = [symbol.name for symbol in all_symbols[:20]]
            print(f"symbols preview: {preview}")

        for raw in symbols:
            resolved = resolve_symbol_request(raw)
            candidates = [raw, resolved.broker_symbol, resolved.profile_symbol, resolved.data_symbol]
            print("")
            print(f"requested: {raw}")
            print(f"resolved broker: {resolved.broker_symbol}")
            print(f"resolved profile: {resolved.profile_symbol}")
            print(f"resolved data: {resolved.data_symbol}")
            for candidate in dict.fromkeys(candidates):
                if not candidate:
                    continue
                info = mt5.symbol_info(candidate)
                exists = info is not None
                selected = mt5.symbol_select(candidate, True) if exists else False
                print(f"candidate: {candidate} exists={exists} select={selected} last_error={_fmt_last_error()}")
                if not exists:
                    continue
                rates = mt5.copy_rates_from_pos(candidate, mt5.TIMEFRAME_M5, 0, 10)
                print(
                    f"copy_rates_from_pos({candidate}): "
                    f"{'ok rows=' + str(len(rates)) if rates is not None else 'FAILED'} "
                    f"last_error={_fmt_last_error()}"
                )
                break
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
