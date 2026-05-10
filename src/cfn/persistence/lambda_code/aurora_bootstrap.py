"""Aurora bootstrap Lambda — runs once at stack-create.

Creates the ems_document + ems_vector databases, installs the vector
extension on ems_vector, creates least-privilege app users for each
database, and writes their conn strings to Secrets Manager. Not
imported by application code — the source is read as text by
aurora_resources.py and embedded in CFN as Code.ZipFile.

Lambda runtime: python3.13. Dependencies: psycopg2 via Lambda Layer
(arn configured in aurora_resources.py). boto3 + urllib.request are
built into the runtime.
"""

import json
import secrets
import urllib.request

import boto3  # type: ignore[import-untyped]
import psycopg2  # type: ignore[import-untyped]


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
    except Exception as e:  # noqa: BLE001 — Lambda must always reply
        _respond(event, "FAILED", physical_id, {"Reason": str(e)})


def _create(event: dict) -> dict:
    props = event["ResourceProperties"]
    cluster_endpoint = props["ClusterEndpoint"]
    master_secret_arn = props["MasterSecretArn"]
    deployment_uuid = props["DeploymentUuid"]

    sm = boto3.client("secretsmanager")
    master = json.loads(sm.get_secret_value(SecretId=master_secret_arn)["SecretString"])

    # Generate app-user passwords up front so we can write them to SM
    # before SQL runs (idempotent recovery on Lambda retry).
    doc_pw = secrets.token_urlsafe(32)
    vec_pw = secrets.token_urlsafe(32)

    # psycopg2's `with connect(...) as conn` begins a transaction on entry;
    # CREATE DATABASE / CREATE USER must run outside any transaction. Manage
    # the connection manually so autocommit takes effect before the first
    # statement.
    admin_conn = psycopg2.connect(
        host=cluster_endpoint,
        user=master["username"],
        password=master["password"],
        dbname="postgres",
    )
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute("CREATE DATABASE ems_document")
            cur.execute("CREATE DATABASE ems_vector")
            cur.execute(f"CREATE USER ems_doc_app WITH PASSWORD '{doc_pw}'")
            cur.execute(f"CREATE USER ems_vec_app WITH PASSWORD '{vec_pw}'")
            cur.execute("GRANT ALL PRIVILEGES ON DATABASE ems_document TO ems_doc_app")
            cur.execute("GRANT ALL PRIVILEGES ON DATABASE ems_vector TO ems_vec_app")
    finally:
        admin_conn.close()

    vector_conn = psycopg2.connect(
        host=cluster_endpoint,
        user=master["username"],
        password=master["password"],
        dbname="ems_vector",
    )
    vector_conn.autocommit = True
    try:
        with vector_conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    finally:
        vector_conn.close()

    doc_url = f"postgres://ems_doc_app:{doc_pw}@{cluster_endpoint}:5432/ems_document"
    vec_url = f"postgres://ems_vec_app:{vec_pw}@{cluster_endpoint}:5432/ems_vector"

    sm.create_secret(
        Name=f"ems/{deployment_uuid}/persistence/aurora-document",
        SecretString=doc_url,
    )
    sm.create_secret(
        Name=f"ems/{deployment_uuid}/persistence/aurora-vector",
        SecretString=vec_url,
    )

    return {
        "DocumentSecretName": f"ems/{deployment_uuid}/persistence/aurora-document",
        "VectorSecretName": f"ems/{deployment_uuid}/persistence/aurora-vector",
    }


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
    urllib.request.urlopen(req)  # noqa: S310 — CFN-signed presigned URL
