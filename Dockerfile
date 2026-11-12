FROM python:3.15-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GC_ANALYTICS_DATABASE=/data/analytics.sqlite3
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY analytics ./analytics
RUN python -m pip install --no-cache-dir . \
    && groupadd --system --gid 10001 appgroup \
    && useradd --system --uid 10001 --gid appgroup --home /nonexistent appuser \
    && mkdir /data && chown appuser:appgroup /data
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)" || exit 1
CMD ["uvicorn", "analytics.app:build", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--workers", "1"]
