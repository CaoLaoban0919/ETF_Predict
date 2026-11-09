from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import StrategyConfig


@dataclass(frozen=True)
class BacktestResult:
    daily: pd.DataFrame
    executed_weights: pd.DataFrame
    metrics: dict[str, float | int | str]


def run_backtest(
    prices: pd.DataFrame,
    executed_weights: pd.DataFrame,
    config: StrategyConfig,
    execution_mask: pd.Series | None = None,
) -> BacktestResult:
    """Apply close-to-close returns and per-side transaction costs."""
    targets = executed_weights.reindex(index=prices.index, columns=prices.columns)
    _validate_weights(targets)
    rebalance = _prepare_execution_mask(execution_mask, targets)

    raw_asset_returns = prices.pct_change(fill_method=None)
    asset_returns = raw_asset_returns.fillna(0.0)
    actual_weights, gross_return, traded_notional = _simulate_holdings(
        targets,
        asset_returns,
        rebalance,
    )
    transaction_cost = traded_notional.mul(config.commission_bps / 10_000.0)
    net_return = gross_return.sub(transaction_cost)
    if net_return.le(-1.0).any():
        raise ValueError("net return reached -100%; check prices and transaction costs")

    equity_curve = net_return.add(1.0).cumprod()
    drawdown = equity_curve.div(equity_curve.cummax()).sub(1.0)
    benchmark_return = raw_asset_returns.mean(axis=1, skipna=True).fillna(0.0)
    benchmark_equity = benchmark_return.add(1.0).cumprod()
    exposure = actual_weights.sum(axis=1)

    daily = pd.DataFrame(
        {
            "gross_return": gross_return,
            "transaction_cost": transaction_cost,
            "net_return": net_return,
            "equity_curve": equity_curve,
            "drawdown": drawdown,
            "benchmark_return": benchmark_return,
            "benchmark_equity": benchmark_equity,
            "traded_notional": traded_notional,
            "exposure": exposure,
            "rebalance": rebalance,
            "holdings": actual_weights.apply(_format_holdings, axis=1),
        },
        index=prices.index,
    )
    daily.index.name = prices.index.name
    metrics = calculate_metrics(daily, config)
    return BacktestResult(
        daily=daily,
        executed_weights=actual_weights,
        metrics=metrics,
    )


def calculate_metrics(
    daily: pd.DataFrame,
    config: StrategyConfig,
) -> dict[str, float | int | str]:
    net_return = daily["net_return"]
    equity_curve = daily["equity_curve"]
    elapsed_days = max((daily.index[-1] - daily.index[0]).days, 1)
    elapsed_years = elapsed_days / 365.25

    total_return = float(equity_curve.iloc[-1] - 1.0)
    cagr = float(equity_curve.iloc[-1] ** (1.0 / elapsed_years) - 1.0)
    annualized_volatility = float(net_return.std(ddof=0) * np.sqrt(config.annualization))
    annualized_return = float(net_return.mean() * config.annualization)
    sharpe = (
        (annualized_return - config.risk_free_rate) / annualized_volatility
        if annualized_volatility > 0
        else 0.0
    )
    active_returns = net_return[daily["exposure"].gt(0.0)]
    active_win_rate = float(active_returns.gt(0.0).mean()) if len(active_returns) else 0.0

    return {
        "start_date": daily.index[0].date().isoformat(),
        "end_date": daily.index[-1].date().isoformat(),
        "observations": int(len(daily)),
        "total_return": total_return,
        "cagr": cagr,
        "annualized_volatility": annualized_volatility,
        "sharpe": float(sharpe),
        "max_drawdown": float(daily["drawdown"].min()),
        "active_win_rate": active_win_rate,
        "benchmark_total_return": float(daily["benchmark_equity"].iloc[-1] - 1.0),
        "total_traded_notional": float(daily["traded_notional"].sum()),
        "total_transaction_cost": float(daily["transaction_cost"].sum()),
        "invested_days_ratio": float(daily["exposure"].gt(0.0).mean()),
        "rebalance_count": int(daily["rebalance"].sum()),
        "execution_count": int(daily["traded_notional"].gt(0.0).sum()),
    }


def _validate_weights(weights: pd.DataFrame) -> None:
    if weights.isna().any().any():
        raise ValueError("executed weights cannot contain missing values")
    if weights.lt(-1e-12).any().any():
        raise ValueError("long-only strategy cannot have negative weights")
    if weights.sum(axis=1).gt(1.0 + 1e-9).any():
        raise ValueError("executed weights cannot exceed 100% exposure")


def _prepare_execution_mask(
    execution_mask: pd.Series | None,
    targets: pd.DataFrame,
) -> pd.Series:
    if execution_mask is None:
        previous = targets.shift(1).fillna(0.0)
        mask = targets.ne(previous).any(axis=1)
    else:
        mask = execution_mask.reindex(targets.index)
        if mask.isna().any():
            raise ValueError("execution mask must cover every price date")
        mask = mask.astype(bool)
    mask.name = "rebalance"
    return mask


def _simulate_holdings(
    targets: pd.DataFrame,
    asset_returns: pd.DataFrame,
    rebalance: pd.Series,
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    target_values = targets.to_numpy(dtype=float)
    return_values = asset_returns.to_numpy(dtype=float)
    actual_values = np.zeros_like(target_values)
    gross_values = np.zeros(len(targets), dtype=float)
    turnover_values = np.zeros(len(targets), dtype=float)
    current = np.zeros(targets.shape[1], dtype=float)

    for row in range(len(targets)):
        if rebalance.iloc[row]:
            turnover_values[row] = np.abs(target_values[row] - current).sum()
            current = target_values[row].copy()

        actual_values[row] = current
        gross_values[row] = float(np.dot(current, return_values[row]))
        portfolio_growth = 1.0 + gross_values[row]
        if portfolio_growth <= 0:
            raise ValueError("portfolio value reached zero during holdings simulation")
        current = current * (1.0 + return_values[row]) / portfolio_growth

    actual_weights = pd.DataFrame(
        actual_values,
        index=targets.index,
        columns=targets.columns,
    )
    gross_return = pd.Series(gross_values, index=targets.index, name="gross_return")
    traded_notional = pd.Series(
        turnover_values,
        index=targets.index,
        name="traded_notional",
    )
    return actual_weights, gross_return, traded_notional


def _format_holdings(row: pd.Series) -> str:
    active = row[row.gt(0.0)]
    return "|".join(f"{symbol}:{weight:.4f}" for symbol, weight in active.items())
