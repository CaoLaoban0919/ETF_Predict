from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from typing import Any


DEFAULT_ETF_HISTORY_URL = "http://182.149.175.233:8000/api/v1/core/fund/etf/hist"

FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("日期", "date"),
    ("开盘", "open"),
    ("收盘", "close"),
    ("最高", "high"),
    ("最低", "low"),
    ("成交量", "volume"),
    ("成交额", "amount"),
    ("振幅", "amplitude"),
    ("涨跌幅", "change_pct"),
    ("涨跌额", "change_amount"),
    ("换手率", "turnover_rate"),
)


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    source: str
    period: str
    adjust: str
    count: int
    request_url: str
    fetched_at: str
    raw_payload: dict[str, Any]
    raw_rows: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    first_date: str | None
    last_date: str | None

    @property
    def latest_row(self) -> dict[str, Any] | None:
        return self.rows[-1] if self.rows else None

    def to_record(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "source": self.source,
            "period": self.period,
            "adjust": self.adjust,
            "count": self.count,
            "request_url": self.request_url,
            "fetched_at": self.fetched_at,
            "first_date": self.first_date,
            "last_date": self.last_date,
            "latest_row": self.latest_row,
            "rows": self.rows,
            "raw_rows": self.raw_rows,
            "raw_payload": self.raw_payload,
        }


def summarize_market_history(snapshot: MarketSnapshot) -> dict[str, Any]:
    rows = snapshot.rows
    latest = snapshot.latest_row or {}
    first = rows[0] if rows else {}
    if rows:
        daily_returns = []
        for previous, current in zip(rows, rows[1:], strict=False):
            prev_close = previous.get("close")
            current_close = current.get("close")
            if prev_close and current_close:
                daily_returns.append((current_close / prev_close) - 1.0)
        average_return = sum(daily_returns) / len(daily_returns) if daily_returns else 0.0
        volatility = (
            (sum((item - average_return) ** 2 for item in daily_returns) / len(daily_returns)) ** 0.5
            if daily_returns
            else 0.0
        )
    else:
        average_return = 0.0
        volatility = 0.0

    return {
        "symbol": snapshot.symbol,
        "source": snapshot.source,
        "period": snapshot.period,
        "adjust": snapshot.adjust,
        "count": snapshot.count,
        "request_url": snapshot.request_url,
        "fetched_at": snapshot.fetched_at,
        "first_date": snapshot.first_date,
        "last_date": snapshot.last_date,
        "latest": latest,
        "first": first,
        "stats": {
            "average_daily_return": average_return,
            "volatility_proxy": volatility,
            "max_close": max((row.get("close", 0.0) for row in rows), default=0.0),
            "min_close": min((row.get("close", 0.0) for row in rows), default=0.0),
        },
        "rows": rows,
        "raw_rows": snapshot.raw_rows,
        "raw_payload": snapshot.raw_payload,
    }


def fetch_etf_history(
    symbol: str,
    *,
    base_url: str = DEFAULT_ETF_HISTORY_URL,
    timeout: float = 15.0,
) -> MarketSnapshot:
    requested_symbol = str(symbol).strip()
    if not requested_symbol:
        raise ValueError("symbol cannot be empty")

    request_url = f"{base_url.rstrip('/')}/{quote(requested_symbol)}"
    request = Request(request_url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        raise ConnectionError(f"failed to fetch ETF history for {requested_symbol}") from exc

    if not isinstance(payload, dict):
        raise ValueError("ETF history payload must be a JSON object")
    if not payload.get("success"):
        raise ValueError(f"ETF history request for {requested_symbol} was not successful")

    raw_rows = payload.get("data")
    if not isinstance(raw_rows, list):
        raise ValueError("ETF history payload is missing data rows")

    rows = [_normalize_row(row) for row in raw_rows]
    rows.sort(key=lambda item: item["date"])
    first_date = rows[0]["date"] if rows else None
    last_date = rows[-1]["date"] if rows else None

    return MarketSnapshot(
        symbol=str(payload.get("symbol", requested_symbol)),
        source=str(payload.get("source", "")),
        period=str(payload.get("period", "")),
        adjust=str(payload.get("adjust", "")),
        count=int(payload.get("count") or len(rows)),
        request_url=request_url,
        fetched_at=datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        raw_payload=payload,
        raw_rows=[row for row in raw_rows if isinstance(row, dict)],
        rows=rows,
        first_date=first_date,
        last_date=last_date,
    )


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("ETF history row must be a JSON object")

    normalized: dict[str, Any] = {}
    for raw_name, normalized_name in FIELD_MAP:
        if raw_name not in row:
            raise ValueError(f"ETF history row is missing {raw_name}")
        value = row[raw_name]
        if normalized_name == "date":
            normalized[normalized_name] = str(value)
        elif normalized_name in {"volume"}:
            normalized[normalized_name] = int(float(value))
        elif normalized_name in {"amount", "turnover_rate"}:
            normalized[normalized_name] = float(value)
        else:
            normalized[normalized_name] = float(value)
    return normalized
