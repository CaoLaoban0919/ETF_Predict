from __future__ import annotations

import json
from pathlib import Path
from typing import Any

class DashboardDataError(RuntimeError):
    pass


class DashboardRepository:
    """Expose a narrow, read-only view over the deterministic backtest output."""

    def __init__(self, data_path: str | Path, market_history_path: str | Path | None = None) -> None:
        self.data_path = Path(data_path)
        self.market_history_path = (
            Path(market_history_path)
            if market_history_path is not None
            else self.data_path.with_name("market_history.json")
        )

    def is_available(self) -> bool:
        return self.data_path.is_file()

    def load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.data_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise DashboardDataError("Backtest dashboard data is not available") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise DashboardDataError("Backtest dashboard data cannot be read") from exc

        required = {
            "meta",
            "config",
            "metrics",
            "series",
            "current_allocation",
            "recent_rebalances",
        }
        if not isinstance(payload, dict) or not required.issubset(payload):
            raise DashboardDataError("Backtest dashboard data has an invalid schema")
        return payload

    def load_market_history(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.market_history_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise DashboardDataError("Market history data is not available") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise DashboardDataError("Market history data cannot be read") from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
            raise DashboardDataError("Market history data has an invalid schema")
        return payload

    def as_of(self) -> str:
        payload = self.load()
        return str(payload["meta"].get("generated_at", ""))

    def get_strategy_snapshot(self) -> dict[str, Any]:
        """Return strategy configuration, metrics, symbols and current allocation."""
        payload = self.load()
        is_demo = bool(payload["meta"].get("is_demo"))
        return {
            "as_of": payload["meta"].get("generated_at"),
            "data_source": "deterministic demo data" if is_demo else "external ETF daily bars",
            "is_demo": is_demo,
            "symbols": payload["meta"].get("symbols", []),
            "config": payload["config"],
            "metrics": payload["metrics"],
            "current_allocation": payload["current_allocation"],
        }

    def get_recent_rebalances(self, limit: int = 5) -> list[dict[str, Any]]:
        """Return up to ten most recent rebalance decisions and factor rankings."""
        payload = self.load()
        bounded_limit = max(1, min(int(limit), 10))
        events = []
        for event in payload["recent_rebalances"][:bounded_limit]:
            events.append(
                {
                    "date": event.get("date"),
                    "selected_symbols": event.get("selected_symbols", []),
                    "ranking": list(event.get("ranking", []))[:20],
                }
            )
        return events

    def get_risk_summary(self) -> dict[str, Any]:
        """Return already-computed risk and implementation metrics."""
        payload = self.load()
        metrics = payload["metrics"]
        keys = (
            "start_date",
            "end_date",
            "annualized_volatility",
            "sharpe",
            "max_drawdown",
            "active_win_rate",
            "invested_days_ratio",
            "total_transaction_cost",
            "total_traded_notional",
            "rebalance_count",
            "execution_count",
        )
        return {
            "as_of": payload["meta"].get("generated_at"),
            "is_demo": bool(payload["meta"].get("is_demo")),
            **{key: metrics.get(key) for key in keys},
        }

    def get_market_history_summary(self) -> dict[str, Any]:
        payload = self.load_market_history()
        records = payload.get("records", [])
        latest = records[-1] if records else None
        return {
            "as_of": payload.get("generated_at"),
            "record_count": len(records),
            "latest_record": latest,
            "records": records[-20:],
        }

    def get_market_history_for_symbol(self, symbol: str) -> dict[str, Any] | None:
        normalized = str(symbol).strip()
        if not normalized:
            return None
        payload = self.load_market_history()
        for record in reversed(payload.get("records", [])):
            if str(record.get("symbol")) == normalized:
                return record
        return None

    def save_market_history_record(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = self._load_market_history_payload()
        records = [item for item in payload.get("records", []) if isinstance(item, dict)]
        records.append(record)
        payload = {
            "generated_at": record.get("fetched_at"),
            "records": sorted(
                records,
                key=lambda item: (
                    str(item.get("symbol", "")),
                    str(item.get("fetched_at", "")),
                ),
            ),
        }
        self.market_history_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        return payload

    def load_market_history_record(self, symbol: str) -> dict[str, Any] | None:
        normalized = str(symbol).strip()
        if not normalized:
            return None
        payload = self._load_market_history_payload()
        for record in reversed(payload.get("records", [])):
            if str(record.get("symbol")) == normalized:
                return record

    def compare_market_records(self, symbol_a: str, symbol_b: str) -> dict[str, Any]:
        record_a = self.load_market_history_record(symbol_a)
        record_b = self.load_market_history_record(symbol_b)
        if record_a is None or record_b is None:
            raise DashboardDataError("Market comparison data is not available")

        return {
            "symbol_a": self._build_market_summary(record_a),
            "symbol_b": self._build_market_summary(record_b),
            "comparison": self._build_comparison(record_a, record_b),
        }

    def _load_market_history_payload(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.market_history_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"generated_at": None, "records": []}
        except (OSError, json.JSONDecodeError):
            return {"generated_at": None, "records": []}
        if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
            return {"generated_at": None, "records": []}
        return payload

    def _build_market_summary(self, record: dict[str, Any]) -> dict[str, Any]:
        rows = list(record.get("rows", []))
        latest = record.get("latest_row") or (rows[-1] if rows else {})
        first = rows[0] if rows else {}
        close_values = [float(row.get("close", 0.0)) for row in rows if row.get("close") is not None]
        return {
            "symbol": record.get("symbol"),
            "source": record.get("source"),
            "period": record.get("period"),
            "adjust": record.get("adjust"),
            "count": record.get("count"),
            "fetched_at": record.get("fetched_at"),
            "first_date": record.get("first_date"),
            "last_date": record.get("last_date"),
            "latest": latest,
            "first": first,
            "stats": {
                "latest_close": latest.get("close"),
                "latest_change_pct": latest.get("change_pct"),
                "latest_turnover_rate": latest.get("turnover_rate"),
                "latest_amount": latest.get("amount"),
                "max_close": max(close_values) if close_values else None,
                "min_close": min(close_values) if close_values else None,
            },
        }

    def _build_comparison(self, record_a: dict[str, Any], record_b: dict[str, Any]) -> dict[str, Any]:
        a = self._build_market_summary(record_a)
        b = self._build_market_summary(record_b)
        latest_a = a["stats"]
        latest_b = b["stats"]
        return {
            "latest_close_diff": self._safe_diff(latest_a.get("latest_close"), latest_b.get("latest_close")),
            "latest_change_pct_diff": self._safe_diff(latest_a.get("latest_change_pct"), latest_b.get("latest_change_pct")),
            "latest_turnover_rate_diff": self._safe_diff(latest_a.get("latest_turnover_rate"), latest_b.get("latest_turnover_rate")),
            "latest_amount_diff": self._safe_diff(latest_a.get("latest_amount"), latest_b.get("latest_amount")),
            "close_range_diff": self._safe_diff(latest_a.get("max_close"), latest_b.get("max_close")),
        }

    def _safe_diff(self, left: Any, right: Any) -> float | None:
        if left is None or right is None:
            return None
        try:
            return float(left) - float(right)
        except (TypeError, ValueError):
            return None
