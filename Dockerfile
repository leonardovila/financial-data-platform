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

# Install build dependencies first (layer caching: this only
# reruns when pyproject.toml changes, not on every code edit)
COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

# ── Stage 2: Runtime ──────────────────────────────────
FROM python:3.11-slim AS runtime

# Non-root user (security best practice — containers should
# never run as root unless they need to bind privileged ports)
RUN groupadd --gid 1000 app && \
    useradd  --uid 1000 --gid app --create-home app

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY financial_data_etl/ ./financial_data_etl/

# Create directories for runtime artifacts
RUN mkdir -p /data logs ws_traces && \
    chown -R app:app /app /data

# Default DB path → /data/ volume (overridable via env)
ENV FORGE_DB_PATH=/data/financial_data_etl.db
ENV PYTHONUNBUFFERED=1

USER app

EXPOSE 8000

# Default: run the API. Override in docker-compose for ETL.
CMD ["uvicorn", "financial_data_etl.api.app:app", \
     "--host", "0.0.0.0", "--port", "8000"]
