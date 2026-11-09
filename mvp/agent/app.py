from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool

try:
    from ..core import fetch_etf_history, summarize_market_history
except ImportError:
    from core import fetch_etf_history, summarize_market_history

from .config import AgentSettings
from .repository import DashboardDataError, DashboardRepository
from .refresh import DashboardRefreshError, DashboardRefreshService
from .runtime import AgentExecutionError, AgentNotConfiguredError, AgentRuntime
from .schemas import AnalyzeRequest, AnalyzeResponse, HealthResponse, RefreshResponse


settings = AgentSettings.from_env()
repository = DashboardRepository(settings.data_path, settings.market_history_path)
runtime = AgentRuntime(settings, repository)
refresh_service = DashboardRefreshService(settings, repository)

app = FastAPI(title="ETF Rotation Agent API", version="1.0.0", docs_url=None, redoc_url=None)


@app.get("/api/agent/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        configured=settings.configured,
        data_available=repository.is_available(),
        model=settings.model,
    )


@app.get("/api/market/etf/{symbol}")
async def get_market_history(symbol: str) -> dict[str, object]:
    try:
        snapshot = await run_in_threadpool(
            fetch_etf_history,
            symbol,
            base_url=settings.market_api_base,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="真实行情接口暂不可用") from exc
    return {
        "record": snapshot.to_record(),
        "summary": summarize_market_history(snapshot),
    }


@app.post("/api/market/records/{symbol}")
async def save_market_record(symbol: str) -> dict[str, object]:
    try:
        snapshot = await run_in_threadpool(
            fetch_etf_history,
            symbol,
            base_url=settings.market_api_base,
        )
        record = snapshot.to_record()
        await run_in_threadpool(repository.save_market_history_record, record)
        history = repository.get_market_history_summary()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="行情记录保存失败") from exc
    return {
        "status": "ok",
        "record": record,
        "history": history,
    }


@app.get("/api/market/records")
def get_market_records() -> dict[str, object]:
    try:
        return repository.load_market_history()
    except DashboardDataError:
        return {"generated_at": None, "records": []}


@app.get("/api/market/records/{symbol}")
def get_market_record(symbol: str) -> dict[str, object]:
    record = repository.load_market_history_record(symbol)
    if record is None:
        raise HTTPException(status_code=404, detail="未找到该股票代码的记录")
    return {"record": record}


@app.get("/api/market/compare/{symbol_a}/{symbol_b}")
def compare_market_records(symbol_a: str, symbol_b: str) -> dict[str, object]:
    try:
        for symbol in (symbol_a, symbol_b):
            if repository.load_market_history_record(symbol) is None:
                snapshot = fetch_etf_history(symbol, base_url=settings.market_api_base)
                repository.save_market_history_record(snapshot.to_record())
        payload = repository.compare_market_records(symbol_a, symbol_b)
    except DashboardDataError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="真实行情对比失败") from exc
    return payload


@app.post("/api/dashboard/refresh", response_model=RefreshResponse)
async def refresh_dashboard() -> RefreshResponse:
    try:
        payload = await run_in_threadpool(refresh_service.refresh)
    except DashboardDataError as exc:
        raise HTTPException(status_code=503, detail="回测数据暂不可用") from exc
    except DashboardRefreshError as exc:
        raise HTTPException(status_code=503, detail="回测数据刷新失败") from exc

    meta = payload["meta"]
    return RefreshResponse(
        generated_at=str(meta.get("generated_at", "")),
        data_source=str(meta.get("data_source", "")),
        is_demo=bool(meta.get("is_demo")),
        dashboard=payload,
    )


@app.post("/api/agent/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    question = request.question.strip()
    if len(question) < 2:
        raise HTTPException(status_code=422, detail="问题内容不能为空")

    try:
        as_of = repository.as_of()
        answer = await run_in_threadpool(runtime.analyze, question)
    except AgentNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail="尚未配置第三方模型 API") from exc
    except DashboardDataError as exc:
        raise HTTPException(status_code=503, detail="回测数据暂不可用") from exc
    except AgentExecutionError as exc:
        raise HTTPException(status_code=502, detail="模型调用失败，请稍后重试") from exc

    return AnalyzeResponse(
        answer=answer,
        as_of=as_of,
        model=settings.model,
    )
