from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .backtest import BacktestResult
from .config import StrategyConfig
from .data import PriceData
from .strategy import StrategyResult


@dataclass(frozen=True)
class ReportPaths:
    daily_backtest: Path
    executed_weights: Path
    rebalance_ranking: Path
    metrics: Path
    dashboard_data: Path


def save_report(
    output_dir: str | Path,
    price_data: PriceData,
    strategy: StrategyResult,
    backtest: BacktestResult,
    config: StrategyConfig,
) -> ReportPaths:
    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)

    paths = ReportPaths(
        daily_backtest=directory / "daily_backtest.csv",
        executed_weights=directory / "executed_weights.csv",
        rebalance_ranking=directory / "rebalance_ranking.csv",
        metrics=directory / "metrics.json",
        dashboard_data=directory / "dashboard_data.json",
    )
    backtest.daily.to_csv(paths.daily_backtest, encoding="utf-8")
    backtest.executed_weights.to_csv(paths.executed_weights, encoding="utf-8")
    strategy.ranking.to_csv(paths.rebalance_ranking, index=False, encoding="utf-8")

    payload = {
        "data_source": price_data.source,
        "is_demo": price_data.is_demo,
        "symbols": list(price_data.prices.columns),
        "config": config.to_dict(),
        **backtest.metrics,
    }
    paths.metrics.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True, allow_nan=False),
        encoding="utf-8",
    )
    dashboard_payload = _build_dashboard_payload(
        price_data,
        strategy,
        backtest,
        config,
    )
    paths.dashboard_data.write_text(
        json.dumps(dashboard_payload, separators=(",", ":"), ensure_ascii=True, allow_nan=False),
        encoding="utf-8",
    )
    return paths


def format_summary(
    price_data: PriceData,
    backtest: BacktestResult,
    paths: ReportPaths,
) -> str:
    metrics = backtest.metrics
    lines = [
        "ETF rotation MVP completed",
        f"Data source: {price_data.source}",
        f"Period: {metrics['start_date']} -> {metrics['end_date']}",
        f"Symbols: {', '.join(price_data.prices.columns)}",
        f"Total return: {metrics['total_return']:.2%}",
        f"CAGR: {metrics['cagr']:.2%}",
        f"Sharpe: {metrics['sharpe']:.2f}",
        f"Max drawdown: {metrics['max_drawdown']:.2%}",
        f"Output: {paths.metrics.parent}",
    ]
    if price_data.is_demo:
        lines.append("NOTE: results use synthetic demo data and are not investment evidence.")
    return "\n".join(lines)


def _build_dashboard_payload(
    price_data: PriceData,
    strategy: StrategyResult,
    backtest: BacktestResult,
    config: StrategyConfig,
) -> dict[str, object]:
    series = []
    for date, row in backtest.daily.iterrows():
        series.append(
            {
                "date": date.date().isoformat(),
                "equity": float(row["equity_curve"]),
                "benchmark": float(row["benchmark_equity"]),
                "drawdown": float(row["drawdown"]),
                "net_return": float(row["net_return"]),
                "exposure": float(row["exposure"]),
            }
        )

    latest_weights = backtest.executed_weights.iloc[-1]
    allocation = [
        {"symbol": str(symbol), "weight": float(weight)}
        for symbol, weight in latest_weights.sort_values(ascending=False).items()
        if weight > 1e-10
    ]
    cash_weight = max(0.0, 1.0 - float(latest_weights.sum()))
    if cash_weight > 1e-10:
        allocation.append({"symbol": "CASH", "weight": cash_weight})

    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "data_source": price_data.source,
            "is_demo": price_data.is_demo,
            "symbols": list(price_data.prices.columns),
        },
        "config": config.to_dict(),
        "metrics": backtest.metrics,
        "series": series,
        "current_allocation": allocation,
        "recent_rebalances": _recent_rebalances(strategy.ranking),
    }


def _recent_rebalances(ranking: pd.DataFrame, limit: int = 10) -> list[dict[str, object]]:
    if ranking.empty:
        return []

    recent_dates = ranking["date"].drop_duplicates().tail(limit).tolist()
    events: list[dict[str, object]] = []
    for date in reversed(recent_dates):
        rows = ranking.loc[ranking["date"].eq(date)].copy()
        rows = rows.sort_values("rank", na_position="last", kind="mergesort")
        selected_rows = rows.loc[rows["selected"]]
        events.append(
            {
                "date": pd.Timestamp(date).date().isoformat(),
                "selected_symbols": selected_rows["symbol"].astype(str).tolist(),
                "ranking": [
                    {
                        "symbol": str(row["symbol"]),
                        "rank": _optional_int(row["rank"]),
                        "score": _optional_number(row["score"]),
                        "momentum": _optional_number(row["momentum"]),
                        "trend": _optional_number(row["trend"]),
                        "eligible": bool(row["eligible"]),
                        "selected": bool(row["selected"]),
                        "target_weight": float(row["target_weight"]),
                    }
                    for _, row in rows.iterrows()
                ],
            }
        )
    return events


def _optional_number(value: object) -> float | None:
    return None if pd.isna(value) else float(value)


def _optional_int(value: object) -> int | None:
    return None if pd.isna(value) else int(value)
