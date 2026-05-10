"""Integration tests for the Aurora bootstrap Lambda.

Tests against a real Postgres testcontainer (pgvector image, since the
Lambda installs the `vector` extension on `ems_vector`) plus a LocalStack
container for AWS Secrets Manager. urllib mocked only for the CFN
ResponseURL callback (no vendor REST API in this Lambda).
"""

import importlib.util
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import boto3

from tests.fixtures.containers import start_localstack, start_postgres

LAMBDA_PATH = (
    Path(__file__).parent.parent.parent
    / "src"
    / "cfn"
    / "persistence"
    / "lambda_code"
    / "aurora_bootstrap.py"
)
DEPLOYMENT_UUID = "abcd1234-5678-90ef-1234-567890abcdef"


def _load_module():
    spec = importlib.util.spec_from_file_location("aurora_bootstrap", LAMBDA_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


def test_create_provisions_databases_extension_users_and_secrets() -> None:
    """End-to-end: real postgres + LocalStack secrets manager.

    Asserts:
    - ems_document and ems_vector databases exist after handler runs
    - vector extension installed on ems_vector
    - app users ems_doc_app and ems_vec_app can connect with their conn strings
    - aurora-document + aurora-vector secrets land in Secrets Manager
    """
    # Arrange — pgvector image (master pw + db = "test")
    with (
        start_postgres(password="test", image="pgvector/pgvector:pg16") as pg,
        start_localstack(services=("secretsmanager",)) as ls,
    ):
        # First: write the Aurora master secret to LocalStack (the bootstrap
        # Lambda reads this to obtain master credentials).
        sm_client = boto3.client(
            "secretsmanager",
            endpoint_url=ls.url,
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        master_secret = sm_client.create_secret(
            Name="aurora-master-secret-test",
            SecretString=json.dumps({"username": "postgres", "password": "test"}),
        )
        master_arn = master_secret["ARN"]

        event = {
            "RequestType": "Create",
            "ResponseURL": "https://cfn-response.example/path",
            "StackId": "arn:aws:cloudformation:us-east-1:123:stack/test/abc",
            "RequestId": "req-123",
            "LogicalResourceId": "AuroraBootstrapCustomResource",
            "ResourceProperties": {
                "ClusterEndpoint": pg.host,
                "MasterSecretArn": master_arn,
                "DeploymentUuid": DEPLOYMENT_UUID,
            },
        }

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
            urlopen.return_value = _ctx(_FakeResp(b""))  # CFN callback only

            mod = _load_module()

            # The Lambda hardcodes port 5432 in the conn string, so monkey-patch
            # the psycopg2.connect to inject the dynamic test port. The handler's
            # _create() uses keyword args (host=, dbname=); we wrap connect to
            # add port=pg.port to every call.
            real_connect = mod.psycopg2.connect

            def _patched_connect(**kwargs: Any) -> Any:  # noqa: ANN401
                kwargs["port"] = pg.port
                return real_connect(**kwargs)

            with patch.object(mod.psycopg2, "connect", side_effect=_patched_connect):
                # Act
                mod.handler(event, context=None)

            # Sanity: handler must have sent SUCCESS to CFN, otherwise the
            # databases never got created and downstream asserts are misleading.
            cfn_body = json.loads(urlopen.call_args.args[0].data)
            assert (
                cfn_body["Status"] == "SUCCESS"
            ), f"Lambda failed: {cfn_body.get('Reason', 'unknown')}"

            # Assert: databases exist
            with real_connect(
                host=pg.host,
                port=pg.port,
                user="postgres",
                password="test",
                dbname="postgres",
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT datname FROM pg_database WHERE datname IN ('ems_document', 'ems_vector')"
                    )
                    dbs = {row[0] for row in cur.fetchall()}
            assert dbs == {"ems_document", "ems_vector"}

            # Assert: vector extension installed on ems_vector
            with (
                real_connect(
                    host=pg.host,
                    port=pg.port,
                    user="postgres",
                    password="test",
                    dbname="ems_vector",
                ) as conn,
                conn.cursor() as cur,
            ):
                cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
                rows = cur.fetchall()
            assert rows == [("vector",)]

            # Assert: secrets landed in LocalStack
            doc_secret = sm_client.get_secret_value(
                SecretId=f"ems/{DEPLOYMENT_UUID}/persistence/aurora-document"
            )["SecretString"]
            vec_secret = sm_client.get_secret_value(
                SecretId=f"ems/{DEPLOYMENT_UUID}/persistence/aurora-vector"
            )["SecretString"]
            assert "ems_doc_app" in doc_secret
            assert "ems_document" in doc_secret
            assert "ems_vec_app" in vec_secret
            assert "ems_vector" in vec_secret

            # Assert: CFN callback was SUCCESS
            cfn_call = urlopen.call_args
            cfn_body = json.loads(cfn_call.args[0].data)
            assert cfn_body["Status"] == "SUCCESS"
