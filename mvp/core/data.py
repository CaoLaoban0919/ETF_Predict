from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


DATE_COLUMNS = ("trade_date", "date", "datetime", "timestamp")
PRICE_COLUMNS = ("adj_close", "close")


@dataclass(frozen=True)
class PriceData:
    prices: pd.DataFrame
    source: str
    is_demo: bool


def generate_demo_prices(periods: int = 1_250, seed: int = 7) -> PriceData:
    """Create deterministic multi-regime data for an install-free smoke run."""
    if periods < 100:
        raise ValueError("demo data requires at least 100 observations")

    symbols = ("EQUITY", "GROWTH", "BOND", "GOLD")
    dates = pd.bdate_range("2020-01-02", periods=periods, name="date")
    rng = np.random.default_rng(seed)

    annual_drifts = np.array(
        [
            [0.16, 0.24, 0.02, 0.04],
            [-0.18, -0.27, 0.09, 0.13],
            [0.05, -0.03, -0.05, 0.21],
            [0.14, 0.20, 0.03, 0.06],
        ]
    )
    annual_volatility = np.array([0.18, 0.25, 0.06, 0.14])
    market_beta = np.array([1.00, 1.25, -0.15, 0.05])

    regime_length = max(80, periods // 6)
    regimes = (np.arange(periods) // regime_length) % len(annual_drifts)
    common_shock = rng.normal(0.0, 0.008, size=periods)
    idiosyncratic = rng.normal(size=(periods, len(symbols)))

    daily_returns = annual_drifts[regimes] / 252.0
    daily_returns += common_shock[:, None] * market_beta[None, :]
    daily_returns += idiosyncratic * annual_volatility[None, :] / np.sqrt(252.0)
    daily_returns = np.clip(daily_returns, -0.25, 0.25)

    prices = 100.0 * np.exp(np.log1p(daily_returns).cumsum(axis=0))
    frame = pd.DataFrame(prices, index=dates, columns=symbols)
    return PriceData(
        prices=frame,
        source=f"deterministic demo data (seed={seed})",
        is_demo=True,
    )


def load_price_directory(
    data_dir: str | Path,
    symbols: Iterable[str] | None = None,
    *,
    max_stale_days: int = 3,
    min_overlap_ratio: float = 0.80,
    min_observations: int = 130,
) -> PriceData:
    """Load daily adjusted-close prices from per-symbol or wide CSV/Parquet files."""
    directory = Path(data_dir).expanduser().resolve()
    if not directory.is_dir():
        raise FileNotFoundError(f"data directory does not exist: {directory}")

    files = sorted(directory.glob("*.csv")) + sorted(directory.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no CSV or Parquet files found in {directory}")

    requested = set(symbols or [])
    parts: dict[str, list[pd.Series]] = defaultdict(list)
    errors: list[str] = []
    for path in files:
        try:
            extracted = _extract_price_series(path)
        except (ValueError, KeyError, ImportError) as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        for symbol, series in extracted.items():
            if not requested or symbol in requested:
                parts[symbol].append(series)

    if requested:
        missing = requested - set(parts)
        if missing:
            details = "; ".join(errors[:5])
            raise ValueError(f"requested symbols not found: {sorted(missing)}. {details}")
    if not parts:
        details = "; ".join(errors[:5])
        raise ValueError(f"no usable daily price series found. {details}")

    merged: dict[str, pd.Series] = {}
    for symbol, series_parts in parts.items():
        series = pd.concat(series_parts).sort_index()
        if series.index.has_duplicates:
            conflicting = series.groupby(level=0).nunique(dropna=True).gt(1).any()
            if conflicting:
                raise ValueError(f"conflicting duplicate prices for {symbol}")
            series = series.groupby(level=0).last()
        series = series.dropna()
        if len(series) < min_observations:
            raise ValueError(
                f"{symbol} has {len(series)} rows; at least {min_observations} are required"
            )
        merged[symbol] = series.rename(symbol)

    _validate_overlap(merged, min_overlap_ratio)
    prices = pd.concat(merged.values(), axis=1, join="outer").sort_index()
    if max_stale_days:
        prices = prices.ffill(limit=max_stale_days)
    prices = prices.dropna(how="all")
    prices.index.name = "date"

    if prices.shape[1] < 2:
        raise ValueError("rotation requires at least two symbols")
    return PriceData(prices=prices, source=str(directory), is_demo=False)


def _extract_price_series(path: Path) -> dict[str, pd.Series]:
    frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
    if frame.empty:
        raise ValueError("file is empty")

    date_column = _find_date_column(frame)
    dates = _parse_dates(frame[date_column], path.name)
    price_column = _find_column(frame, PRICE_COLUMNS)

    if price_column is not None:
        symbol = _find_symbol(frame, path)
        series = _build_series(frame[price_column], dates, symbol, path.name)
        return {symbol: series}

    ignored = {str(date_column).lower(), "ts_code", "symbol", "code"}
    candidates = [column for column in frame.columns if str(column).lower() not in ignored]
    if not candidates:
        raise KeyError("missing adj_close/close or wide price columns")

    result: dict[str, pd.Series] = {}
    for column in candidates:
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.notna().mean() < 0.95:
            continue
        symbol = str(column)
        result[symbol] = _build_series(values, dates, symbol, path.name)
    if not result:
        raise KeyError("no numeric price columns found")
    return result


def _find_date_column(frame: pd.DataFrame) -> str:
    lowered = {str(column).lower(): column for column in frame.columns}
    for candidate in DATE_COLUMNS:
        if candidate in lowered:
            return lowered[candidate]

    first = frame.columns[0]
    first_name = str(first).lower()
    if first_name.startswith("unnamed") or first_name in {"index", ""}:
        return first
    raise KeyError(f"missing date column; expected one of {DATE_COLUMNS}")


def _find_column(frame: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    lowered = {str(column).lower(): column for column in frame.columns}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None


def _find_symbol(frame: pd.DataFrame, path: Path) -> str:
    symbol_column = _find_column(frame, ("ts_code", "symbol", "code"))
    if symbol_column is not None:
        values = frame[symbol_column].dropna().astype(str).unique()
        if len(values) == 1:
            return values[0]
        if len(values) > 1:
            raise ValueError("a per-symbol file contains multiple symbol values")
    return path.stem.split("_daily_")[0]


def _parse_dates(values: pd.Series, filename: str) -> pd.DatetimeIndex:
    raw = values.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    compact = raw.str.fullmatch(r"\d{8}").all()
    dates = pd.to_datetime(raw, format="%Y%m%d" if compact else None, errors="coerce")
    if dates.isna().any():
        raise ValueError(f"unparseable dates in {filename}")

    index = pd.DatetimeIndex(dates)
    if index.tz is not None:
        index = index.tz_convert(None)
    ordered = index.sort_values().unique()
    if len(ordered) > 1:
        deltas = pd.Series(ordered).diff().dropna()
        median_days = float(deltas.median() / pd.Timedelta(days=1))
        if median_days < 0.75 or median_days > 4.0:
            raise ValueError(
                f"expected daily bars, observed median spacing {median_days:.3f} days"
            )
    if index.normalize().duplicated().any():
        raise ValueError("multiple bars per day detected; daily data is required")
    return index.normalize()


def _build_series(
    values: pd.Series,
    dates: pd.DatetimeIndex,
    symbol: str,
    filename: str,
) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    invalid = values.notna() & numeric.isna()
    if invalid.any():
        raise ValueError(f"non-numeric prices in {filename}")
    series = pd.Series(numeric.to_numpy(), index=dates, name=symbol).sort_index().dropna()
    if series.empty:
        raise ValueError(f"no valid prices in {filename}")
    if (series <= 0).any():
        raise ValueError(f"non-positive prices in {filename}")
    if series.index.has_duplicates:
        raise ValueError(f"duplicate dates in {filename}")
    return series


def _validate_overlap(series: dict[str, pd.Series], minimum: float) -> None:
    if len(series) < 2:
        return
    common = set.intersection(*(set(item.index) for item in series.values()))
    shortest = min(len(item) for item in series.values())
    ratio = len(common) / shortest
    if ratio < minimum:
        raise ValueError(
            f"daily series overlap is {ratio:.1%}; at least {minimum:.1%} is required. "
            "Do not mix assets with different periods or bar frequencies."
        )
