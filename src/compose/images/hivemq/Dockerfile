# Custom HiveMQ CE image — File RBAC auth baked in, Allow-All stripped.
#
# Vanilla hivemq-ce ships the "Allow All" extension enabled, so anonymous
# pub/sub works out of the box. We replace it with the File RBAC extension
# (username/password + topic ACL) so the broker rejects anonymous and
# enforces per-role topic permissions. Baked (not runtime-fetched) for the
# same reason telemetry-writer is — airgap-clean + version-pinned.
#
# credentials.xml is NOT baked — it carries per-deploy passwords and is
# bind-mounted at runtime from /opt/arcnode (written by UserData from
# Secrets Manager). extension-config.xml IS baked (static policy).
FROM hivemq/hivemq-ce:latest

# Pin to the File RBAC release that matches CE 2024+/extension SDK.
ARG RBAC_VERSION=4.6.14
ARG RBAC_URL=https://github.com/hivemq/hivemq-file-rbac-extension/releases/download/${RBAC_VERSION}/hivemq-file-rbac-extension-${RBAC_VERSION}.zip

USER root
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends unzip; \
    # Strip Allow-All — otherwise it short-circuits auth and File RBAC never runs.
    rm -rf /opt/hivemq/extensions/hivemq-allow-all-extension; \
    curl -fsSL --retry 5 --retry-delay 2 "${RBAC_URL}" -o /tmp/rbac.zip; \
    unzip -q /tmp/rbac.zip -d /opt/hivemq/extensions/; \
    rm /tmp/rbac.zip; \
    apt-get purge -y unzip; apt-get autoremove -y; rm -rf /var/lib/apt/lists/*

# Baked static policy: hashed-vs-plain + how often the broker re-reads
# credentials.xml (so a deploy-time rewrite is picked up without restart).
# conf/ is the current location; the legacy root location is deprecated.
# Build context = repo root (mirrors telemetry-writer). CI invokes:
#   docker build -t public.ecr.aws/y1d2j6a8/ems-hivemq:latest \
#     -f src/compose/images/hivemq/Dockerfile .
RUN mkdir -p /opt/hivemq/extensions/hivemq-file-rbac-extension/conf
COPY src/compose/images/hivemq/extension-config.xml /opt/hivemq/extensions/hivemq-file-rbac-extension/conf/config.xml
