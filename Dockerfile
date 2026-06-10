FROM python:3.12-slim AS builder
WORKDIR /app

# official uv binary, pinnable, no pip download step
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

# cache and site-packages are on different mounts, so copy instead of hardlink
ENV UV_LINK_MODE=copy

COPY pyproject.toml ./
COPY webcaldav/ webcaldav/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system .

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