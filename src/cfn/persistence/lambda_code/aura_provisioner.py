"""Neo4j Aura provisioning Lambda — CFN custom resource backend.

Exchanges the operator-supplied OAuth client id+secret for a bearer token
via Aura's client_credentials grant, then POSTs to /v1/instances to create
the database. Polls /v1/instances/<id> until status == 'running'. Writes
the bolt URI + credentials to Secrets Manager.

Endpoint base: https://api.neo4j.io
Token URL: https://api.neo4j.io/oauth/token
"""

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import boto3  # type: ignore[import-untyped]

API_BASE = "https://api.neo4j.io"
TOKEN_URL = f"{API_BASE}/oauth/token"
POLL_INTERVAL = 15
POLL_TIMEOUT = 900  # 15 min — Aura cold-start can be slow


def handler(event: dict, context: object) -> None:
    request_type = event["RequestType"]
    physical_id = event.get("PhysicalResourceId", "aura-pending")
    try:
        if request_type == "Create":
            instance_id, payload = _create(event)
            _write_secret(event, payload)
            _respond(event, "SUCCESS", instance_id, {"InstanceId": instance_id})
        elif request_type == "Delete":
            _delete(event, physical_id)
            _respond(event, "SUCCESS", physical_id, {})
        else:
            _respond(event, "SUCCESS", physical_id, {})
    except Exception as e:
        _respond(event, "FAILED", physical_id, {"Reason": str(e)})


def _token(client_id: str, client_secret: str) -> str:
    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["access_token"]


def _create(event: dict) -> tuple[str, dict]:
    props = event["ResourceProperties"]
    token = _token(props["Neo4jAuraClientId"], props["Neo4jAuraClientSecret"])

    body = json.dumps(
        {
            "name": props["DeploymentUuid"][:30],  # Aura name length cap
            "version": "5",
            "region": props.get("Region", "us-east-1"),
            "memory": "1GB",
            "type": "free-db",
            "tenant_id": props["Neo4jAuraTenantId"],
            "cloud_provider": "aws",
        }
    ).encode()
    req = urllib.request.Request(
        f"{API_BASE}/v1/instances",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        created = json.loads(resp.read())["data"]
    instance_id = created["id"]
    # Aura returns initial credentials in the create response; conn URL only
    # becomes valid once status=running.
    payload = {
        "uri": created["connection_url"],
        "username": created["username"],
        "password": created["password"],
    }
    _wait_running(token, instance_id)
    return instance_id, payload


def _wait_running(token: str, instance_id: str) -> None:
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        req = urllib.request.Request(
            f"{API_BASE}/v1/instances/{instance_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req) as resp:
            status = json.loads(resp.read())["data"]["status"]
        if status == "running":
            return
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Aura instance {instance_id} did not start in time")


def _delete(event: dict, instance_id: str) -> None:
    if instance_id in ("aura-pending", ""):
        return
    props = event["ResourceProperties"]
    token = _token(props["Neo4jAuraClientId"], props["Neo4jAuraClientSecret"])
    req = urllib.request.Request(
        f"{API_BASE}/v1/instances/{instance_id}",
        method="DELETE",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return
        raise


def _write_secret(event: dict, payload: dict) -> None:
    sm = boto3.client("secretsmanager")
    deployment_uuid = event["ResourceProperties"]["DeploymentUuid"]
    sm.create_secret(
        Name=f"ems/{deployment_uuid}/persistence/neo4j-aura",
        SecretString=json.dumps(payload),
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
    urllib.request.urlopen(req)
