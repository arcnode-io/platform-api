"""Integration tests for the Tiger Cloud provisioning Lambda.

Vendor REST API mocked via `unittest.mock.patch('urllib.request.urlopen')` —
we don't hit Tiger's real API in CI. AWS Secrets Manager is mocked by a
LocalStack container started inline. Verifies the handler:

1. Calls the Tiger create-service endpoint with the right Basic-auth header
2. Polls until status=READY
3. Writes the resulting Postgres URL to LocalStack Secrets Manager
4. Sends a SUCCESS callback to the CFN ResponseURL

Lambda source is loaded via importlib (same pattern as the smoke tests).
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
    / "tiger_provisioner.py"
)
DEPLOYMENT_UUID = "abcd1234-5678-90ef-1234-567890abcdef"


def _load_module():
    spec = importlib.util.spec_from_file_location("tiger_provisioner", LAMBDA_PATH)
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
        "LogicalResourceId": "TigerCustomResource",
        "ResourceProperties": {
            "TigerCloudAccessKey": "alice",
            "TigerCloudSecretKey": "wonderland",
            "TigerCloudProjectId": "proj-123",
            "DeploymentUuid": DEPLOYMENT_UUID,
        },
    }


def _mock_urlopen_responses(*payloads: dict | str) -> MagicMock:
    """Build a urlopen mock that returns each payload in sequence.

    Each entry is JSON-serialized (or used as-is for the empty CFN PUT response).
    """
    mock_responses = []
    for p in payloads:
        body = json.dumps(p).encode() if isinstance(p, dict) else p.encode()
        m = MagicMock()
        m.__enter__ = lambda self, b=body: _FakeResp(b)
        m.__exit__ = lambda *a: None
        mock_responses.append(m)
    return MagicMock(side_effect=mock_responses)


class _FakeResp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body


def test_create_provisions_tiger_service_and_writes_secret_to_localstack() -> None:
    """Full happy-path: vendor API mocked, Secrets Manager hit via LocalStack."""
    # Arrange — start LocalStack with the secretsmanager service
    with start_localstack(services=("secretsmanager",)) as ls:
        sm_client = boto3.client(
            "secretsmanager",
            endpoint_url=ls.url,
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

        # The Lambda creates its own boto3 client at module level (boto3.client
        # in _write_secret); we need it to point at LocalStack. The standard
        # AWS SDK env var for endpoint override is AWS_ENDPOINT_URL.
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
            # Mock urlopen sequence: create response → poll response (READY) →
            # CFN callback PUT (returns empty)
            urlopen.side_effect = [
                _ctx(_FakeResp(json.dumps({"service_id": "svc-abc"}).encode())),
                _ctx(
                    _FakeResp(
                        json.dumps(
                            {
                                "status": "READY",
                                "hostname": "tsdb-1.cloud.tigerdata.com",
                                "port": 5432,
                                "username": "tsdbadmin",
                                "initial_password": "s3cret",
                                "default_db_name": "tsdb",
                            }
                        ).encode()
                    )
                ),
                _ctx(_FakeResp(b"")),  # CFN callback PUT
            ]

            mod = _load_module()

            # Act
            mod.handler(_make_event(), context=None)

            # Assert: vendor API was called with correct base URL + Basic auth
            create_call = urlopen.call_args_list[0]
            req = create_call.args[0]
            assert (
                req.full_url
                == "https://console.cloud.tigerdata.com/public/api/v1/projects/proj-123/services"
            )
            assert req.headers["Authorization"] == "Basic YWxpY2U6d29uZGVybGFuZA=="

            # Assert: secret landed in LocalStack Secrets Manager
            secret = sm_client.get_secret_value(
                SecretId=f"ems/{DEPLOYMENT_UUID}/persistence/tiger"
            )
            assert (
                secret["SecretString"]
                == "postgres://tsdbadmin:s3cret@tsdb-1.cloud.tigerdata.com:5432/tsdb?sslmode=require"
            )

            # Assert: CFN callback was a PUT with Status=SUCCESS
            cfn_call = urlopen.call_args_list[2]
            cfn_req = cfn_call.args[0]
            assert cfn_req.method == "PUT"
            cfn_body = json.loads(cfn_req.data)
            assert cfn_body["Status"] == "SUCCESS"
            assert cfn_body["PhysicalResourceId"] == "svc-abc"


def test_create_failure_sends_failed_callback_to_cfn() -> None:
    """If the vendor API errors, Lambda must FAIL the custom resource cleanly."""
    # Arrange
    with (
        start_localstack(services=("secretsmanager",)) as ls,
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
        # Vendor create returns an HTTPError → Lambda FAILED + CFN callback
        urlopen.side_effect = [
            Exception("vendor API returned 401"),
            _ctx(_FakeResp(b"")),  # CFN callback
        ]

        mod = _load_module()

        # Act — should not raise; Lambda always responds to CFN
        mod.handler(_make_event(), context=None)

        # Assert: CFN callback indicates FAILED
        cfn_call = urlopen.call_args_list[1]
        cfn_body = json.loads(cfn_call.args[0].data)
        assert cfn_body["Status"] == "FAILED"
        assert "401" in cfn_body["Reason"]


def _ctx(resp: _FakeResp) -> MagicMock:
    """Wrap a fake response in a context-manager mock (urlopen returns one)."""
    m = MagicMock()
    m.__enter__ = lambda self: resp
    m.__exit__ = lambda *a: None
    return m
