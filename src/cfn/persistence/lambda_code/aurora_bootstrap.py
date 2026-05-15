"""Aurora bootstrap Lambda — runs once at stack-create per variant.

Reads ``Slices`` from the CFN custom resource properties (e.g.
``["document", "vector"]`` for commercial, ``["document", "vector",
"timeseries"]`` for defense) and:

  1. Creates one Postgres database per slice (idempotent — checks
     ``pg_database`` first).
  2. Installs the per-slice extension when needed (``pgvector`` for vector,
     ``pg_partman`` for timeseries).
  3. Creates a least-privilege per-slice app user with a generated password.
  4. For timeseries: hardcoded SQL creates the ``measurements`` parent table
     (partitioned by RANGE on ``ts``) and registers it with pg_partman.
  5. Writes each slice's connection URL to Secrets Manager under
     ``arcnode-ems-{STACK}/<slice>-url``.

Not imported by application code — the source is read as text by
``aurora_resources.py`` and embedded in CFN as ``Code.ZipFile``.

Lambda runtime: python3.13. Dependencies: psycopg2 via Lambda Layer (arn
configured in ``aurora_resources.py``). boto3 + urllib.request are built
into the runtime.
"""

import json
import secrets
import urllib.request

import boto3  # type: ignore[import-untyped]
import psycopg2  # type: ignore[import-untyped]

# Slice → (db_name, app_user, extension or None).
SLICE_SPECS: dict[str, tuple[str, str, str | None]] = {
    "document": ("ems_document", "ems_doc_app", None),
    "vector": ("ems_vector", "ems_vec_app", "vector"),
    "timeseries": ("ems_timeseries", "ems_ts_app", "pg_partman"),
}

# measurements — the broker-ingest landing table. Every MQTT publish a
# gateway sends gets written here by the EMQX rule. JSONB value column
# matches the polymorphic MQTT payload (float | bool | enum). Hourly
# partitions managed by pg_partman with 7-day retention (rolled-off
# partitions dropped, not archived). Analyst-API consumers read from this
# same table.
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
    """
    UPDATE partman.part_config
       SET retention = '7 days',
           retention_keep_table = false
     WHERE parent_table = 'public.measurements'
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_measurements_lookup
        ON measurements (site_id, device_id, measurement, ts DESC)
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
    master_secret_arn = props["MasterSecretArn"]
    deployment_uuid = props["DeploymentUuid"]
    slices: list[str] = props["Slices"]

    sm = boto3.client("secretsmanager")
    master = json.loads(sm.get_secret_value(SecretId=master_secret_arn)["SecretString"])

    # Phase 1 — connect to the cluster's admin db and create the per-slice
    # database + app user. CREATE DATABASE must run outside any transaction,
    # so we manage the connection by hand and force autocommit.
    admin_conn = psycopg2.connect(
        host=cluster_endpoint,
        user=master["username"],
        password=master["password"],
        dbname="postgres",
    )
    admin_conn.autocommit = True
    slice_passwords: dict[str, str] = {}
    try:
        with admin_conn.cursor() as cur:
            for slice_name in slices:
                db_name, app_user, _ext = SLICE_SPECS[slice_name]
                pw = secrets.token_urlsafe(32)
                slice_passwords[slice_name] = pw
                _create_db_if_missing(cur, db_name)
                _create_user_if_missing(cur, app_user, pw)
                cur.execute(f"GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {app_user}")
    finally:
        admin_conn.close()

    # Phase 2 — connect to each slice's own db and install extensions /
    # bootstrap the timeseries schema. Each connection is independent;
    # autocommit so CREATE EXTENSION takes effect immediately.
    for slice_name in slices:
        db_name, app_user, ext = SLICE_SPECS[slice_name]
        slice_conn = psycopg2.connect(
            host=cluster_endpoint,
            user=master["username"],
            password=master["password"],
            dbname=db_name,
        )
        slice_conn.autocommit = True
        try:
            with slice_conn.cursor() as cur:
                # Postgres 15+ revokes CREATE on public schema from PUBLIC.
                # The per-slice app user owns its slice's data, so make it
                # owner of public + grant on the bootstrap schema.
                cur.execute(f"ALTER SCHEMA public OWNER TO {app_user}")
                cur.execute(f"GRANT ALL ON SCHEMA public TO {app_user}")
                # Default privileges so any future tables (partman child
                # partitions, app migrations) auto-grant to the app user.
                cur.execute(
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                    f"GRANT ALL ON TABLES TO {app_user}"
                )
                cur.execute(
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                    f"GRANT ALL ON SEQUENCES TO {app_user}"
                )
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
                # Grant on tables created above (measurements + partman
                # child partitions, pgvector tables, etc.) — these were
                # created as the master user, so app_user has no perms
                # by default. Default-privileges only catches future
                # tables, not this batch.
                cur.execute(
                    f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {app_user}"
                )
                cur.execute(
                    f"GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO {app_user}"
                )
        finally:
            slice_conn.close()

    # Phase 3 — write per-slice connection URLs to Secrets Manager. Naming
    # follows the Q4 lock: arcnode-ems-{STACK}/<slice>-url.
    secret_names: dict[str, str] = {}
    for slice_name in slices:
        db_name, app_user, _ext = SLICE_SPECS[slice_name]
        pw = slice_passwords[slice_name]
        url = f"postgres://{app_user}:{pw}@{cluster_endpoint}:5432/{db_name}"
        name = f"arcnode-ems-{deployment_uuid}/{slice_name}-url"
        _put_secret(sm, name, url)
        secret_names[slice_name] = name

    return {"SecretNames": secret_names, "Slices": slices}


from typing import Any  # noqa: E402 — psycopg2/boto3 are runtime-only deps


def _create_db_if_missing(cur: Any, db_name: str) -> None:
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
    if cur.fetchone() is None:
        cur.execute(f"CREATE DATABASE {db_name}")


def _create_user_if_missing(cur: Any, user: str, password: str) -> None:
    cur.execute("SELECT 1 FROM pg_user WHERE usename = %s", (user,))
    if cur.fetchone() is None:
        cur.execute(f"CREATE USER {user} WITH PASSWORD '{password}'")
    else:
        cur.execute(f"ALTER USER {user} WITH PASSWORD '{password}'")


def _put_secret(sm: Any, name: str, value: str) -> None:
    try:
        sm.create_secret(Name=name, SecretString=value)
    except sm.exceptions.ResourceExistsException:
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
