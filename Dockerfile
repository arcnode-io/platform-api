FROM python:3.14-slim AS builder
WORKDIR /app
COPY pyproject.toml uv.lock .
RUN pip install uv && uv sync --frozen
COPY cfg.yml .
COPY src src
RUN find src -name "test_*.py" -delete

FROM python:3.14-slim AS production
WORKDIR /app
# xorriso bakes each on-prem order into the appliance ISO (src/iso/iso_service.py).
RUN apt-get update && apt-get install -y --no-install-recommends xorriso \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock .
RUN pip install uv && uv sync --frozen --no-dev --no-install-project
COPY --from=builder /app/src ./src
COPY cfg.yml .
CMD ["uv", "run", "-m", "src.main"]
