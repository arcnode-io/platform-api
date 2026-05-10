"""Integration tests for the Neo4j Aura provisioning Lambda.

Vendor REST API mocked via `unittest.mock.patch('urllib.request.urlopen')`.
AWS Secrets Manager mocked by a LocalStack container started inline.
"""

import importlib.util
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import boto3

from tests.fixtures.containers import start_localstack

LAMBDA_PATH = (
    Path(__file__).parent.parent.parent
    / "src"
    / "cfn"
    / "persistence"
    / "lambda_code"
    / "aura_provisioner.py"
)
DEPLOYMENT_UUID = "abcd1234-5678-90ef-1234-567890abcdef"


def _load_module():
    spec = importlib.util.spec_from_file_location("aura_provisioner", LAMBDA_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_event(request_type: str = "Create") -> dict[str, Any]:
    return {
        "RequestType": request_type,
        "ResponseURL": "https://cfn-response.example/path",
        "StackId": "arn:aws:cloudformation:us-east-1:123:stack/test/abc",
        "RequestId": "req-123",
        "LogicalResourceId": "AuraCustomResource",
        "ResourceProperties": {
            "Neo4jAuraClientId": "client-xyz",
            "Neo4jAuraClientSecret": "secret-xyz",
            "Neo4jAuraTenantId": "tenant-abc",
            "DeploymentUuid": DEPLOYMENT_UUID,
        },
    }


class _FakeResp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body


def _ctx(resp: _FakeResp) -> MagicMock:
    m = MagicMock()
    m.__enter__ = lambda self: resp
    m.__exit__ = lambda *a: None
    return m


def test_create_provisions_aura_instance_and_writes_secret_to_localstack() -> None:
    """Full happy-path: vendor OAuth + create + poll mocked, secret hits LocalStack."""
    # Arrange
    with start_localstack(services=("secretsmanager",)) as ls:
        sm_client = boto3.client(
            "secretsmanager",
            endpoint_url=ls.url,
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

        with (
            patch.dict(
                "os.environ",
                {
                    "AWS_ENDPOINT_URL": ls.url,
                    "AWS_DEFAULT_REGION": "us-east-1",
                    "AWS_ACCESS_KEY_ID": "test",
                    "AWS_SECRET_ACCESS_KEY": "test",
                },
            ),
            patch("urllib.request.urlopen") as urlopen,
        ):
            # Sequence: token exchange → create → poll (running) → CFN PUT
            urlopen.side_effect = [
                _ctx(_FakeResp(json.dumps({"access_token": "tok-123"}).encode())),
                _ctx(
                    _FakeResp(
                        json.dumps(
                            {
                                "data": {
                                    "id": "instance-789",
                                    "connection_url": "neo4j+s://instance-789.databases.neo4j.io",
                                    "username": "neo4j",
                                    "password": "graph-pw",
                                    "status": "creating",
                                }
                            }
                        ).encode()
                    )
                ),
                _ctx(_FakeResp(json.dumps({"data": {"status": "running"}}).encode())),
                _ctx(_FakeResp(b"")),  # CFN callback PUT
            ]

            mod = _load_module()

            # Act
            mod.handler(_make_event(), context=None)

            # Assert: token exchange used Basic auth on /oauth/token
            token_call = urlopen.call_args_list[0]
            token_req = token_call.args[0]
            assert token_req.full_url == "https://api.neo4j.io/oauth/token"
            assert "Basic " in token_req.headers["Authorization"]
            assert b"grant_type=client_credentials" in token_req.data

            # Assert: create posted to /v1/instances with Bearer token + tenant_id
            create_call = urlopen.call_args_list[1]
            create_req = create_call.args[0]
            assert create_req.full_url == "https://api.neo4j.io/v1/instances"
            assert create_req.headers["Authorization"] == "Bearer tok-123"
            create_body = json.loads(create_req.data)
            assert create_body["tenant_id"] == "tenant-abc"
            assert create_body["cloud_provider"] == "aws"

            # Assert: secret landed in LocalStack
            secret = sm_client.get_secret_value(
                SecretId=f"ems/{DEPLOYMENT_UUID}/persistence/neo4j-aura"
            )
            payload = json.loads(secret["SecretString"])
            assert payload["uri"] == "neo4j+s://instance-789.databases.neo4j.io"
            assert payload["username"] == "neo4j"
            assert payload["password"] == "graph-pw"

            # Assert: CFN callback was SUCCESS with the instance id as PhysicalResourceId
            cfn_call = urlopen.call_args_list[3]
            cfn_body = json.loads(cfn_call.args[0].data)
            assert cfn_body["Status"] == "SUCCESS"
            assert cfn_body["PhysicalResourceId"] == "instance-789"
