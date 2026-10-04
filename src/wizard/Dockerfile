# Built locally on the appliance by setup.sh (no registry yet — see
# src/wizard/README.md for the versioned-S3-artifact plan this is a
# stand-in for). Dependency versions match pyproject.toml's floors exactly.
#
# Build context must be the directory containing src/ (so `src.wizard.main`
# imports correctly) — see setup.sh's `docker build -f src/wizard/Dockerfile .`
FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    "classy-fastapi>=0.6.1" \
    "fastapi>=0.116.1" \
    "pydantic>=2.11.7" \
    "uvicorn>=0.34.0"

COPY src /app/src
ENV PYTHONPATH=/app

EXPOSE 8080
CMD ["python", "-m", "src.wizard.main"]
