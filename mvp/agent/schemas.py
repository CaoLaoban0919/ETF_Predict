from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)


class AnalyzeResponse(BaseModel):
    answer: str
    as_of: str
    model: str
    runtime: str = "agno"


class HealthResponse(BaseModel):
    status: str = "ok"
    configured: bool
    data_available: bool
    model: str
    runtime: str = "agno"


class RefreshResponse(BaseModel):
    status: str = "ok"
    generated_at: str
    data_source: str
    is_demo: bool
    dashboard: dict[str, object]
