# ────────────────────────────────────────────────────────
#  financial-data-etl  ·  Backend image (API + ETL)
#
#  Single image, two entrypoints:
#    API → uvicorn financial_data_etl.api.app:app
#    ETL → python -m financial_data_etl.main_runner
#
#  Multi-stage build:
#    Stage 1 (builder): install deps + compile wheels
#    Stage 2 (runtime): slim image with only what we need
# ────────────────────────────────────────────────────────

# ── Stage 1: Builder ──────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# libpq-dev needed to compile psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

# ── Stage 2: Runtime ──────────────────────────────────
FROM python:3.11-slim AS runtime

# libpq is needed at runtime for psycopg2 to talk to PostgreSQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 app && \
    useradd  --uid 1000 --gid app --create-home app

WORKDIR /app

COPY --from=builder /install /usr/local
COPY financial_data_etl/ ./financial_data_etl/

RUN mkdir -p logs ws_traces && \
    chown -R app:app /app

ENV PYTHONUNBUFFERED=1

USER app

EXPOSE 8000

CMD ["uvicorn", "financial_data_etl.api.app:app", \
     "--host", "0.0.0.0", "--port", "8000"]
