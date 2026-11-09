from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_DATA_PATH = Path(__file__).resolve().parents[1] / "output" / "dashboard_data.json"
DEFAULT_MARKET_HISTORY_PATH = Path(__file__).resolve().parents[1] / "output" / "market_history.json"
DEFAULT_MARKET_API_BASE = "http://182.149.175.233:8000/api/v1/core/fund/etf/hist"


@dataclass(frozen=True)
class AgentSettings:
    data_path: Path
    api_key: str
    base_url: str
    model: str
    market_history_path: Path | None = None
    market_api_base: str = DEFAULT_MARKET_API_BASE
    market_data_path: Path | None = None
    symbols: tuple[str, ...] = ()

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip() and self.base_url.strip() and self.model.strip())

    @classmethod
    def from_env(cls) -> "AgentSettings":
        market_data = os.getenv("ETF_MARKET_DATA", "").strip()
        symbols = tuple(
            symbol.strip()
            for symbol in os.getenv("ETF_SYMBOLS", "").split(",")
            if symbol.strip()
        )
        return cls(
            data_path=Path(os.getenv("ETF_DASHBOARD_DATA", str(DEFAULT_DATA_PATH))),
            market_history_path=Path(
                os.getenv("ETF_MARKET_HISTORY", str(DEFAULT_MARKET_HISTORY_PATH))
            ),
            # 数据刷新：真实行情目录仅从显式环境变量读取，未配置时使用演示数据。
            market_data_path=Path(market_data) if market_data else None,
            symbols=symbols,
            api_key=os.getenv("LLM_API_KEY", ""),
            base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
            model=os.getenv("LLM_MODEL", "deepseek-chat"),
            market_api_base=os.getenv("ETF_MARKET_API_BASE", DEFAULT_MARKET_API_BASE),
        )
