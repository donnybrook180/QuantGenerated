from __future__ import annotations

from quant_system.models import FeatureVector
from quant_system.symbols import (
    is_crypto_symbol as symbol_is_crypto,
    is_stock_symbol as symbol_is_stock,
)


def split_features(features: list[FeatureVector], symbol: str) -> tuple[list[FeatureVector], list[FeatureVector], list[FeatureVector]]:
    total = len(features)
    if total < 30:
        return features, [], []
    if symbol_is_crypto(symbol):
        train_ratio = 0.5
        validation_ratio = 0.25
    elif symbol_is_stock(symbol):
        train_ratio = 0.5
        validation_ratio = 0.25
    else:
        train_ratio = 0.6
        validation_ratio = 0.2
    train_end = max(int(total * train_ratio), 1)
    validation_end = max(int(total * (train_ratio + validation_ratio)), train_end + 1)
    train = features[:train_end]
    validation = features[train_end:validation_end]
    test = features[validation_end:]
    return train, validation, test


def walk_forward_slices(
    features: list[FeatureVector],
    symbol: str,
) -> list[tuple[list[FeatureVector], list[FeatureVector], list[FeatureVector]]]:
    total = len(features)
    if total < 90:
        train, validation, test = split_features(features, symbol)
        return [(train, validation, test)] if validation and test else []

    upper = symbol.upper()
    if symbol_is_crypto(symbol):
        train_size = max(int(total * 0.45), 30)
        validation_size = max(int(total * 0.25), 10)
        test_size = max(int(total * 0.2), 10)
        step_size = max(int(total * 0.08), 10)
    elif symbol_is_stock(symbol):
        train_size = max(int(total * 0.42), 30)
        validation_size = max(int(total * 0.22), 12)
        test_size = max(int(total * 0.22), 12)
        step_size = max(int(total * 0.06), 10)
    elif upper == "US500":
        train_size = max(int(total * 0.45), 30)
        validation_size = max(int(total * 0.15), 10)
        test_size = max(int(total * 0.15), 10)
        step_size = max(int(total * 0.07), 10)
    else:
        train_size = max(int(total * 0.5), 30)
        validation_size = max(int(total * 0.2), 10)
        test_size = max(int(total * 0.2), 10)
        step_size = max(int(total * 0.1), 10)
    windows: list[tuple[list[FeatureVector], list[FeatureVector], list[FeatureVector]]] = []
    start = 0
    while True:
        train_end = start + train_size
        validation_end = train_end + validation_size
        test_end = validation_end + test_size
        if test_end > total:
            break
        windows.append(
            (
                features[start:train_end],
                features[train_end:validation_end],
                features[validation_end:test_end],
            )
        )
        start += step_size
    if not windows:
        train, validation, test = split_features(features, symbol)
        if validation and test:
            windows.append((train, validation, test))
    return windows
