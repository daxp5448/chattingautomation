# --- builder stage: build a venv using compiled deps, no build tools in the final image ---
FROM python:3.12.7-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- final stage: slim runtime image, no compilers/headers, non-root user ---
FROM python:3.12.7-slim

WORKDIR /app

# asyncpg (the Postgres driver in use, see requirements.txt) is a pure C-extension
# wheel with no libpq dependency at runtime, so no build toolchain is needed here.
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN groupadd -r appuser && useradd -r -g appuser appuser

COPY . .
RUN chown -R appuser:appuser /app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)" || exit 1

USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
