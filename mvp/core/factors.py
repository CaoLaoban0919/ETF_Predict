from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import StrategyConfig


@dataclass(frozen=True)
class FactorResult:
    raw: dict[str, pd.DataFrame]
    normalized: dict[str, pd.DataFrame]
    composite: pd.DataFrame


def compute_factors(prices: pd.DataFrame, config: StrategyConfig) -> FactorResult:
    _validate_prices(prices)
    returns = prices.pct_change(fill_method=None)

    raw = {
        "momentum": prices.pct_change(
            periods=config.momentum_lookback,
            fill_method=None,
        ),
        "trend": prices.div(
            prices.rolling(
                config.trend_lookback,
                min_periods=config.trend_lookback,
            ).mean()
        ).sub(1.0),
        "low_volatility": returns.rolling(
            config.volatility_lookback,
            min_periods=config.volatility_lookback,
        ).std(ddof=0).mul(-np.sqrt(config.annualization)),
    }
    normalized = {name: cross_sectional_score(value) for name, value in raw.items()}

    weights = config.normalized_factor_weights
    composite = sum(normalized[name] * weights[name] for name in weights)
    composite.index.name = prices.index.name
    return FactorResult(raw=raw, normalized=normalized, composite=composite)


def cross_sectional_score(values: pd.DataFrame) -> pd.DataFrame:
    """Map each date's valid factor values to [-1, 1] by cross-sectional rank."""
    counts = values.notna().sum(axis=1)
    denominator = counts.sub(1).replace(0, np.nan)
    scores = values.rank(axis=1, method="average").sub(1.0)
    scores = scores.div(denominator, axis=0).mul(2.0).sub(1.0)

    single_rows = counts.eq(1)
    if single_rows.any():
        single_values = values.loc[single_rows]
        scores.loc[single_rows] = single_values.notna().astype(float).replace(0.0, np.nan) * 0.0
    return scores


def _validate_prices(prices: pd.DataFrame) -> None:
    if prices.empty:
        raise ValueError("prices cannot be empty")
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise TypeError("prices must use a DatetimeIndex")
    if not prices.index.is_monotonic_increasing or prices.index.has_duplicates:
        raise ValueError("price index must be sorted and unique")
    if prices.shape[1] < 2:
        raise ValueError("factor scoring requires at least two symbols")
    if (prices <= 0).any().any():
        raise ValueError("prices must be positive")
