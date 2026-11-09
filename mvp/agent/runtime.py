from __future__ import annotations

import json
import os
from collections.abc import Callable
from threading import Lock
from typing import Any, Protocol

from .config import AgentSettings
from .repository import DashboardRepository


class AgentNotConfiguredError(RuntimeError):
    pass


class AgentExecutionError(RuntimeError):
    pass


class _Agent(Protocol):
    def run(self, message: str) -> Any: ...


AgentFactory = Callable[[AgentSettings, DashboardRepository], _Agent]


class AgentRuntime:
    def __init__(
        self,
        settings: AgentSettings,
        repository: DashboardRepository,
        agent_factory: AgentFactory | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self._agent_factory = agent_factory or _build_agno_agent
        self._agent: _Agent | None = None
        self._run_lock = Lock()

    def analyze(self, question: str) -> str:
        if not self.settings.configured:
            raise AgentNotConfiguredError("LLM provider is not configured")

        normalized_question = question.strip()
        if not normalized_question:
            raise ValueError("Question cannot be empty")

        with self._run_lock:
            try:
                if self._agent is None:
                    self._agent = self._agent_factory(self.settings, self.repository)
                response = self._agent.run(normalized_question)
            except AgentExecutionError:
                raise
            except Exception as exc:
                raise AgentExecutionError("The Agent provider request failed") from exc

        content = getattr(response, "content", response)
        if isinstance(content, str):
            answer = content.strip()
        else:
            answer = json.dumps(content, ensure_ascii=False, default=str)
        if not answer:
            raise AgentExecutionError("The Agent returned an empty response")
        return answer


def _build_agno_agent(
    settings: AgentSettings,
    repository: DashboardRepository,
) -> _Agent:
    os.environ.setdefault("AGNO_TELEMETRY", "false")

    try:
        from agno.agent import Agent
        from agno.models.openai.like import OpenAILike
    except ImportError as exc:
        raise AgentExecutionError("Agno runtime is not installed") from exc

    def get_strategy_snapshot() -> dict[str, Any]:
        """Get the latest ETF strategy metrics, configuration and allocation."""
        return repository.get_strategy_snapshot()

    def get_recent_rebalances(limit: int = 5) -> list[dict[str, Any]]:
        """Get recent ETF rebalance decisions and their factor rankings."""
        return repository.get_recent_rebalances(limit)

    def get_risk_summary() -> dict[str, Any]:
        """Get deterministic risk, turnover and transaction-cost metrics."""
        return repository.get_risk_summary()

    def get_market_history_summary() -> dict[str, Any]:
        """Get recent fetched ETF history snapshots for comparison."""
        return repository.get_market_history_summary()

    def get_market_history_for_symbol(symbol: str) -> dict[str, Any] | None:
        """Get the latest stored market snapshot for a specific ETF symbol."""
        return repository.get_market_history_for_symbol(symbol)

    def compare_market_records(symbol_a: str, symbol_b: str) -> dict[str, Any]:
        """Compare the latest stored market snapshots for two ETF symbols."""
        return repository.compare_market_records(symbol_a, symbol_b)

    model = OpenAILike(
        id=settings.model,
        api_key=settings.api_key,
        base_url=settings.base_url,
    )
    return Agent(
        name="ETF Strategy Analyst",
        model=model,
        tools=[
            get_strategy_snapshot,
            get_recent_rebalances,
            get_risk_summary,
            get_market_history_summary,
            get_market_history_for_symbol,
            compare_market_records,
        ],
        instructions=[
            "你是 ETF 轮动策略分析员，必须先调用工具读取最新回测数据再回答。",
            "回测引擎输出是唯一事实来源，不要自行编造收益、仓位或风险指标。",
            "当用户要求比较不同股票代码时，优先调用市场历史工具；如果记录不存在，明确说明。",
            "清楚区分演示数据和真实数据，并明确历史回测不代表未来表现。",
            "回答使用中文，先给结论，再列依据和风险；不要提供自动下单指令。",
            # 二次渲染：约束模型输出为前端安全渲染器支持的 Markdown 子集。
            "使用简洁 Markdown 排版：短标题、项目列表和重点加粗；不要输出 HTML 或 Markdown 表格。",
            "只有在解释资产关系、调仓流程或风险传导时才使用 Mermaid 代码块；不要把未经核验的数值硬编码进图表。",
        ],
        markdown=True,
    )
