FROM python:3.12-slim AS builder
WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
COPY webcaldav/ webcaldav/

RUN uv pip install --system --no-cache .

# ── Runtime ──
FROM python:3.12-slim
WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY webcaldav/ webcaldav/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL="sqlite+aiosqlite:////data/webcaldav.db"

VOLUME ["/data"]
EXPOSE 8000

CMD ["uvicorn", "webcaldav.app:app", "--host", "0.0.0.0", "--port", "8000"]
