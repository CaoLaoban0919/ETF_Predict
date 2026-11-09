from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from mvp.agent.config import AgentSettings
from mvp.agent.repository import DashboardDataError, DashboardRepository
from mvp.agent.refresh import DashboardRefreshService
from mvp.agent.runtime import AgentNotConfiguredError, AgentRuntime


def _dashboard_payload() -> dict[str, object]:
    return {
        "meta": {
            "generated_at": "2026-08-07T10:00:00Z",
            "data_source": "test.csv",
            "is_demo": False,
            "symbols": ["510300.SH", "518880.SH"],
        },
        "config": {"top_k": 1},
        "metrics": {
            "start_date": "2024-01-02",
            "end_date": "2026-08-07",
            "annualized_volatility": 0.12,
            "sharpe": 1.1,
            "max_drawdown": -0.08,
            "active_win_rate": 0.53,
            "invested_days_ratio": 0.75,
            "total_transaction_cost": 0.01,
            "total_traded_notional": 8.0,
            "rebalance_count": 10,
            "execution_count": 8,
        },
        "series": [{"date": "2026-08-07", "equity": 1.2}],
        "current_allocation": [{"symbol": "510300.SH", "weight": 1.0}],
        "recent_rebalances": [
            {
                "date": "2026-08-06",
                "selected_symbols": ["510300.SH"],
                "ranking": [{"rank": rank, "symbol": f"ETF-{rank}"} for rank in range(25)],
            }
        ],
    }


class AgentIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_path = Path(self.temp_dir.name) / "dashboard_data.json"
        self.data_path.write_text(json.dumps(_dashboard_payload()), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_repository_exposes_only_bounded_views(self) -> None:
        repository = DashboardRepository(self.data_path)

        snapshot = repository.get_strategy_snapshot()
        risk = repository.get_risk_summary()

        self.assertNotIn("series", snapshot)
        self.assertEqual(snapshot["data_source"], "external ETF daily bars")
        self.assertEqual(snapshot["current_allocation"][0]["symbol"], "510300.SH")
        self.assertEqual(risk["max_drawdown"], -0.08)
        self.assertEqual(len(repository.get_recent_rebalances()[0]["ranking"]), 20)

    def test_repository_rejects_invalid_payload(self) -> None:
        self.data_path.write_text("{}", encoding="utf-8")

        with self.assertRaises(DashboardDataError):
            DashboardRepository(self.data_path).load()

    def test_repository_stores_and_compares_market_records(self) -> None:
        repository = DashboardRepository(self.data_path, Path(self.temp_dir.name) / "market_history.json")
        record_a = {
            "symbol": "510500",
            "source": "eastmoney",
            "period": "daily",
            "adjust": "qfq",
            "count": 2,
            "request_url": "http://example.test/a",
            "fetched_at": "2026-08-08T10:00:00Z",
            "first_date": "2026-08-01",
            "last_date": "2026-08-08",
            "latest_row": {
                "date": "2026-08-08",
                "close": 3.0,
                "change_pct": 1.0,
                "turnover_rate": 2.0,
                "amount": 100.0,
            },
            "rows": [
                {"date": "2026-08-01", "close": 2.0, "change_pct": 0.0, "turnover_rate": 1.0, "amount": 80.0},
                {"date": "2026-08-08", "close": 3.0, "change_pct": 1.0, "turnover_rate": 2.0, "amount": 100.0},
            ],
            "raw_rows": [],
            "raw_payload": {},
        }
        record_b = {
            "symbol": "510300",
            "source": "eastmoney",
            "period": "daily",
            "adjust": "qfq",
            "count": 2,
            "request_url": "http://example.test/b",
            "fetched_at": "2026-08-08T11:00:00Z",
            "first_date": "2026-08-01",
            "last_date": "2026-08-08",
            "latest_row": {
                "date": "2026-08-08",
                "close": 2.0,
                "change_pct": -1.0,
                "turnover_rate": 1.5,
                "amount": 50.0,
            },
            "rows": [
                {"date": "2026-08-01", "close": 1.5, "change_pct": 0.0, "turnover_rate": 1.2, "amount": 40.0},
                {"date": "2026-08-08", "close": 2.0, "change_pct": -1.0, "turnover_rate": 1.5, "amount": 50.0},
            ],
            "raw_rows": [],
            "raw_payload": {},
        }

        repository.save_market_history_record(record_a)
        repository.save_market_history_record(record_b)
        comparison = repository.compare_market_records("510500", "510300")

        self.assertEqual(comparison["symbol_a"]["symbol"], "510500")
        self.assertEqual(comparison["symbol_b"]["symbol"], "510300")
        self.assertAlmostEqual(comparison["comparison"]["latest_close_diff"], 1.0)
        self.assertAlmostEqual(comparison["comparison"]["latest_change_pct_diff"], 2.0)

    def test_runtime_uses_injected_agent_without_importing_agno(self) -> None:
        repository = DashboardRepository(self.data_path)
        settings = AgentSettings(
            data_path=self.data_path,
            api_key="test-key",
            base_url="https://example.test/v1",
            model="test-model",
        )
        calls: list[str] = []

        class FakeAgent:
            def run(self, message: str) -> SimpleNamespace:
                calls.append(message)
                return SimpleNamespace(content="结论：保持只读分析。")

        runtime = AgentRuntime(settings, repository, lambda _settings, _repository: FakeAgent())

        self.assertEqual(runtime.analyze("分析当前风险"), "结论：保持只读分析。")
        self.assertEqual(calls, ["分析当前风险"])

    def test_runtime_requires_provider_configuration(self) -> None:
        repository = DashboardRepository(self.data_path)
        settings = AgentSettings(
            data_path=self.data_path,
            api_key="",
            base_url="https://example.test/v1",
            model="test-model",
        )

        with self.assertRaises(AgentNotConfiguredError):
            AgentRuntime(settings, repository).analyze("分析风险")

    def test_dashboard_refresh_rewrites_shared_snapshot(self) -> None:
        repository = DashboardRepository(self.data_path)
        settings = AgentSettings(
            data_path=self.data_path,
            api_key="",
            base_url="https://example.test/v1",
            model="test-model",
        )

        payload = DashboardRefreshService(settings, repository).refresh()

        self.assertEqual(payload["meta"]["generated_at"], repository.as_of())
        self.assertTrue(payload["meta"]["is_demo"])
        self.assertTrue(payload["series"])

    def test_runtime_uses_market_comparison_tool(self) -> None:
        repository = DashboardRepository(self.data_path, Path(self.temp_dir.name) / "market_history.json")
        repository.save_market_history_record(
            {
                "symbol": "510500",
                "source": "eastmoney",
                "period": "daily",
                "adjust": "qfq",
                "count": 1,
                "request_url": "http://example.test/a",
                "fetched_at": "2026-08-08T10:00:00Z",
                "first_date": "2026-08-08",
                "last_date": "2026-08-08",
                "latest_row": {"date": "2026-08-08", "close": 3.0, "change_pct": 1.0, "turnover_rate": 2.0, "amount": 100.0},
                "rows": [{"date": "2026-08-08", "close": 3.0, "change_pct": 1.0, "turnover_rate": 2.0, "amount": 100.0}],
                "raw_rows": [],
                "raw_payload": {},
            }
        )
        repository.save_market_history_record(
            {
                "symbol": "510300",
                "source": "eastmoney",
                "period": "daily",
                "adjust": "qfq",
                "count": 1,
                "request_url": "http://example.test/b",
                "fetched_at": "2026-08-08T11:00:00Z",
                "first_date": "2026-08-08",
                "last_date": "2026-08-08",
                "latest_row": {"date": "2026-08-08", "close": 2.0, "change_pct": -1.0, "turnover_rate": 1.5, "amount": 50.0},
                "rows": [{"date": "2026-08-08", "close": 2.0, "change_pct": -1.0, "turnover_rate": 1.5, "amount": 50.0}],
                "raw_rows": [],
                "raw_payload": {},
            }
        )

        settings = AgentSettings(
            data_path=self.data_path,
            api_key="test-key",
            base_url="https://example.test/v1",
            model="test-model",
        )

        class FakeAgent:
            def run(self, message: str) -> SimpleNamespace:
                return SimpleNamespace(content=message)

        runtime = AgentRuntime(settings, repository, lambda _settings, _repository: FakeAgent())
        answer = runtime.analyze("请比较 510500 和 510300 的表现")
        self.assertIn("510500", answer)
        self.assertIn("510300", answer)


if __name__ == "__main__":
    unittest.main()
