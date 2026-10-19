"""Aurora bootstrap Lambda — runs once at stack-create per variant.

Reads ``Slices`` from the CFN custom resource properties (e.g.
``["document", "vector", "dercontrol"]`` for commercial, plus
``"timeseries"`` for defense) and:

  1. Creates one Postgres database per slice (idempotent — checks
     ``pg_database`` first).
  2. Installs the per-slice extension when needed (``pgvector`` for vector,
     ``pg_partman`` for timeseries).
  3. For timeseries: hardcoded SQL creates the ``measurements`` parent table
     (partitioned by RANGE on ``ts``), registers it with pg_partman, and
     schedules pg_partman's hourly maintenance with pg_cron.
  4. Writes each slice's connection URL to Secrets Manager under
     ``arcnode-ems-{STACK}/<slice>-url``. Every URL logs in as the master
     user with the customer's database password, same as on-prem: one
     password, no per-service roles.

Not imported by application code — the source is read as text by
``aurora_resources.py`` and embedded in CFN as ``Code.ZipFile``.

Lambda runtime: python3.13. Dependencies: psycopg2 via Lambda Layer (arn
configured in ``aurora_resources.py``). boto3 + urllib.request are built
into the runtime.
"""

import json
import urllib.parse
import urllib.request

import boto3  # type: ignore[import-untyped]
import psycopg2  # type: ignore[import-untyped]

# Slice → (db_name, extension or None).
SLICE_SPECS: dict[str, tuple[str, str | None]] = {
    "document": ("ems_document", None),
    "vector": ("ems_vector", "vector"),
    "timeseries": ("ems_timeseries", "pg_partman"),
    # ems-der-control-api's DB. No extension — Hibernate ddl-auto=update builds
    # the schema on first boot, same as device-api does in the document slice.
    "dercontrol": ("ems_dercontrol", None),
}

