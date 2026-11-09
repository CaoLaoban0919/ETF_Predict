FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AGNO_TELEMETRY=false

WORKDIR /app

COPY requirements-agent.txt ./requirements-agent.txt
RUN pip install --no-cache-dir -r requirements-agent.txt

COPY agent/ ./agent/
COPY core/ ./core/

EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=4s --start-period=8s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/agent/health', timeout=3)" || exit 1

CMD ["uvicorn", "agent.app:app", "--host", "0.0.0.0", "--port", "8000"]
