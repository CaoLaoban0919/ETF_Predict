from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import StrategyConfig
from .factors import FactorResult


RANKING_COLUMNS = (
    "date",
    "symbol",
    "rank",
    "score",
    "momentum",
    "trend",
    "low_volatility",
    "eligible",
    "selected",
    "target_weight",
)


@dataclass(frozen=True)
class StrategyResult:
    decision_weights: pd.DataFrame
    executed_weights: pd.DataFrame
    execution_mask: pd.Series
    ranking: pd.DataFrame


def build_rotation_strategy(
    prices: pd.DataFrame,
    factors: FactorResult,
    config: StrategyConfig,
) -> StrategyResult:
    """Rank assets on rebalance closes and execute the target one bar later."""
    if not prices.index.equals(factors.composite.index):
        raise ValueError("price and factor indexes must match")
    if not prices.columns.equals(factors.composite.columns):
        raise ValueError("price and factor symbols must match")
    if config.top_k > prices.shape[1]:
        raise ValueError("top_k cannot exceed the number of symbols")

    sparse_decisions = pd.DataFrame(
        np.nan,
        index=prices.index,
        columns=prices.columns,
        dtype=float,
    )
    ranking_rows: list[dict[str, object]] = []

    rebalance_positions = range(
        config.warmup_bars,
        len(prices.index),
        config.rebalance_frequency,
    )
    for position in rebalance_positions:
        date = prices.index[position]
        scores = factors.composite.loc[date]
        momentum = factors.raw["momentum"].loc[date]
        trend = factors.raw["trend"].loc[date]
        low_volatility = factors.raw["low_volatility"].loc[date]

        valid = scores.notna() & momentum.notna() & trend.notna() & low_volatility.notna()
        eligible = valid & momentum.ge(config.minimum_momentum)
        if config.require_uptrend:
            eligible &= trend.gt(0.0)

        ranked_symbols = scores[valid].sort_values(ascending=False, kind="mergesort")
        selected = list(ranked_symbols[eligible.reindex(ranked_symbols.index)].head(config.top_k).index)

        sparse_decisions.loc[date] = 0.0
        if selected:
            sparse_decisions.loc[date, selected] = 1.0 / len(selected)

        rank_map = {symbol: rank for rank, symbol in enumerate(ranked_symbols.index, start=1)}
        for symbol in prices.columns:
            ranking_rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "rank": rank_map.get(symbol),
                    "score": _optional_float(scores[symbol]),
                    "momentum": _optional_float(momentum[symbol]),
                    "trend": _optional_float(trend[symbol]),
                    "low_volatility": _optional_float(low_volatility[symbol]),
                    "eligible": bool(eligible[symbol]),
                    "selected": symbol in selected,
                    "target_weight": float(sparse_decisions.loc[date, symbol]),
                }
            )

    decision_events = sparse_decisions.notna().all(axis=1)
    decision_weights = sparse_decisions.ffill().fillna(0.0)
    executed_weights = decision_weights.shift(1).fillna(0.0)
    execution_mask = decision_events.shift(1, fill_value=False).astype(bool)
    decision_weights.index.name = prices.index.name
    executed_weights.index.name = prices.index.name
    execution_mask.index.name = prices.index.name
    execution_mask.name = "rebalance"

    ranking = pd.DataFrame(ranking_rows, columns=RANKING_COLUMNS)
    if not ranking.empty:
        ranking["date"] = pd.to_datetime(ranking["date"])
    return StrategyResult(
        decision_weights=decision_weights,
        executed_weights=executed_weights,
        execution_mask=execution_mask,
        ranking=ranking,
    )


def _optional_float(value: object) -> float | None:
    return None if pd.isna(value) else float(value)