# measurements — the broker-ingest landing table. Every MQTT publish a
# gateway sends gets written here by the telemetry-writer sidecar. JSONB value column
# matches the polymorphic MQTT payload (float | bool | enum). Hourly
# partitions managed by pg_partman; telemetry-writer sets the retention
# window the customer picked (expired partitions are dropped, not archived).
# Analyst-API consumers read from this same table.
MEASUREMENTS_SCHEMA_SQL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS measurements (
        ts          TIMESTAMPTZ NOT NULL,
        site_id     TEXT        NOT NULL,
        device_id   TEXT        NOT NULL,
        measurement TEXT        NOT NULL,
        unit        TEXT        NOT NULL,
        value       JSONB       NOT NULL
    ) PARTITION BY RANGE (ts)
    """,
    """
    SELECT partman.create_parent(
        p_parent_table => 'public.measurements',
        p_control      => 'ts',
        p_interval     => '1 hour',
        p_premake      => 4
    )
    WHERE NOT EXISTS (
        SELECT 1 FROM partman.part_config
        WHERE parent_table = 'public.measurements'
    )
    """,
    # Reason: keep making partitions on schedule even through a gap in telemetry.
    """
    UPDATE partman.part_config
       SET infinite_time_partitions = true
     WHERE parent_table = 'public.measurements'
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_measurements_lookup
        ON measurements (site_id, device_id, measurement, ts DESC)
    """,
)


# pg_partman only makes and drops partitions when its maintenance runs. pg_cron
# keeps its jobs in the postgres db (Aurora's cron.database_name) and runs this
# one in ems_timeseries. Same job name → re-running updates it, no duplicate.
PARTITION_MAINTENANCE_SQL: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS pg_cron",
    """
    SELECT cron.schedule_in_database(
        'partman-maintenance',
        '@hourly',
        'CALL partman.run_maintenance_proc()',
        'ems_timeseries'
    )
    """,
)


def handler(event: dict, context: object) -> None:
    request_type = event["RequestType"]
    physical_id = event.get("PhysicalResourceId", "aurora-bootstrap")
    try:
        if request_type == "Create":
            data = _create(event)
            _respond(event, "SUCCESS", physical_id, data)
        else:
            # Update + Delete are no-ops; databases persist across stack updates,
            # and stack-delete drops the entire cluster anyway.
            _respond(event, "SUCCESS", physical_id, {})
    except Exception as e:
        _respond(event, "FAILED", physical_id, {"Reason": str(e)})


def _create(event: dict) -> dict:
    props = event["ResourceProperties"]
    cluster_endpoint = props["ClusterEndpoint"]
    master_user = props["MasterUsername"]
    deployment_uuid = props["DeploymentUuid"]
    slices: list[str] = props["Slices"]

    sm = boto3.client("secretsmanager")
    # The customer's DbPassword parameter, held as a plain string.
    master_pw = sm.get_secret_value(SecretId=props["MasterSecretArn"])["SecretString"]

    # Phase 1 — create the per-slice databases. CREATE DATABASE must run
    # outside any transaction, so force autocommit.
    admin_conn = psycopg2.connect(
        host=cluster_endpoint, user=master_user, password=master_pw, dbname="postgres"
    )
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            for slice_name in slices:
                db_name, _ext = SLICE_SPECS[slice_name]
                _create_db_if_missing(cur, db_name)
    finally:
        admin_conn.close()

    # Phase 2 — connect to each slice's own db and install extensions /
    # bootstrap the timeseries schema.
    for slice_name in slices:
        db_name, ext = SLICE_SPECS[slice_name]
        slice_conn = psycopg2.connect(
            host=cluster_endpoint, user=master_user, password=master_pw, dbname=db_name
        )
        slice_conn.autocommit = True
        try:
            with slice_conn.cursor() as cur:
                if ext == "pg_partman":
                    # pg_partman publishes its functions in a dedicated
                    # schema; create it first so the extension lands there
                    # and `partman.create_parent(...)` resolves.
                    cur.execute("CREATE SCHEMA IF NOT EXISTS partman")
                    cur.execute(
                        "CREATE EXTENSION IF NOT EXISTS pg_partman SCHEMA partman"
                    )
                elif ext:
                    cur.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
                if slice_name == "timeseries":
                    for stmt in MEASUREMENTS_SCHEMA_SQL:
                        cur.execute(stmt)
        finally:
            slice_conn.close()

    if "timeseries" in slices:
        _run_in_postgres_db(cluster_endpoint, master_user, master_pw)

    # Phase 3 — write per-slice connection URLs to Secrets Manager.
    # Reason: the customer picks the password, so it's percent-encoded to survive the URL.
    user = urllib.parse.quote(master_user, safe="")
    pw = urllib.parse.quote(master_pw, safe="")
    secret_names: dict[str, str] = {}
    for slice_name in slices:
        db_name, _ext = SLICE_SPECS[slice_name]
        url = f"postgres://{user}:{pw}@{cluster_endpoint}:5432/{db_name}"
        name = f"arcnode-ems-{deployment_uuid}/{slice_name}-url"
        _put_secret(sm, name, url)
        secret_names[slice_name] = name

    return {"SecretNames": secret_names, "Slices": slices}


from typing import Any  # noqa: E402 — psycopg2/boto3 are runtime-only deps


def _create_db_if_missing(cur: Any, db_name: str) -> None:
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
    if cur.fetchone() is None:
        cur.execute(f"CREATE DATABASE {db_name}")


def _run_in_postgres_db(cluster_endpoint: str, user: str, password: str) -> None:
    """Schedule partition maintenance from the postgres db, where pg_cron lives."""
    conn = psycopg2.connect(
        host=cluster_endpoint, user=user, password=password, dbname="postgres"
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for stmt in PARTITION_MAINTENANCE_SQL:
                cur.execute(stmt)
    finally:
        conn.close()


def _put_secret(sm: Any, name: str, value: str) -> None:
    """Overwrite the CFN-created secret's placeholder with the real URL.

    The per-slice secrets are declared as CFN AWS::SecretsManager::Secret
    resources in aurora_resources.py — created with a fixed placeholder
    before the bootstrap Lambda runs. This call only writes
    the real value; CFN owns the lifecycle (delete cleans automatically,
    no orphans).
    """
    sm.put_secret_value(SecretId=name, SecretString=value)


def _respond(event: dict, status: str, physical_id: str, data: dict) -> None:
    body = json.dumps(
        {
            "Status": status,
            "Reason": data.get("Reason", "see CloudWatch logs"),
            "PhysicalResourceId": physical_id,
            "StackId": event["StackId"],
            "RequestId": event["RequestId"],
            "LogicalResourceId": event["LogicalResourceId"],
            "Data": {k: v for k, v in data.items() if k != "Reason"},
        }
    ).encode()
    req = urllib.request.Request(
        event["ResponseURL"],
        data=body,
        method="PUT",
        headers={"content-type": "", "content-length": str(len(body))},
    )
    urllib.request.urlopen(req)
