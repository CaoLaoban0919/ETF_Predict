from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


FACTOR_NAMES = ("momentum", "trend", "low_volatility")


@dataclass(frozen=True)
class StrategyConfig:
    momentum_lookback: int = 60
    trend_lookback: int = 120
    volatility_lookback: int = 20
    factor_weights: dict[str, float] = field(
        default_factory=lambda: {
            "momentum": 0.50,
            "trend": 0.30,
            "low_volatility": 0.20,
        }
    )
    rebalance_frequency: int = 20
    top_k: int = 1
    commission_bps: float = 10.0
    annualization: int = 252
    risk_free_rate: float = 0.02
    minimum_momentum: float = 0.0
    require_uptrend: bool = True
    max_stale_days: int = 3
    min_overlap_ratio: float = 0.80

    def __post_init__(self) -> None:
        positive_ints = {
            "momentum_lookback": self.momentum_lookback,
            "trend_lookback": self.trend_lookback,
            "volatility_lookback": self.volatility_lookback,
            "rebalance_frequency": self.rebalance_frequency,
            "top_k": self.top_k,
            "annualization": self.annualization,
        }
        for name, value in positive_ints.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")

        if self.commission_bps < 0:
            raise ValueError("commission_bps cannot be negative")
        if self.max_stale_days < 0:
            raise ValueError("max_stale_days cannot be negative")
        if not 0 < self.min_overlap_ratio <= 1:
            raise ValueError("min_overlap_ratio must be in (0, 1]")

        unknown = set(self.factor_weights) - set(FACTOR_NAMES)
        missing = set(FACTOR_NAMES) - set(self.factor_weights)
        if unknown or missing:
            raise ValueError(
                f"factor_weights must contain exactly {FACTOR_NAMES}; "
                f"unknown={sorted(unknown)}, missing={sorted(missing)}"
            )
        if any(weight < 0 for weight in self.factor_weights.values()):
            raise ValueError("factor weights cannot be negative")
        if sum(self.factor_weights.values()) <= 0:
            raise ValueError("at least one factor weight must be positive")

    @property
    def warmup_bars(self) -> int:
        return max(
            self.momentum_lookback,
            self.trend_lookback,
            self.volatility_lookback,
        )

    @property
    def normalized_factor_weights(self) -> dict[str, float]:
        total = sum(self.factor_weights.values())
        return {name: weight / total for name, weight in self.factor_weights.items()}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

