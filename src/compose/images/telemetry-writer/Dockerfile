# MQTT → postgres-timeseries bridge image for all three EMS variants.
#
# Replaces the previous pattern (python:3.13-alpine + runtime
# `pip install paho-mqtt psycopg2-binary` + bind-mount of the script).
# That pattern restart-loops if the box reboots offline (real bug on
# appliance; resilience gap on commercial / defense).
#
# Image used by:
#   - src/compose/commercial/docker-compose.yaml
#   - src/compose/defense/docker-compose.yaml
#   - platform-ems-iso appliance/compose/docker-compose.yaml
#
# Build context = repo root (so we COPY the canonical script from
# src/compose/init-scripts/). CI invokes:
#   docker build -t public.ecr.aws/y1d2j6a8/ems-telemetry-writer:latest \
#     -f src/compose/images/telemetry-writer/Dockerfile .

FROM python:3.13-alpine

# Pinned: paho-mqtt 2.x required (script uses CallbackAPIVersion.VERSION2).
# psycopg2-binary 2.9.x is the current stable for postgres 15/16.
RUN pip install --no-cache-dir \
    paho-mqtt==2.1.0 \
    psycopg2-binary==2.9.10

WORKDIR /app
COPY src/compose/init-scripts/telemetry_writer.py /app/telemetry_writer.py

CMD ["python", "/app/telemetry_writer.py"]
