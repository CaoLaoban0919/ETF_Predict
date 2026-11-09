from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from mvp.core import (
    StrategyConfig,
    build_rotation_strategy,
    compute_factors,
    generate_demo_prices,
    load_price_directory,
    run_backtest,
    save_report,
    MarketSnapshot,
    summarize_market_history,
)
from mvp.core.factors import FactorResult


class CoreBehaviorTests(unittest.TestCase):
    def test_market_snapshot_summary_preserves_raw_payload(self) -> None:
        snapshot = MarketSnapshot(
            symbol="510500",
            source="eastmoney",
            period="daily",
            adjust="qfq",
            count=2,
            request_url="http://example.test/510500",
            fetched_at="2026-08-08T10:00:00Z",
            first_date="2026-08-01",
            last_date="2026-08-08",
            raw_payload={"success": True, "symbol": "510500"},
            raw_rows=[{"日期": "2026-08-08"}],
            rows=[
                {"date": "2026-08-01", "close": 2.0},
                {"date": "2026-08-08", "close": 3.0},
            ],
        )

        summary = summarize_market_history(snapshot)

        self.assertEqual(summary["symbol"], "510500")
        self.assertEqual(summary["latest"]["close"], 3.0)
        self.assertEqual(summary["raw_payload"]["symbol"], "510500")
        self.assertAlmostEqual(summary["stats"]["max_close"], 3.0)

    def test_factor_scores_do_not_use_future_prices(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=90, name="date")
        prices = pd.DataFrame(
            {
                "A": np.linspace(100.0, 145.0, len(dates)),
                "B": np.linspace(120.0, 90.0, len(dates)),
                "C": 100.0 + np.sin(np.arange(len(dates)) / 4.0) * 8.0,
            },
            index=dates,
        )
        config = StrategyConfig(
            momentum_lookback=10,
            trend_lookback=15,
            volatility_lookback=5,
        )
        cutoff = dates[50]

        baseline = compute_factors(prices, config)
        changed = prices.copy()
        changed.loc[dates[51]:, "A"] *= 4.0
        changed.loc[dates[51]:, "B"] *= 0.25
        recalculated = compute_factors(changed, config)

        pd.testing.assert_frame_equal(
            baseline.composite.loc[:cutoff],
            recalculated.composite.loc[:cutoff],
        )

    def test_rebalance_signal_executes_on_next_bar(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=10, name="date")
        prices = pd.DataFrame(
            {"A": np.arange(100.0, 110.0), "B": np.arange(80.0, 90.0)},
            index=dates,
        )
        config = StrategyConfig(
            momentum_lookback=2,
            trend_lookback=2,
            volatility_lookback=2,
            rebalance_frequency=3,
            minimum_momentum=-1.0,
            require_uptrend=False,
        )

        common = pd.DataFrame(1.0, index=dates, columns=prices.columns)
        scores = pd.DataFrame({"A": 1.0, "B": 0.0}, index=dates)
        scores.loc[dates[5]:, "A"] = 0.0
        scores.loc[dates[5]:, "B"] = 1.0
        factors = FactorResult(
            raw={
                "momentum": common,
                "trend": common,
                "low_volatility": common,
            },
            normalized={},
            composite=scores,
        )

        result = build_rotation_strategy(prices, factors, config)

        self.assertAlmostEqual(result.decision_weights.loc[dates[2], "A"], 1.0)
        self.assertAlmostEqual(result.executed_weights.loc[dates[2]].sum(), 0.0)
        self.assertAlmostEqual(result.executed_weights.loc[dates[3], "A"], 1.0)
        self.assertAlmostEqual(result.decision_weights.loc[dates[5], "B"], 1.0)
        self.assertAlmostEqual(result.executed_weights.loc[dates[5], "A"], 1.0)
        self.assertAlmostEqual(result.executed_weights.loc[dates[6], "B"], 1.0)

    def test_backtest_charges_each_trade_side(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=4, name="date")
        prices = pd.DataFrame(
            {"A": [100.0, 110.0, 110.0, 110.0], "B": [100.0] * 4},
            index=dates,
        )
        weights = pd.DataFrame(
            {"A": [0.0, 1.0, 1.0, 0.0], "B": [0.0, 0.0, 0.0, 0.0]},
            index=dates,
        )
        config = StrategyConfig(commission_bps=10.0)

        result = run_backtest(prices, weights, config)

        self.assertAlmostEqual(result.daily.loc[dates[1], "gross_return"], 0.10)
        self.assertAlmostEqual(result.daily.loc[dates[1], "transaction_cost"], 0.001)
        self.assertAlmostEqual(result.daily.loc[dates[1], "net_return"], 0.099)
        self.assertAlmostEqual(result.daily.loc[dates[3], "transaction_cost"], 0.001)
        self.assertAlmostEqual(result.metrics["total_traded_notional"], 2.0)

    def test_multi_asset_weights_drift_until_scheduled_rebalance(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=4, name="date")
        prices = pd.DataFrame(
            {"A": [100.0, 200.0, 200.0, 200.0], "B": [100.0] * 4},
            index=dates,
        )
        targets = pd.DataFrame(
            {
                "A": [0.0, 0.5, 0.5, 0.5],
                "B": [0.0, 0.5, 0.5, 0.5],
            },
            index=dates,
        )
        execution_mask = pd.Series(
            [False, True, False, True],
            index=dates,
            name="rebalance",
        )

        result = run_backtest(
            prices,
            targets,
            StrategyConfig(commission_bps=0.0),
            execution_mask,
        )

        self.assertAlmostEqual(result.executed_weights.loc[dates[1], "A"], 0.5)
        self.assertAlmostEqual(result.executed_weights.loc[dates[2], "A"], 2.0 / 3.0)
        self.assertAlmostEqual(result.executed_weights.loc[dates[3], "A"], 0.5)
        self.assertAlmostEqual(result.daily.loc[dates[3], "traded_notional"], 1.0 / 3.0)

    def test_wide_daily_file_loads_without_backfill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            dates = pd.bdate_range("2024-01-02", periods=40)
            frame = pd.DataFrame(
                {
                    "date": dates,
                    "510300.SH": np.linspace(3.5, 3.9, len(dates)),
                    "518880.SH": np.linspace(4.2, 4.0, len(dates)),
                }
            )
            frame.loc[5, "518880.SH"] = np.nan
            frame.to_csv(directory / "prices.csv", index=False)

            loaded = load_price_directory(
                directory,
                max_stale_days=2,
                min_observations=20,
            )

            self.assertEqual(list(loaded.prices.columns), ["510300.SH", "518880.SH"])
            self.assertAlmostEqual(
                loaded.prices.iloc[5]["518880.SH"],
                loaded.prices.iloc[4]["518880.SH"],
            )
            self.assertFalse(loaded.is_demo)

    def test_full_demo_pipeline_writes_auditable_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            price_data = generate_demo_prices(periods=260, seed=11)
            config = StrategyConfig(
                momentum_lookback=10,
                trend_lookback=20,
                volatility_lookback=5,
                rebalance_frequency=10,
                top_k=2,
                commission_bps=8.0,
            )

            factors = compute_factors(price_data.prices, config)
            strategy = build_rotation_strategy(price_data.prices, factors, config)
            backtest = run_backtest(
                price_data.prices,
                strategy.executed_weights,
                config,
                strategy.execution_mask,
            )
            paths = save_report(directory, price_data, strategy, backtest, config)

            self.assertTrue(all(path.exists() for path in paths.__dict__.values()))
            self.assertFalse(strategy.ranking.empty)
            self.assertTrue(strategy.executed_weights.sum(axis=1).le(1.0).all())
            payload = json.loads(paths.metrics.read_text(encoding="utf-8"))
            self.assertTrue(payload["is_demo"])
            self.assertEqual(payload["observations"], 260)
            self.assertTrue(np.isfinite(payload["total_return"]))

            dashboard = json.loads(paths.dashboard_data.read_text(encoding="utf-8"))
            self.assertEqual(len(dashboard["series"]), 260)
            self.assertEqual(dashboard["meta"]["symbols"], list(price_data.prices.columns))
            self.assertTrue(dashboard["recent_rebalances"])
            self.assertAlmostEqual(
                sum(item["weight"] for item in dashboard["current_allocation"]),
                1.0,
            )


if __name__ == "__main__":
    unittest.main()
