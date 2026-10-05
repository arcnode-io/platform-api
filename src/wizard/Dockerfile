# Local dev/test convenience only — the appliance itself runs this
# natively now (apt-installed python3-fastapi/uvicorn/pydantic via
# setup.sh), not via Docker, so provisioning has no dependency on PyPI
# being reachable. This file exists so `docker run` + a real browser is
# still the fast local verification loop for wizard changes (see
# MANUAL_TESTS.md). Dependency versions match pyproject.toml's floors.
#
# Build context must be the directory containing src/ (so `src.wizard.main`
# imports correctly) — see setup.sh's `docker build -f src/wizard/Dockerfile .`
FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    "fastapi>=0.116.1" \
    "pydantic>=2.11.7" \
    "uvicorn>=0.34.0"

COPY src /app/src
ENV PYTHONPATH=/app

EXPOSE 8080
CMD ["python", "-m", "src.wizard.main"]
