from __future__ import annotations

import json
from datetime import datetime, timezone
from dataclasses import fields
from threading import Lock
from typing import Any

try:
    from ..core import (
        StrategyConfig,
        build_rotation_strategy,
        compute_factors,
        fetch_etf_history,
        generate_demo_prices,
        load_price_directory,
        run_backtest,
        save_report,
    )
except ImportError:
    from core import (
        StrategyConfig,
        build_rotation_strategy,
        compute_factors,
        fetch_etf_history,
        generate_demo_prices,
        load_price_directory,
        run_backtest,
        save_report,
    )

from .config import AgentSettings
from .repository import DashboardRepository


class DashboardRefreshError(RuntimeError):
    pass


class DashboardRefreshService:
    def __init__(self, settings: AgentSettings, repository: DashboardRepository) -> None:
        self.settings = settings
        self.repository = repository
        self._lock = Lock()

    def refresh(self) -> dict[str, Any]:
        acquired = self._lock.acquire(blocking=False)
        if not acquired:
            raise DashboardRefreshError("Dashboard refresh is already running")
        try:
            previous = self.repository.load()
            config = _strategy_config(previous.get("config", {}))
            observations = max(int(previous.get("metrics", {}).get("observations", 1_250)), 130)

            if self.settings.market_data_path is not None:
                price_data = load_price_directory(
                    self.settings.market_data_path,
                    self.settings.symbols or None,
                    max_stale_days=config.max_stale_days,
                    min_overlap_ratio=config.min_overlap_ratio,
                    min_observations=config.warmup_bars + 2,
                )
            else:
                price_data = generate_demo_prices(observations, seed=7)

            symbols = self.settings.symbols or (price_data.prices.columns.tolist()[:1] if not price_data.is_demo else [])
            if symbols:
                latest_records = []
                for symbol in symbols:
                    snapshot = fetch_etf_history(symbol, base_url=self.settings.market_api_base)
                    latest_records.append(snapshot.to_record())
                _save_market_history(self.settings.market_history_path, latest_records)

            factors = compute_factors(price_data.prices, config)
            strategy = build_rotation_strategy(price_data.prices, factors, config)
            backtest = run_backtest(
                price_data.prices,
                strategy.executed_weights,
                config,
                strategy.execution_mask,
            )
            paths = save_report(
                self.settings.data_path.parent,
                price_data,
                strategy,
                backtest,
                config,
            )
            return json.loads(paths.dashboard_data.read_text(encoding="utf-8"))
        except DashboardRefreshError:
            raise
        except Exception as exc:
            raise DashboardRefreshError("Dashboard data refresh failed") from exc
        finally:
            if acquired:
                self._lock.release()


def _strategy_config(raw: object) -> StrategyConfig:
    if not isinstance(raw, dict):
        return StrategyConfig()
    allowed = {field.name for field in fields(StrategyConfig)}
    values = {key: value for key, value in raw.items() if key in allowed}
    return StrategyConfig(**values)


def _load_market_history(path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"generated_at": None, "records": []}
    except (OSError, json.JSONDecodeError):
        return {"generated_at": None, "records": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        return {"generated_at": None, "records": []}
    return payload


def _save_market_history(path, records: list[dict[str, Any]]) -> None:
    existing = _load_market_history(path)
    merged: list[dict[str, Any]] = [
        item for item in existing.get("records", []) if isinstance(item, dict)
    ]
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for record in records:
        if isinstance(record, dict) and record.get("symbol"):
            merged.append(record)
    payload = {
        "generated_at": now,
        "records": sorted(
            merged,
            key=lambda item: (
                str(item.get("symbol", "")),
                str(item.get("fetched_at", "")),
            ),
        ),
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, allow_nan=False), encoding="utf-8")
