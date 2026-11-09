from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

if __package__:
    from .core import (
        StrategyConfig,
        build_rotation_strategy,
        compute_factors,
        format_summary,
        generate_demo_prices,
        load_price_directory,
        run_backtest,
        save_report,
    )
else:
    from core import (
        StrategyConfig,
        build_rotation_strategy,
        compute_factors,
        format_summary,
        generate_demo_prices,
        load_price_directory,
        run_backtest,
        save_report,
    )


MVP_DIR = Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the ETF multi-factor rotation MVP")
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Directory containing daily per-symbol or wide CSV/Parquet files",
    )
    parser.add_argument("--symbols", nargs="+", help="Optional symbols to load")
    parser.add_argument("--output-dir", type=Path, default=MVP_DIR / "output")
    parser.add_argument("--top-k", type=int, default=1)
    parser.add_argument("--rebalance-frequency", type=int, default=20)
    parser.add_argument("--momentum-lookback", type=int, default=60)
    parser.add_argument("--trend-lookback", type=int, default=120)
    parser.add_argument("--volatility-lookback", type=int, default=20)
    parser.add_argument("--commission-bps", type=float, default=10.0)
    parser.add_argument("--minimum-momentum", type=float, default=0.0)
    parser.add_argument("--allow-downtrend", action="store_true")
    parser.add_argument("--demo-periods", type=int, default=1_250)
    parser.add_argument("--demo-seed", type=int, default=7)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = StrategyConfig(
        momentum_lookback=args.momentum_lookback,
        trend_lookback=args.trend_lookback,
        volatility_lookback=args.volatility_lookback,
        rebalance_frequency=args.rebalance_frequency,
        top_k=args.top_k,
        commission_bps=args.commission_bps,
        minimum_momentum=args.minimum_momentum,
        require_uptrend=not args.allow_downtrend,
    )

    if args.data_dir:
        price_data = load_price_directory(
            args.data_dir,
            args.symbols,
            max_stale_days=config.max_stale_days,
            min_overlap_ratio=config.min_overlap_ratio,
            min_observations=config.warmup_bars + 2,
        )
    else:
        price_data = generate_demo_prices(args.demo_periods, args.demo_seed)

    if config.top_k > price_data.prices.shape[1]:
        raise ValueError(
            f"top_k={config.top_k} exceeds {price_data.prices.shape[1]} loaded symbols"
        )

    factors = compute_factors(price_data.prices, config)
    strategy = build_rotation_strategy(price_data.prices, factors, config)
    backtest = run_backtest(
        price_data.prices,
        strategy.executed_weights,
        config,
        strategy.execution_mask,
    )
    paths = save_report(args.output_dir, price_data, strategy, backtest, config)
    print(format_summary(price_data, backtest, paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
