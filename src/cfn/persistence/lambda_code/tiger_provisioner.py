"""Tiger Cloud provisioning Lambda — CFN custom resource backend.

Calls the Tiger Cloud REST API to create/delete a Tiger service. Polls
the service-status endpoint until ready. Writes the connection string to
Secrets Manager. No third-party deps — uses urllib.request + boto3 only
(both available in python3.13 runtime).

Endpoint base: https://console.cloud.tigerdata.com/public/api/v1
Auth: HTTP Basic (access_key:secret_key)
"""

import base64
import json
import time
import urllib.error
import urllib.request

import boto3  # type: ignore[import-untyped]

API_BASE = "https://console.cloud.tigerdata.com/public/api/v1"
POLL_INTERVAL = 10  # seconds
POLL_TIMEOUT = 600  # 10 minutes


def handler(event: dict, context: object) -> None:
    request_type = event["RequestType"]
    physical_id = event.get("PhysicalResourceId", "tiger-pending")
    try:
        if request_type == "Create":
            service_id, conn_url = _create(event)
            _write_secret(event, conn_url)
            _respond(event, "SUCCESS", service_id, {"ConnectionUrl": conn_url})
        elif request_type == "Delete":
            _delete(event, physical_id)
            _respond(event, "SUCCESS", physical_id, {})
        else:
            # Update — recreate-on-change handled by CFN replacing PhysicalResourceId
            _respond(event, "SUCCESS", physical_id, {})
    except Exception as e:  # noqa: BLE001
        _respond(event, "FAILED", physical_id, {"Reason": str(e)})


def _basic_auth_header(access_key: str, secret_key: str) -> str:
    creds = base64.b64encode(f"{access_key}:{secret_key}".encode()).decode()
    return f"Basic {creds}"


def _create(event: dict) -> tuple[str, str]:
    props = event["ResourceProperties"]
    access_key = props["TigerCloudAccessKey"]
    secret_key = props["TigerCloudSecretKey"]
    project_id = props["TigerCloudProjectId"]
    auth = _basic_auth_header(access_key, secret_key)

    body = json.dumps(
        {
            "name": props["DeploymentUuid"][:32],  # Tiger truncates long names
            "region_code": props.get("Region", "us-east-1"),
            "addons": ["time-series"],
            "service_type": "TIMESCALEDB",
        }
    ).encode()
    req = urllib.request.Request(
        f"{API_BASE}/projects/{project_id}/services",
        data=body,
        method="POST",
        headers={"Authorization": auth, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        created = json.loads(resp.read())

    service_id = created["service_id"]
    return service_id, _wait_and_fetch_conn(auth, project_id, service_id)


def _wait_and_fetch_conn(auth: str, project_id: str, service_id: str) -> str:
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        req = urllib.request.Request(
            f"{API_BASE}/projects/{project_id}/services/{service_id}",
            headers={"Authorization": auth},
        )
        with urllib.request.urlopen(req) as resp:  # noqa: S310
            svc = json.loads(resp.read())
        if svc.get("status") == "READY":
            return _build_conn_url(svc)
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Tiger service {service_id} did not become ready in time")


def _build_conn_url(svc: dict) -> str:
    # Tiger returns connection details in the service object once status=READY.
    # Field names per Tiger Cloud REST API docs: hostname, port, username,
    # initial_password, default_db_name.
    host = svc["hostname"]
    port = svc.get("port", 5432)
    user = svc["username"]
    password = svc["initial_password"]
    db = svc.get("default_db_name", "tsdb")
    return f"postgres://{user}:{password}@{host}:{port}/{db}?sslmode=require"


def _delete(event: dict, service_id: str) -> None:
    if service_id in ("tiger-pending", ""):
        return  # nothing was ever provisioned
    props = event["ResourceProperties"]
    auth = _basic_auth_header(
        props["TigerCloudAccessKey"], props["TigerCloudSecretKey"]
    )
    project_id = props["TigerCloudProjectId"]
    req = urllib.request.Request(
        f"{API_BASE}/projects/{project_id}/services/{service_id}",
        method="DELETE",
        headers={"Authorization": auth},
    )
    try:
        urllib.request.urlopen(req)  # noqa: S310
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return  # already deleted
        raise


def _write_secret(event: dict, conn_url: str) -> None:
    sm = boto3.client("secretsmanager")
    deployment_uuid = event["ResourceProperties"]["DeploymentUuid"]
    sm.create_secret(
        Name=f"ems/{deployment_uuid}/persistence/tiger",
        SecretString=conn_url,
    )


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
    urllib.request.urlopen(req)  # noqa: S310
