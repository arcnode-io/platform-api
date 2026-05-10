# Cloud Persistence Provisioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three operator-pasted persistence connection-string parameters in the per-order CFN template with native Aurora serverless provisioning + inline-Lambda CFN custom resources that provision Tiger Cloud and Neo4j Aura via vendor REST APIs.

**Architecture:** NestJS-style sub-module under `src/cfn/persistence/`. `PersistenceService` composes pure-data CFN dicts produced by `aurora_resources.py`, `tiger_resources.py`, `aura_resources.py`. Three inline Python Lambdas live as `lambda_code/*.py` files, loaded as strings by the resource builders and embedded in CFN via `Code.ZipFile`. UserData rewritten to fetch four secrets from Secrets Manager via the AWS CLI (already in AL2023 AMI) and write to `/opt/arcnode/<name>.url` for docker-compose `env_file:` consumption.

**Tech Stack:** Python 3.13, FastAPI (existing), `pyyaml`, `cfn-lint` (test-only), AWS CFN intrinsics (`Fn::Sub`, `Fn::GetAtt`, `Ref`), Aurora serverless PG 16+, Tiger Cloud REST API, Neo4j Aura REST API.

**Spec source:** `../../../ems/docs/superpowers/specs/2026-05-10-cloud-persistence-provisioning-design.md`

---

## File Structure

**Create:**

- `src/cfn/persistence/__init__.py` — empty package marker
- `src/cfn/persistence/persistence_module.py` — DI assembly for `PersistenceService`
- `src/cfn/persistence/persistence_service.py` — composes Aurora + Tiger + Aura resource dicts into one
- `src/cfn/persistence/aurora_resources.py` — Aurora cluster + instance + master secret + bootstrap Lambda CFN
- `src/cfn/persistence/tiger_resources.py` — Tiger Cloud Lambda + custom resource CFN
- `src/cfn/persistence/aura_resources.py` — Neo4j Aura Lambda + custom resource CFN
- `src/cfn/persistence/lambda_code/__init__.py` — empty package marker
- `src/cfn/persistence/lambda_code/aurora_bootstrap.py` — runs inside Lambda; creates DBs + extension + app users
- `src/cfn/persistence/lambda_code/tiger_provisioner.py` — runs inside Lambda; calls Tiger REST API
- `src/cfn/persistence/lambda_code/aura_provisioner.py` — runs inside Lambda; calls Aura REST API
- `src/cfn/persistence/aurora_resources_test.py` — unit tests for Aurora CFN block
- `src/cfn/persistence/tiger_resources_test.py` — unit tests for Tiger CFN block
- `src/cfn/persistence/aura_resources_test.py` — unit tests for Aura CFN block
- `src/cfn/persistence/persistence_service_test.py` — composition tests + cfn-lint over the joined dict

**Modify:**

- `src/cfn/cfn_resources.py` — drop `PERSISTENCE_PARAMETERS` (the three conn-string params); add four vendor-token params; extend `iam_resources()` to grant `secretsmanager:GetSecretValue`; rewrite `build_userdata()` to fetch from Secrets Manager
- `src/cfn/cfn_resources_test.py` — adjust assertions (file may need to be split off `cfn_service_test.py` if no separate test file exists today; check first)
- `src/cfn/cfn_service.py` — inject `PersistenceService`, merge its resources into the template `Resources` block, add new parameters to template `Parameters`
- `src/cfn/cfn_service_test.py` — replace conn-string-param assertions with vendor-token + Aurora + custom-resource assertions
- `src/cfn/cfn_module.py` — instantiate `PersistenceService` and pass to `CfnService`
- `tests/fixtures/` — add Tiger + Aura API response fixtures if used in any integration tests

**Cross-repo edits (ems repo, separate commit cycle):**

- `/home/resister/arcnode/ems/cloud_persistence_provisioning_adr.md` — new ADR-004 derived from spec
- `/home/resister/arcnode/ems/system_adr.md` — small banner pointing to ADR-004 above the "Managed Postgres Service" rejection note
- `/home/resister/arcnode/ems/readme.md` — Cloud Deployment (AWS) PlantUML diagram: replace `cloud neon_vector` + `cloud neon_document` with `database aurora_serverless`

---

## Task 0: Research vendor REST APIs

**Goal:** Capture the exact request/response shapes for Tiger Cloud's
"create service" and Neo4j Aura's "create instance" endpoints so the
later Lambda-code tasks have concrete contracts to implement against.

**Files:**
- Read-only research; outputs are inline notes used by Tasks 7–10

- [ ] **Step 1: Tiger Cloud API research**

Use the `WebSearch` tool with these queries:
- `Tiger Cloud REST API create service endpoint 2026 authentication`
- `tigerdata.com developer API key project-id provision service`
- `Tiger Cloud OpenAPI specification timescaledb`

Capture into a scratch note (delete after Task 10):
- Auth header format (`Authorization: Bearer ...` vs custom header)
- POST endpoint path for service creation
- Required request body fields (project_id, region, service_type, name)
- Response shape (service_id, status, host, port, username, password, database)
- Polling endpoint + "ready" status value
- DELETE endpoint path

- [ ] **Step 2: Neo4j Aura API research**

Use the `WebSearch` tool with these queries:
- `Neo4j Aura API create instance OAuth client credentials 2026`
- `neo4j.com developer Aura instances POST endpoint`
- `Aura OpenAPI specification`

Capture into the same scratch note:
- OAuth2 token endpoint (client_credentials grant) and exact body
- POST endpoint path for instance creation
- Required body fields (name, version, region, memory, type, tenant_id)
- Response shape (id, status, connection_url, username, password)
- Polling endpoint + "running" status value
- DELETE endpoint path

- [ ] **Step 3: Confirm CFN custom-resource Lambda response contract**

Use the `WebSearch` tool: `AWS CloudFormation custom resource response signed URL S3 PhysicalResourceId 2026`. Confirm:
- Response is a PUT to `event['ResponseURL']` (presigned S3 URL)
- Required fields: `Status`, `Reason`, `PhysicalResourceId`, `StackId`, `RequestId`, `LogicalResourceId`, optional `Data`
- The Python `urllib.request.Request` PUT pattern (`method='PUT'`, `data=json.dumps(...).encode()`)

- [ ] **Step 4: No commit — research only**

Move on to Task 1 carrying these notes inline.

---

## Task 1: Drop the three obsolete connection-string parameters

**Files:**
- Modify: `src/cfn/cfn_resources.py:24-51`
- Modify: `src/cfn/cfn_service_test.py` (assertions referencing the three params)

- [ ] **Step 1: Identify failing tests after the planned change**

Read `src/cfn/cfn_service_test.py` and find every `assert` that references `NeonConnectionString`, `AuraConnectionString`, or `TimeseriesConnectionString`. There are at least two (the params test + a UserData substitution test). Note the test names.

- [ ] **Step 2: Write a failing test for the new param shape**

Edit `src/cfn/cfn_service_test.py`. Add this new test to assert the new parameters are present:

```python
def test_render_template_declares_vendor_token_parameters() -> None:
    """Four no-default NoEcho parameters: Tiger key+project, Aura client id+secret."""
    rendered = _render()

    assert "TigerCloudApiKey" in rendered
    assert "TigerCloudProjectId" in rendered
    assert "Neo4jAuraClientId" in rendered
    assert "Neo4jAuraClientSecret" in rendered
    assert "NoEcho: true" in rendered
```

- [ ] **Step 3: Run the new test — verify it fails**

```bash
cd /home/resister/arcnode/platform-api
uv run pytest -vv src/cfn/cfn_service_test.py::test_render_template_declares_vendor_token_parameters
```

Expected: FAIL — `TigerCloudApiKey not in rendered`.

- [ ] **Step 4: Replace `PERSISTENCE_PARAMETERS` in `cfn_resources.py`**

Edit `src/cfn/cfn_resources.py`. Replace the existing `PERSISTENCE_PARAMETERS` constant + `persistence_parameters()` function with:

```python
# Four vendor-token parameters the operator pastes at create-stack time.
# The Lambda custom resources in the persistence sub-module use these tokens
# to call vendor REST APIs and provision instances. Operators no longer paste
# raw connection strings — those are generated by the Lambdas and stored in
# Secrets Manager. NoEcho keeps tokens out of the Console UI.
VENDOR_TOKEN_PARAMETERS: Final[tuple[tuple[str, str], ...]] = (
    (
        "TigerCloudApiKey",
        "Tiger Cloud API key (generated in Tiger Cloud console > API Keys).",
    ),
    (
        "TigerCloudProjectId",
        "Tiger Cloud project id (shown next to the API key).",
    ),
    (
        "Neo4jAuraClientId",
        "Neo4j Aura OAuth2 client id (org-level API key).",
    ),
    (
        "Neo4jAuraClientSecret",
        "Neo4j Aura OAuth2 client secret (paired with client id).",
    ),
)


def vendor_token_parameters() -> dict[str, object]:
    """Four required no-default NoEcho String parameters for vendor REST API auth."""
    return {
        name: {
            "Type": "String",
            "NoEcho": True,
            "MinLength": 1,
            "Description": description,
        }
        for name, description in VENDOR_TOKEN_PARAMETERS
    }
```

- [ ] **Step 5: Update the import + call site in `cfn_service.py`**

Edit `src/cfn/cfn_service.py`. Change the import:

```python
from src.cfn.cfn_resources import (
    AMI_SSM_PARAMETER,
    build_userdata,
    iam_resources,
    network_resources,
    vendor_token_parameters,
)
```

Change the `Parameters` line in `render_template`:

```python
"Parameters": vendor_token_parameters(),
```

- [ ] **Step 6: Delete tests that reference the removed parameters**

Remove any test in `src/cfn/cfn_service_test.py` that asserts on `NeonConnectionString`, `AuraConnectionString`, or `TimeseriesConnectionString`. The replacement test from Step 2 covers the new shape.

- [ ] **Step 7: Update `build_userdata()` to drop the three Fn::Sub conn-string lines**

Edit `src/cfn/cfn_resources.py`. In `build_userdata()`, remove these three lines:

```python
'echo "${NeonConnectionString}" > /opt/arcnode/neon.url\n'
'echo "${AuraConnectionString}" > /opt/arcnode/aura.url\n'
'echo "${TimeseriesConnectionString}" > /opt/arcnode/timeseries.url\n'
```

(The new UserData fetches from Secrets Manager — added in Task 14.)

- [ ] **Step 8: Run all CFN tests — verify pass**

```bash
uv run pytest -vv src/cfn/
```

Expected: all pass, including the new `test_render_template_declares_vendor_token_parameters`.

- [ ] **Step 9: Commit**

```bash
cd /home/resister/arcnode/platform-api
git add src/cfn/cfn_resources.py src/cfn/cfn_service.py src/cfn/cfn_service_test.py
git commit -m "$(cat <<'EOF'
refactor(cfn): replace 3 conn-string params with 4 vendor-token params

Drops NeonConnectionString, AuraConnectionString, TimeseriesConnectionString.
Adds TigerCloudApiKey, TigerCloudProjectId, Neo4jAuraClientId,
Neo4jAuraClientSecret. Persistence sub-module to follow.
EOF
)"
```

---

## Task 2: Persistence sub-package skeleton

**Files:**
- Create: `src/cfn/persistence/__init__.py`
- Create: `src/cfn/persistence/lambda_code/__init__.py`
- Create: `src/cfn/persistence/persistence_service.py` (stub)
- Create: `src/cfn/persistence/persistence_module.py` (stub)
- Create: `src/cfn/persistence/persistence_service_test.py` (one trivial test)

- [ ] **Step 1: Write the failing test**

Create `src/cfn/persistence/persistence_service_test.py`:

```python
"""Composition tests for `PersistenceService.build_resources()`.

Asserts that Aurora + Tiger + Aura resource blocks are merged into one dict
and that the joined dict, when embedded in a minimal CFN skeleton, passes
cfn-lint.
"""

from src.cfn.persistence.persistence_service import PersistenceService


def test_build_resources_returns_dict() -> None:
    """Smoke test — composition entry point returns a dict (placeholder)."""
    # Arrange
    service = PersistenceService()

    # Act
    resources = service.build_resources()

    # Assert
    assert isinstance(resources, dict)
```

- [ ] **Step 2: Run — verify ImportError**

```bash
uv run pytest -vv src/cfn/persistence/persistence_service_test.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.cfn.persistence'`.

- [ ] **Step 3: Create empty package markers**

```bash
mkdir -p /home/resister/arcnode/platform-api/src/cfn/persistence/lambda_code
touch /home/resister/arcnode/platform-api/src/cfn/persistence/__init__.py
touch /home/resister/arcnode/platform-api/src/cfn/persistence/lambda_code/__init__.py
```

- [ ] **Step 4: Create the stub `persistence_service.py`**

Create `src/cfn/persistence/persistence_service.py`:

```python
"""PersistenceService — composes Aurora + Tiger + Aura CFN resource blocks."""


class PersistenceService:
    """Single entry point for building the persistence section of the CFN template."""

    def build_resources(self) -> dict[str, object]:
        """Return the merged Aurora + Tiger + Aura resource dict (CFN `Resources:`)."""
        return {}
```

- [ ] **Step 5: Create the stub `persistence_module.py`**

Create `src/cfn/persistence/persistence_module.py`:

```python
"""Persistence module — DI assembly for `PersistenceService`."""

from src.cfn.persistence.persistence_service import PersistenceService


class PersistenceModule:
    """Single point of DI for persistence resource composition."""

    def __init__(self) -> None:
        self.service = PersistenceService()
```

- [ ] **Step 6: Run — verify pass**

```bash
uv run pytest -vv src/cfn/persistence/persistence_service_test.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/cfn/persistence/
git commit -m "feat(cfn): add persistence sub-package skeleton (stub PersistenceService)"
```

---

## Task 3: Aurora cluster + instance + master secret

**Files:**
- Create: `src/cfn/persistence/aurora_resources.py`
- Create: `src/cfn/persistence/aurora_resources_test.py`

- [ ] **Step 1: Write the failing test**

Create `src/cfn/persistence/aurora_resources_test.py`:

```python
"""Unit tests for `aurora_resources.aurora_cluster_resources`.

Asserts presence of the three CFN resources Aurora needs (cluster, instance,
master secret) and the scale-to-0 + serverless-v2-config invariants.
"""

from src.cfn.persistence.aurora_resources import aurora_cluster_resources


def test_returns_cluster_instance_and_master_secret() -> None:
    """Three logical IDs: AuroraCluster, AuroraInstance, AuroraMasterSecret."""
    # Arrange + Act
    resources = aurora_cluster_resources()

    # Assert
    assert "AuroraCluster" in resources
    assert "AuroraInstance" in resources
    assert "AuroraMasterSecret" in resources


def test_cluster_uses_serverless_with_scale_to_zero() -> None:
    """ServerlessV2ScalingConfiguration with MinCapacity=0 + auto-pause."""
    # Arrange + Act
    cluster = aurora_cluster_resources()["AuroraCluster"]

    # Assert
    assert cluster["Type"] == "AWS::RDS::DBCluster"
    props = cluster["Properties"]
    assert props["Engine"] == "aurora-postgresql"
    assert props["EngineMode"] == "provisioned"
    scaling = props["ServerlessV2ScalingConfiguration"]
    assert scaling["MinCapacity"] == 0
    assert scaling["SecondsUntilAutoPause"] == 300


def test_instance_uses_db_serverless_class() -> None:
    """Instance class is db.serverless (the serverless-v2 class name)."""
    # Arrange + Act
    instance = aurora_cluster_resources()["AuroraInstance"]

    # Assert
    assert instance["Type"] == "AWS::RDS::DBInstance"
    assert instance["Properties"]["DBInstanceClass"] == "db.serverless"


def test_master_secret_is_aws_secretsmanager_secret() -> None:
    """Master credentials live in Secrets Manager, referenced from the cluster."""
    # Arrange + Act
    secret = aurora_cluster_resources()["AuroraMasterSecret"]

    # Assert
    assert secret["Type"] == "AWS::SecretsManager::Secret"
    gen = secret["Properties"]["GenerateSecretString"]
    assert gen["SecretStringTemplate"] == '{"username": "ems_master"}'
    assert gen["GenerateStringKey"] == "password"
```

- [ ] **Step 2: Run — verify ImportError**

```bash
uv run pytest -vv src/cfn/persistence/aurora_resources_test.py
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `aurora_resources.py`**

Create `src/cfn/persistence/aurora_resources.py`:

```python
"""Aurora serverless PG CFN resources — cluster, instance, master secret.

Engine version 16.3+ is required for scale-to-0 (per ADR-004 source spec).
The cluster sits in the existing public subnet for MVP; locking it into
private subnets is a future hardening step.
"""

from typing import Final

ENGINE_VERSION: Final[str] = "16.4"
SECONDS_UNTIL_AUTO_PAUSE: Final[int] = 300  # 5 min idle → auto-pause
MASTER_USERNAME: Final[str] = "ems_master"


def aurora_cluster_resources() -> dict[str, object]:
    """CFN resources for a scale-to-0 Aurora serverless PG cluster."""
    return {
        "AuroraMasterSecret": {
            "Type": "AWS::SecretsManager::Secret",
            "Properties": {
                "Description": "Aurora master credentials (managed rotation)",
                "GenerateSecretString": {
                    "SecretStringTemplate": f'{{"username": "{MASTER_USERNAME}"}}',
                    "GenerateStringKey": "password",
                    "PasswordLength": 32,
                    "ExcludeCharacters": '"@/\\',
                },
            },
        },
        "AuroraCluster": {
            "Type": "AWS::RDS::DBCluster",
            "Properties": {
                "Engine": "aurora-postgresql",
                "EngineMode": "provisioned",
                "EngineVersion": ENGINE_VERSION,
                "MasterUsername": MASTER_USERNAME,
                "MasterUserPassword": {
                    "Fn::Sub": "{{resolve:secretsmanager:${AuroraMasterSecret}::password}}"
                },
                "DBSubnetGroupName": {"Ref": "AuroraSubnetGroup"},
                "VpcSecurityGroupIds": [{"Ref": "AuroraSecurityGroup"}],
                "ServerlessV2ScalingConfiguration": {
                    "MinCapacity": 0,
                    "MaxCapacity": 4,
                    "SecondsUntilAutoPause": SECONDS_UNTIL_AUTO_PAUSE,
                },
            },
        },
        "AuroraInstance": {
            "Type": "AWS::RDS::DBInstance",
            "Properties": {
                "DBClusterIdentifier": {"Ref": "AuroraCluster"},
                "DBInstanceClass": "db.serverless",
                "Engine": "aurora-postgresql",
                "EngineVersion": ENGINE_VERSION,
            },
        },
    }
```

- [ ] **Step 4: Run — verify the four tests pass**

```bash
uv run pytest -vv src/cfn/persistence/aurora_resources_test.py
```

Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cfn/persistence/aurora_resources.py src/cfn/persistence/aurora_resources_test.py
git commit -m "feat(cfn/persistence): Aurora serverless cluster + instance + master secret"
```

---

## Task 4: Aurora subnet group + security group

The cluster references `AuroraSubnetGroup` and `AuroraSecurityGroup`; add them.

**Files:**
- Modify: `src/cfn/persistence/aurora_resources.py`
- Modify: `src/cfn/persistence/aurora_resources_test.py`

- [ ] **Step 1: Add the failing test**

Append to `src/cfn/persistence/aurora_resources_test.py`:

```python
def test_returns_subnet_group_and_security_group() -> None:
    """Aurora needs a subnet group + SG; both reference the existing VPC."""
    # Arrange + Act
    resources = aurora_cluster_resources()

    # Assert
    assert "AuroraSubnetGroup" in resources
    assert "AuroraSecurityGroup" in resources
    assert resources["AuroraSubnetGroup"]["Type"] == "AWS::RDS::DBSubnetGroup"
    assert resources["AuroraSecurityGroup"]["Type"] == "AWS::EC2::SecurityGroup"
```

- [ ] **Step 2: Run — verify fail**

```bash
uv run pytest -vv src/cfn/persistence/aurora_resources_test.py::test_returns_subnet_group_and_security_group
```

Expected: FAIL.

- [ ] **Step 3: Add subnet group + SG to `aurora_resources.py`**

Edit `aurora_cluster_resources()` to include two new entries (above `AuroraCluster`):

```python
"AuroraSubnetGroup": {
    "Type": "AWS::RDS::DBSubnetGroup",
    "Properties": {
        "DBSubnetGroupDescription": "Aurora serverless subnet group",
        # MVP: reuse the existing public subnet from network_resources().
        # A second subnet (different AZ) is required for cluster creation;
        # add an EmsSubnetB to network_resources() in a follow-up if RDS
        # rejects single-subnet groups in the target region.
        "SubnetIds": [{"Ref": "EmsSubnet"}, {"Ref": "EmsSubnet"}],
    },
},
"AuroraSecurityGroup": {
    "Type": "AWS::EC2::SecurityGroup",
    "Properties": {
        "GroupDescription": "Aurora serverless ingress (Postgres)",
        "VpcId": {"Ref": "EmsVpc"},
        "SecurityGroupIngress": [
            {
                "IpProtocol": "tcp",
                "FromPort": 5432,
                "ToPort": 5432,
                "SourceSecurityGroupId": {"Ref": "EmsSecurityGroup"},
            }
        ],
    },
},
```

- [ ] **Step 4: Run all Aurora tests — verify pass**

```bash
uv run pytest -vv src/cfn/persistence/aurora_resources_test.py
```

Expected: all 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cfn/persistence/aurora_resources.py src/cfn/persistence/aurora_resources_test.py
git commit -m "feat(cfn/persistence): Aurora subnet group + security group"
```

---

## Task 5: Aurora bootstrap Lambda code

**Files:**
- Create: `src/cfn/persistence/lambda_code/aurora_bootstrap.py`
- Create: `src/cfn/persistence/lambda_code/aurora_bootstrap_test.py`

This file's source becomes the `Code.ZipFile` string for the bootstrap Lambda. Keep it self-contained — only `boto3`, `psycopg2`, `urllib.request` (psycopg2 must be in a Lambda Layer; CFN handles this — see Task 6).

- [ ] **Step 1: Write the failing test**

Create `src/cfn/persistence/lambda_code/aurora_bootstrap_test.py`:

```python
"""Smoke tests for the Aurora bootstrap Lambda source.

The function runs in Lambda; we test what we can statically — that the
module parses, that `handler` is callable, and that the SQL statements
match the expected database + extension shape.
"""

import importlib.util
from pathlib import Path

MODULE_PATH = (
    Path(__file__).parent / "aurora_bootstrap.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("aurora_bootstrap", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_module_loads_and_exposes_handler() -> None:
    """Lambda entry point must be `handler(event, context)`."""
    # Arrange + Act
    mod = _load_module()

    # Assert
    assert callable(mod.handler)


def test_creates_document_and_vector_databases() -> None:
    """SQL must CREATE DATABASE for both ems_document and ems_vector."""
    # Arrange + Act
    source = MODULE_PATH.read_text()

    # Assert
    assert "CREATE DATABASE ems_document" in source
    assert "CREATE DATABASE ems_vector" in source


def test_installs_vector_extension_on_vector_db() -> None:
    """pgvector goes on ems_vector only, not ems_document."""
    # Arrange + Act
    source = MODULE_PATH.read_text()

    # Assert
    assert "CREATE EXTENSION IF NOT EXISTS vector" in source
```

- [ ] **Step 2: Run — verify fail**

```bash
uv run pytest -vv src/cfn/persistence/lambda_code/aurora_bootstrap_test.py
```

Expected: FAIL — file doesn't exist yet.

- [ ] **Step 3: Implement `aurora_bootstrap.py`**

Create `src/cfn/persistence/lambda_code/aurora_bootstrap.py`:

```python
"""Aurora bootstrap Lambda — runs once at stack-create.

Creates the ems_document + ems_vector databases, installs the vector
extension on ems_vector, creates least-privilege app users for each
database, and writes their conn strings to Secrets Manager. Not
imported by application code — the source is read as text by
aurora_resources.py and embedded in CFN as Code.ZipFile.

Lambda runtime: python3.13. Dependencies: psycopg2 via Lambda Layer
(arn:aws:lambda:<region>:898466741470:layer:psycopg2-py313:1 or equivalent
public layer; configured in aurora_resources.py). boto3 + urllib.request
are built into the runtime.
"""

import json
import os
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

    with psycopg2.connect(
        host=cluster_endpoint,
        user=master["username"],
        password=master["password"],
        dbname="postgres",
    ) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("CREATE DATABASE ems_document")
            cur.execute("CREATE DATABASE ems_vector")
            cur.execute(f"CREATE USER ems_doc_app WITH PASSWORD '{doc_pw}'")
            cur.execute(f"CREATE USER ems_vec_app WITH PASSWORD '{vec_pw}'")
            cur.execute("GRANT ALL PRIVILEGES ON DATABASE ems_document TO ems_doc_app")
            cur.execute("GRANT ALL PRIVILEGES ON DATABASE ems_vector TO ems_vec_app")

    with psycopg2.connect(
        host=cluster_endpoint,
        user=master["username"],
        password=master["password"],
        dbname="ems_vector",
    ) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

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
        event["ResponseURL"], data=body, method="PUT",
        headers={"content-type": "", "content-length": str(len(body))},
    )
    urllib.request.urlopen(req)  # noqa: S310 — CFN-signed presigned URL
```

- [ ] **Step 4: Run all bootstrap tests — verify pass**

```bash
uv run pytest -vv src/cfn/persistence/lambda_code/aurora_bootstrap_test.py
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cfn/persistence/lambda_code/aurora_bootstrap.py src/cfn/persistence/lambda_code/aurora_bootstrap_test.py
git commit -m "feat(cfn/persistence): Aurora bootstrap Lambda source"
```

---

## Task 6: Aurora bootstrap Lambda CFN resource + custom resource

**Files:**
- Modify: `src/cfn/persistence/aurora_resources.py`
- Modify: `src/cfn/persistence/aurora_resources_test.py`

- [ ] **Step 1: Add a builder function for the bootstrap Lambda**

Append to `src/cfn/persistence/aurora_resources_test.py`:

```python
def test_returns_bootstrap_lambda_and_custom_resource() -> None:
    """Bootstrap Lambda + IAM role + custom resource trigger."""
    # Arrange + Act
    resources = aurora_cluster_resources()

    # Assert
    assert "AuroraBootstrapLambdaRole" in resources
    assert "AuroraBootstrapLambda" in resources
    assert "AuroraBootstrapCustomResource" in resources

    lambda_res = resources["AuroraBootstrapLambda"]
    assert lambda_res["Type"] == "AWS::Lambda::Function"
    assert lambda_res["Properties"]["Runtime"] == "python3.13"
    assert lambda_res["Properties"]["Handler"] == "index.handler"
    # The Lambda runs inside the VPC because it speaks Postgres to private RDS
    assert "VpcConfig" in lambda_res["Properties"]


def test_bootstrap_custom_resource_passes_required_properties() -> None:
    """ClusterEndpoint, MasterSecretArn, DeploymentUuid flow into the Lambda."""
    # Arrange + Act
    cr = aurora_cluster_resources()["AuroraBootstrapCustomResource"]

    # Assert
    assert cr["Type"] == "Custom::AuroraBootstrap"
    props = cr["Properties"]
    assert "ClusterEndpoint" in props
    assert "MasterSecretArn" in props
    assert "DeploymentUuid" in props
```

- [ ] **Step 2: Run — verify fail**

```bash
uv run pytest -vv src/cfn/persistence/aurora_resources_test.py
```

Expected: 2 new tests FAIL.

- [ ] **Step 3: Add the bootstrap-Lambda block to `aurora_resources.py`**

Edit `src/cfn/persistence/aurora_resources.py`. At the top of the file, add a helper to load the Lambda source as a string:

```python
from pathlib import Path

LAMBDA_CODE_DIR: Final[Path] = Path(__file__).parent / "lambda_code"


def _load_lambda_source(filename: str) -> str:
    """Read a Lambda source file as a string for embedding in CFN ZipFile."""
    return (LAMBDA_CODE_DIR / filename).read_text()
```

Modify `aurora_cluster_resources()` to also return:

```python
"AuroraBootstrapLambdaRole": {
    "Type": "AWS::IAM::Role",
    "Properties": {
        "AssumeRolePolicyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "lambda.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        },
        "ManagedPolicyArns": [
            "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole",
        ],
        "Policies": [
            {
                "PolicyName": "aurora-bootstrap-secrets",
                "PolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": [
                                "secretsmanager:GetSecretValue",
                                "secretsmanager:CreateSecret",
                                "secretsmanager:PutSecretValue",
                            ],
                            "Resource": "*",
                        }
                    ],
                },
            }
        ],
    },
},
"AuroraBootstrapLambda": {
    "Type": "AWS::Lambda::Function",
    "Properties": {
        "Runtime": "python3.13",
        "Handler": "index.handler",
        "Role": {"Fn::GetAtt": ["AuroraBootstrapLambdaRole", "Arn"]},
        "Timeout": 300,
        "Code": {"ZipFile": _load_lambda_source("aurora_bootstrap.py")},
        "VpcConfig": {
            "SubnetIds": [{"Ref": "EmsSubnet"}],
            "SecurityGroupIds": [{"Ref": "EmsSecurityGroup"}],
        },
        # psycopg2 is not in the python3.13 runtime; reference a public layer.
        # The arn below is a placeholder — replace with the operator-region's
        # AWS-Distro-for-Python-Postgres layer or a self-published layer arn.
        # See https://github.com/jkehler/awslambda-psycopg2 for region arns.
        "Layers": [
            {"Fn::Sub": "arn:aws:lambda:${AWS::Region}:898466741470:layer:psycopg2-py313:1"},
        ],
    },
},
"AuroraBootstrapCustomResource": {
    "Type": "Custom::AuroraBootstrap",
    "DependsOn": "AuroraInstance",
    "Properties": {
        "ServiceToken": {"Fn::GetAtt": ["AuroraBootstrapLambda", "Arn"]},
        "ClusterEndpoint": {"Fn::GetAtt": ["AuroraCluster", "Endpoint.Address"]},
        "MasterSecretArn": {"Ref": "AuroraMasterSecret"},
        "DeploymentUuid": {"Ref": "AWS::StackName"},
    },
},
```

- [ ] **Step 4: Run all Aurora tests — verify pass**

```bash
uv run pytest -vv src/cfn/persistence/aurora_resources_test.py
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cfn/persistence/aurora_resources.py src/cfn/persistence/aurora_resources_test.py
git commit -m "feat(cfn/persistence): Aurora bootstrap Lambda + custom resource"
```

---

## Task 7: Tiger Cloud provisioning Lambda code

**Files:**
- Create: `src/cfn/persistence/lambda_code/tiger_provisioner.py`
- Create: `src/cfn/persistence/lambda_code/tiger_provisioner_test.py`

Use the API contract captured in Task 0 to fill in the actual endpoint paths + body shape.

- [ ] **Step 1: Write the failing test**

Create `src/cfn/persistence/lambda_code/tiger_provisioner_test.py`:

```python
"""Smoke tests for the Tiger Cloud provisioning Lambda source."""

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parent / "tiger_provisioner.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("tiger_provisioner", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_module_loads_and_exposes_handler() -> None:
    mod = _load_module()
    assert callable(mod.handler)


def test_module_only_uses_stdlib_and_boto3() -> None:
    """No external deps — must run in vanilla python3.13 runtime."""
    source = MODULE_PATH.read_text()
    # No pip-installable third-party imports
    forbidden = ["import requests", "import httpx", "from requests"]
    for needle in forbidden:
        assert needle not in source, f"Tiger Lambda must not import {needle}"


def test_handler_handles_create_update_delete() -> None:
    """Lambda dispatches on event['RequestType']."""
    source = MODULE_PATH.read_text()
    assert "RequestType" in source
    assert "Create" in source
    assert "Delete" in source
```

- [ ] **Step 2: Run — verify fail**

```bash
uv run pytest -vv src/cfn/persistence/lambda_code/tiger_provisioner_test.py
```

Expected: FAIL — file missing.

- [ ] **Step 3: Implement `tiger_provisioner.py`**

Create `src/cfn/persistence/lambda_code/tiger_provisioner.py` using the Tiger API contract from Task 0. Skeleton (fill endpoint URLs + body fields per Task 0 notes):

```python
"""Tiger Cloud provisioning Lambda — CFN custom resource backend.

Calls the Tiger Cloud REST API to create/delete a Tiger service. Polls
the service-status endpoint until ready. Writes the connection string to
Secrets Manager. No third-party deps — uses urllib.request + boto3 only
(both available in python3.13 runtime).

Endpoint base: https://api.tigerdata.com (verify per Task 0 research)
Auth: Authorization: Bearer <api_key>
"""

import json
import time
import urllib.request

import boto3  # type: ignore[import-untyped]

API_BASE = "https://api.tigerdata.com"
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
        else:  # Update — recreate-on-change handled by CFN replacing PhysicalResourceId
            _respond(event, "SUCCESS", physical_id, {})
    except Exception as e:  # noqa: BLE001
        _respond(event, "FAILED", physical_id, {"Reason": str(e)})


def _create(event: dict) -> tuple[str, str]:
    props = event["ResourceProperties"]
    api_key = props["TigerCloudApiKey"]
    project_id = props["TigerCloudProjectId"]

    # POST /v1/projects/<project_id>/services
    # NOTE: verify exact path + body shape per Task 0 research
    body = json.dumps({
        "name": props["DeploymentUuid"],
        "region": props.get("Region", "us-east-1"),
        "service_type": "timescaledb",
    }).encode()
    req = urllib.request.Request(
        f"{API_BASE}/v1/projects/{project_id}/services",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        created = json.loads(resp.read())

    service_id = created["service_id"]
    _wait_ready(api_key, project_id, service_id)
    return service_id, _fetch_conn_url(api_key, project_id, service_id)


def _wait_ready(api_key: str, project_id: str, service_id: str) -> None:
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        req = urllib.request.Request(
            f"{API_BASE}/v1/projects/{project_id}/services/{service_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req) as resp:  # noqa: S310
            status = json.loads(resp.read()).get("status")
        if status == "ready":
            return
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Tiger service {service_id} did not become ready in time")


def _fetch_conn_url(api_key: str, project_id: str, service_id: str) -> str:
    req = urllib.request.Request(
        f"{API_BASE}/v1/projects/{project_id}/services/{service_id}/connection",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        info = json.loads(resp.read())
    return f"postgres://{info['user']}:{info['password']}@{info['host']}:{info['port']}/{info['database']}"


def _delete(event: dict, physical_id: str) -> None:
    if physical_id in ("tiger-pending", ""):
        return  # nothing was ever provisioned
    props = event["ResourceProperties"]
    api_key = props["TigerCloudApiKey"]
    project_id = props["TigerCloudProjectId"]
    req = urllib.request.Request(
        f"{API_BASE}/v1/projects/{project_id}/services/{physical_id}",
        method="DELETE",
        headers={"Authorization": f"Bearer {api_key}"},
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
    body = json.dumps({
        "Status": status,
        "Reason": data.get("Reason", "see CloudWatch logs"),
        "PhysicalResourceId": physical_id,
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "Data": {k: v for k, v in data.items() if k != "Reason"},
    }).encode()
    req = urllib.request.Request(
        event["ResponseURL"], data=body, method="PUT",
        headers={"content-type": "", "content-length": str(len(body))},
    )
    urllib.request.urlopen(req)  # noqa: S310
```

- [ ] **Step 4: Run — verify pass**

```bash
uv run pytest -vv src/cfn/persistence/lambda_code/tiger_provisioner_test.py
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cfn/persistence/lambda_code/tiger_provisioner.py src/cfn/persistence/lambda_code/tiger_provisioner_test.py
git commit -m "feat(cfn/persistence): Tiger Cloud provisioning Lambda source"
```

---

## Task 8: Tiger Cloud CFN resources

**Files:**
- Create: `src/cfn/persistence/tiger_resources.py`
- Create: `src/cfn/persistence/tiger_resources_test.py`

- [ ] **Step 1: Write the failing test**

Create `src/cfn/persistence/tiger_resources_test.py`:

```python
"""Unit tests for `tiger_resources.tiger_provisioning_resources`."""

from src.cfn.persistence.tiger_resources import tiger_provisioning_resources


def test_returns_lambda_role_lambda_and_custom_resource() -> None:
    resources = tiger_provisioning_resources()
    assert "TigerLambdaRole" in resources
    assert "TigerLambda" in resources
    assert "TigerCustomResource" in resources


def test_lambda_uses_python_runtime() -> None:
    lambda_res = tiger_provisioning_resources()["TigerLambda"]
    assert lambda_res["Type"] == "AWS::Lambda::Function"
    assert lambda_res["Properties"]["Runtime"] == "python3.13"


def test_custom_resource_passes_vendor_token_params_through() -> None:
    cr = tiger_provisioning_resources()["TigerCustomResource"]
    assert cr["Type"] == "Custom::TigerCloudInstance"
    props = cr["Properties"]
    assert props["TigerCloudApiKey"] == {"Ref": "TigerCloudApiKey"}
    assert props["TigerCloudProjectId"] == {"Ref": "TigerCloudProjectId"}
    assert "DeploymentUuid" in props
```

- [ ] **Step 2: Run — verify fail**

```bash
uv run pytest -vv src/cfn/persistence/tiger_resources_test.py
```

Expected: FAIL.

- [ ] **Step 3: Implement `tiger_resources.py`**

Create `src/cfn/persistence/tiger_resources.py`:

```python
"""Tiger Cloud CFN resources — Lambda + IAM role + custom resource trigger."""

from pathlib import Path
from typing import Final

LAMBDA_CODE_DIR: Final[Path] = Path(__file__).parent / "lambda_code"


def _load_lambda_source(filename: str) -> str:
    return (LAMBDA_CODE_DIR / filename).read_text()


def tiger_provisioning_resources() -> dict[str, object]:
    """CFN resources that provision a Tiger Cloud service via REST API."""
    return {
        "TigerLambdaRole": {
            "Type": "AWS::IAM::Role",
            "Properties": {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "lambda.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                },
                "ManagedPolicyArns": [
                    "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
                ],
                "Policies": [
                    {
                        "PolicyName": "tiger-secret-write",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": [
                                        "secretsmanager:CreateSecret",
                                        "secretsmanager:DeleteSecret",
                                        "secretsmanager:PutSecretValue",
                                    ],
                                    "Resource": "*",
                                }
                            ],
                        },
                    }
                ],
            },
        },
        "TigerLambda": {
            "Type": "AWS::Lambda::Function",
            "Properties": {
                "Runtime": "python3.13",
                "Handler": "index.handler",
                "Role": {"Fn::GetAtt": ["TigerLambdaRole", "Arn"]},
                "Timeout": 900,
                "Code": {"ZipFile": _load_lambda_source("tiger_provisioner.py")},
            },
        },
        "TigerCustomResource": {
            "Type": "Custom::TigerCloudInstance",
            "Properties": {
                "ServiceToken": {"Fn::GetAtt": ["TigerLambda", "Arn"]},
                "TigerCloudApiKey": {"Ref": "TigerCloudApiKey"},
                "TigerCloudProjectId": {"Ref": "TigerCloudProjectId"},
                "DeploymentUuid": {"Ref": "AWS::StackName"},
            },
        },
    }
```

- [ ] **Step 4: Run — verify pass**

```bash
uv run pytest -vv src/cfn/persistence/tiger_resources_test.py
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cfn/persistence/tiger_resources.py src/cfn/persistence/tiger_resources_test.py
git commit -m "feat(cfn/persistence): Tiger Cloud Lambda + custom resource"
```

---

## Task 9: Neo4j Aura provisioning Lambda code

**Files:**
- Create: `src/cfn/persistence/lambda_code/aura_provisioner.py`
- Create: `src/cfn/persistence/lambda_code/aura_provisioner_test.py`

- [ ] **Step 1: Write the failing test**

Create `src/cfn/persistence/lambda_code/aura_provisioner_test.py`:

```python
"""Smoke tests for the Neo4j Aura provisioning Lambda source."""

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parent / "aura_provisioner.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("aura_provisioner", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_module_loads_and_exposes_handler() -> None:
    mod = _load_module()
    assert callable(mod.handler)


def test_module_only_uses_stdlib_and_boto3() -> None:
    source = MODULE_PATH.read_text()
    forbidden = ["import requests", "import httpx", "from requests"]
    for needle in forbidden:
        assert needle not in source


def test_handler_handles_create_update_delete() -> None:
    source = MODULE_PATH.read_text()
    assert "RequestType" in source
    assert "Create" in source
    assert "Delete" in source


def test_oauth_client_credentials_flow_used() -> None:
    """Aura uses OAuth2 client_credentials grant for token exchange."""
    source = MODULE_PATH.read_text()
    assert "client_credentials" in source
```

- [ ] **Step 2: Run — verify fail**

```bash
uv run pytest -vv src/cfn/persistence/lambda_code/aura_provisioner_test.py
```

Expected: FAIL.

- [ ] **Step 3: Implement `aura_provisioner.py`**

Create `src/cfn/persistence/lambda_code/aura_provisioner.py` per Task 0 API contract:

```python
"""Neo4j Aura provisioning Lambda — CFN custom resource backend.

Exchanges the operator-supplied OAuth client id+secret for a bearer token
via Aura's client_credentials grant, then POSTs to /v1/instances to create
the database. Polls /v1/instances/<id> until status == 'running'. Writes
the bolt URI + credentials to Secrets Manager.

Endpoint base: https://api.neo4j.io (verify per Task 0 research)
"""

import base64
import json
import time
import urllib.parse
import urllib.request
import urllib.error

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
    except Exception as e:  # noqa: BLE001
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
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        return json.loads(resp.read())["access_token"]


def _create(event: dict) -> tuple[str, dict]:
    props = event["ResourceProperties"]
    token = _token(props["Neo4jAuraClientId"], props["Neo4jAuraClientSecret"])

    body = json.dumps({
        "name": props["DeploymentUuid"],
        "version": "5",
        "region": props.get("Region", "us-east-1"),
        "memory": "1GB",
        "type": "free-db",
        "tenant_id": props["TenantId"],
        "cloud_provider": "aws",
    }).encode()
    req = urllib.request.Request(
        f"{API_BASE}/v1/instances",
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        created = json.loads(resp.read())["data"]
    instance_id = created["id"]
    # Aura returns initial credentials in the create response
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
        with urllib.request.urlopen(req) as resp:  # noqa: S310
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
        urllib.request.urlopen(req)  # noqa: S310
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
    body = json.dumps({
        "Status": status,
        "Reason": data.get("Reason", "see CloudWatch logs"),
        "PhysicalResourceId": physical_id,
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "Data": {k: v for k, v in data.items() if k != "Reason"},
    }).encode()
    req = urllib.request.Request(
        event["ResponseURL"], data=body, method="PUT",
        headers={"content-type": "", "content-length": str(len(body))},
    )
    urllib.request.urlopen(req)  # noqa: S310
```

- [ ] **Step 4: Run — verify pass**

```bash
uv run pytest -vv src/cfn/persistence/lambda_code/aura_provisioner_test.py
```

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cfn/persistence/lambda_code/aura_provisioner.py src/cfn/persistence/lambda_code/aura_provisioner_test.py
git commit -m "feat(cfn/persistence): Neo4j Aura provisioning Lambda source"
```

---

## Task 10: Neo4j Aura CFN resources

**Files:**
- Create: `src/cfn/persistence/aura_resources.py`
- Create: `src/cfn/persistence/aura_resources_test.py`

- [ ] **Step 1: Write the failing test**

Create `src/cfn/persistence/aura_resources_test.py`:

```python
"""Unit tests for `aura_resources.aura_provisioning_resources`."""

from src.cfn.persistence.aura_resources import aura_provisioning_resources


def test_returns_lambda_role_lambda_and_custom_resource() -> None:
    resources = aura_provisioning_resources()
    assert "AuraLambdaRole" in resources
    assert "AuraLambda" in resources
    assert "AuraCustomResource" in resources


def test_lambda_uses_python_runtime() -> None:
    lambda_res = aura_provisioning_resources()["AuraLambda"]
    assert lambda_res["Properties"]["Runtime"] == "python3.13"


def test_custom_resource_passes_oauth_creds_through() -> None:
    cr = aura_provisioning_resources()["AuraCustomResource"]
    assert cr["Type"] == "Custom::Neo4jAuraInstance"
    props = cr["Properties"]
    assert props["Neo4jAuraClientId"] == {"Ref": "Neo4jAuraClientId"}
    assert props["Neo4jAuraClientSecret"] == {"Ref": "Neo4jAuraClientSecret"}
```

- [ ] **Step 2: Run — verify fail**

```bash
uv run pytest -vv src/cfn/persistence/aura_resources_test.py
```

Expected: FAIL.

- [ ] **Step 3: Implement `aura_resources.py`**

Create `src/cfn/persistence/aura_resources.py` (mirrors `tiger_resources.py` shape):

```python
"""Neo4j Aura CFN resources — Lambda + IAM role + custom resource trigger."""

from pathlib import Path
from typing import Final

LAMBDA_CODE_DIR: Final[Path] = Path(__file__).parent / "lambda_code"


def _load_lambda_source(filename: str) -> str:
    return (LAMBDA_CODE_DIR / filename).read_text()


def aura_provisioning_resources() -> dict[str, object]:
    """CFN resources that provision a Neo4j Aura instance via REST API."""
    return {
        "AuraLambdaRole": {
            "Type": "AWS::IAM::Role",
            "Properties": {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "lambda.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                },
                "ManagedPolicyArns": [
                    "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
                ],
                "Policies": [
                    {
                        "PolicyName": "aura-secret-write",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": [
                                        "secretsmanager:CreateSecret",
                                        "secretsmanager:DeleteSecret",
                                        "secretsmanager:PutSecretValue",
                                    ],
                                    "Resource": "*",
                                }
                            ],
                        },
                    }
                ],
            },
        },
        "AuraLambda": {
            "Type": "AWS::Lambda::Function",
            "Properties": {
                "Runtime": "python3.13",
                "Handler": "index.handler",
                "Role": {"Fn::GetAtt": ["AuraLambdaRole", "Arn"]},
                "Timeout": 900,
                "Code": {"ZipFile": _load_lambda_source("aura_provisioner.py")},
            },
        },
        "AuraCustomResource": {
            "Type": "Custom::Neo4jAuraInstance",
            "Properties": {
                "ServiceToken": {"Fn::GetAtt": ["AuraLambda", "Arn"]},
                "Neo4jAuraClientId": {"Ref": "Neo4jAuraClientId"},
                "Neo4jAuraClientSecret": {"Ref": "Neo4jAuraClientSecret"},
                "DeploymentUuid": {"Ref": "AWS::StackName"},
            },
        },
    }
```

- [ ] **Step 4: Run — verify pass**

```bash
uv run pytest -vv src/cfn/persistence/aura_resources_test.py
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cfn/persistence/aura_resources.py src/cfn/persistence/aura_resources_test.py
git commit -m "feat(cfn/persistence): Neo4j Aura Lambda + custom resource"
```

---

## Task 11: PersistenceService composes all three blocks

**Files:**
- Modify: `src/cfn/persistence/persistence_service.py`
- Modify: `src/cfn/persistence/persistence_service_test.py`

- [ ] **Step 1: Add the failing tests**

Append to `src/cfn/persistence/persistence_service_test.py`:

```python
def test_build_resources_merges_aurora_tiger_and_aura() -> None:
    """All three sub-blocks present in the merged dict."""
    # Arrange
    service = PersistenceService()

    # Act
    resources = service.build_resources()

    # Assert — pick one representative key from each block
    assert "AuroraCluster" in resources       # Aurora
    assert "TigerCustomResource" in resources # Tiger
    assert "AuraCustomResource" in resources  # Aura


def test_build_resources_keys_are_unique() -> None:
    """No accidental key collision across the three sub-blocks."""
    # Arrange
    service = PersistenceService()

    # Act
    aurora_keys = set(__import__("src.cfn.persistence.aurora_resources", fromlist=["aurora_cluster_resources"]).aurora_cluster_resources().keys())
    tiger_keys = set(__import__("src.cfn.persistence.tiger_resources", fromlist=["tiger_provisioning_resources"]).tiger_provisioning_resources().keys())
    aura_keys = set(__import__("src.cfn.persistence.aura_resources", fromlist=["aura_provisioning_resources"]).aura_provisioning_resources().keys())

    # Assert — no overlap
    assert aurora_keys.isdisjoint(tiger_keys)
    assert aurora_keys.isdisjoint(aura_keys)
    assert tiger_keys.isdisjoint(aura_keys)
```

- [ ] **Step 2: Run — verify fail**

```bash
uv run pytest -vv src/cfn/persistence/persistence_service_test.py
```

Expected: 2 new tests FAIL (smoke test from Task 2 still passes).

- [ ] **Step 3: Implement `build_resources()`**

Edit `src/cfn/persistence/persistence_service.py`:

```python
"""PersistenceService — composes Aurora + Tiger + Aura CFN resource blocks."""

from src.cfn.persistence.aura_resources import aura_provisioning_resources
from src.cfn.persistence.aurora_resources import aurora_cluster_resources
from src.cfn.persistence.tiger_resources import tiger_provisioning_resources


class PersistenceService:
    """Single entry point for building the persistence section of the CFN template."""

    def build_resources(self) -> dict[str, object]:
        """Return the merged Aurora + Tiger + Aura resource dict (CFN `Resources:`)."""
        return {
            **aurora_cluster_resources(),
            **tiger_provisioning_resources(),
            **aura_provisioning_resources(),
        }
```

- [ ] **Step 4: Run — verify pass**

```bash
uv run pytest -vv src/cfn/persistence/persistence_service_test.py
```

Expected: all 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cfn/persistence/persistence_service.py src/cfn/persistence/persistence_service_test.py
git commit -m "feat(cfn/persistence): PersistenceService composes all three blocks"
```

---

## Task 12: Wire PersistenceService into CfnService

**Files:**
- Modify: `src/cfn/cfn_service.py`
- Modify: `src/cfn/cfn_module.py`
- Modify: `src/cfn/cfn_service_test.py`

- [ ] **Step 1: Write the failing test**

Append to `src/cfn/cfn_service_test.py`:

```python
def test_render_template_includes_aurora_cluster() -> None:
    """Persistence sub-module's Aurora resources are merged into the template."""
    # Arrange + Act
    rendered = _render()

    # Assert
    assert "AuroraCluster" in rendered
    assert "AWS::RDS::DBCluster" in rendered


def test_render_template_includes_tiger_and_aura_custom_resources() -> None:
    """Persistence sub-module's vendor custom resources are merged."""
    # Arrange + Act
    rendered = _render()

    # Assert
    assert "Custom::TigerCloudInstance" in rendered
    assert "Custom::Neo4jAuraInstance" in rendered
```

- [ ] **Step 2: Run — verify fail**

```bash
uv run pytest -vv src/cfn/cfn_service_test.py
```

Expected: 2 new tests FAIL.

- [ ] **Step 3: Inject `PersistenceService` into `CfnService`**

Edit `src/cfn/cfn_service.py`:

```python
"""CfnService — renders the per-order CloudFormation template."""

import yaml

from src.cfn.cfn_resources import (
    AMI_SSM_PARAMETER,
    build_userdata,
    iam_resources,
    network_resources,
    vendor_token_parameters,
)
from src.cfn.persistence.persistence_service import PersistenceService


class CfnService:
    """Per-order CloudFormation template renderer."""

    def __init__(self, persistence: PersistenceService) -> None:
        self._persistence = persistence

    def render_template(
        self, *, deployment_uuid: str, dtm_url: str, ems_mode: str
    ) -> str:
        """Return the per-order CFN template (yaml) with all inputs baked in."""
        short = deployment_uuid.split("-", 1)[0]
        userdata = build_userdata(
            deployment_uuid=deployment_uuid,
            dtm_url=dtm_url,
            ems_mode=ems_mode,
        )
        template = {
            "AWSTemplateFormatVersion": "2010-09-09",
            "Description": f"ARCNODE EMS deployment — {deployment_uuid}",
            "Parameters": vendor_token_parameters(),
            "Resources": {
                **network_resources(),
                **iam_resources(short=short),
                **self._persistence.build_resources(),
                "EmsInstance": {
                    "Type": "AWS::EC2::Instance",
                    "Properties": {
                        "InstanceType": "t3.medium",
                        "ImageId": AMI_SSM_PARAMETER,
                        "IamInstanceProfile": {"Ref": "EmsInstanceProfile"},
                        "SubnetId": {"Ref": "EmsSubnet"},
                        "SecurityGroupIds": [{"Ref": "EmsSecurityGroup"}],
                        "UserData": {"Fn::Base64": {"Fn::Sub": userdata}},
                        "Tags": [
                            {"Key": "Name", "Value": f"arcnode-{short}"},
                            {"Key": "ArcnodeDeploymentUuid", "Value": deployment_uuid},
                        ],
                    },
                    "DependsOn": [
                        "AuroraBootstrapCustomResource",
                        "TigerCustomResource",
                        "AuraCustomResource",
                    ],
                },
            },
            "Outputs": {
                "PublicIp": {
                    "Value": {"Fn::GetAtt": ["EmsInstance", "PublicIp"]},
                    "Description": "EMS HMI is reachable on http://<PublicIp>/",
                },
                "DeploymentUuid": {"Value": deployment_uuid},
                "DtmUrl": {"Value": dtm_url},
                "EmsMode": {"Value": ems_mode},
            },
        }
        return yaml.safe_dump(template, sort_keys=False)
```

- [ ] **Step 4: Update `cfn_module.py` for the new constructor**

Edit `src/cfn/cfn_module.py`:

```python
"""CFN module — DI assembly for `CfnService`."""

from src.cfn.cfn_service import CfnService
from src.cfn.persistence.persistence_module import PersistenceModule


class CfnModule:
    """Single point of DI for CFN template rendering."""

    def __init__(self) -> None:
        self.persistence = PersistenceModule()
        self.service = CfnService(persistence=self.persistence.service)
```

- [ ] **Step 5: Update test fixture for the new constructor**

Edit `src/cfn/cfn_service_test.py`. Update `_render()`:

```python
from src.cfn.persistence.persistence_service import PersistenceService


def _render() -> str:
    return CfnService(persistence=PersistenceService()).render_template(
        deployment_uuid=DEPLOYMENT_UUID, dtm_url=DTM_URL, ems_mode=EMS_MODE
    )
```

- [ ] **Step 6: Run all CFN tests — verify pass**

```bash
uv run pytest -vv src/cfn/
```

Expected: all PASS, including the two new render-template tests.

- [ ] **Step 7: Search for other CfnService callers in the codebase**

```bash
cd /home/resister/arcnode/platform-api
grep -rn "CfnService(" src/ tests/ --include="*.py"
```

If any caller instantiates `CfnService()` without the `persistence=` argument, update it to take `CfnModule().service` or pass a `PersistenceService()` directly.

- [ ] **Step 8: Commit**

```bash
git add src/cfn/cfn_service.py src/cfn/cfn_module.py src/cfn/cfn_service_test.py
git commit -m "feat(cfn): wire PersistenceService into CfnService composition"
```

---

## Task 13: Extend EC2 IAM role with Secrets Manager read access

**Files:**
- Modify: `src/cfn/cfn_resources.py:119-156` (`iam_resources()`)
- Modify: `src/cfn/cfn_service_test.py`

- [ ] **Step 1: Write the failing test**

Append to `src/cfn/cfn_service_test.py`:

```python
def test_instance_role_can_read_persistence_secrets() -> None:
    """EC2 instance role grants secretsmanager:GetSecretValue on ems/* prefix."""
    # Arrange + Act
    rendered = _render()

    # Assert
    assert "secretsmanager:GetSecretValue" in rendered
    assert "ems/" in rendered  # the secret-name prefix appears in the policy
```

- [ ] **Step 2: Run — verify fail**

```bash
uv run pytest -vv src/cfn/cfn_service_test.py::test_instance_role_can_read_persistence_secrets
```

Expected: FAIL.

- [ ] **Step 3: Extend `iam_resources()` in `cfn_resources.py`**

Edit `src/cfn/cfn_resources.py`. Modify `iam_resources()` to add a second policy block alongside the existing DTM-read policy:

```python
def iam_resources(*, short: str) -> dict[str, object]:
    """Instance role with S3 GetObject + Secrets Manager read for persistence secrets."""
    return {
        "EmsInstanceRole": {
            "Type": "AWS::IAM::Role",
            "Properties": {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "ec2.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                },
                "Policies": [
                    {
                        "PolicyName": f"arcnode-{short}-dtm-read",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": "s3:GetObject",
                                    "Resource": "*",
                                }
                            ],
                        },
                    },
                    {
                        "PolicyName": f"arcnode-{short}-secrets-read",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": "secretsmanager:GetSecretValue",
                                    "Resource": {
                                        "Fn::Sub": "arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:ems/*"
                                    },
                                }
                            ],
                        },
                    },
                ],
            },
        },
        "EmsInstanceProfile": {
            "Type": "AWS::IAM::InstanceProfile",
            "Properties": {"Roles": [{"Ref": "EmsInstanceRole"}]},
        },
    }
```

- [ ] **Step 4: Run — verify pass**

```bash
uv run pytest -vv src/cfn/cfn_service_test.py::test_instance_role_can_read_persistence_secrets
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cfn/cfn_resources.py src/cfn/cfn_service_test.py
git commit -m "feat(cfn): grant EC2 instance role read on ems/* Secrets Manager prefix"
```

---

## Task 14: Rewrite UserData to fetch persistence secrets

**Files:**
- Modify: `src/cfn/cfn_resources.py:159-184` (`build_userdata()`)
- Modify: `src/cfn/cfn_service_test.py`

- [ ] **Step 1: Write the failing test**

Append to `src/cfn/cfn_service_test.py`:

```python
def test_userdata_fetches_four_persistence_secrets() -> None:
    """UserData calls aws secretsmanager get-secret-value for each persistence slot."""
    # Arrange + Act
    rendered = _render()

    # Assert — four `aws secretsmanager get-secret-value ... aurora-document/aurora-vector/tiger/neo4j-aura`
    for slot in ("aurora-document", "aurora-vector", "tiger", "neo4j-aura"):
        assert slot in rendered, f"UserData missing fetch for {slot} secret"
    assert "aws secretsmanager get-secret-value" in rendered


def test_userdata_writes_secrets_to_opt_arcnode_url_files() -> None:
    """Secrets land at /opt/arcnode/<name>.url for docker-compose env_file."""
    # Arrange + Act
    rendered = _render()

    # Assert
    assert "/opt/arcnode/aurora-document.url" in rendered
    assert "/opt/arcnode/aurora-vector.url" in rendered
    assert "/opt/arcnode/tiger.url" in rendered
    assert "/opt/arcnode/neo4j-aura.url" in rendered
```

- [ ] **Step 2: Run — verify fail**

```bash
uv run pytest -vv src/cfn/cfn_service_test.py::test_userdata_fetches_four_persistence_secrets src/cfn/cfn_service_test.py::test_userdata_writes_secrets_to_opt_arcnode_url_files
```

Expected: FAIL.

- [ ] **Step 3: Rewrite `build_userdata()` in `cfn_resources.py`**

Replace the existing `build_userdata()` with:

```python
def build_userdata(*, deployment_uuid: str, dtm_url: str, ems_mode: str) -> str:
    """UserData: write deployment env, fetch persistence secrets, fetch DTM.

    Each persistence secret was created at stack-create time by the
    Aurora-bootstrap / Tiger-provisioner / Aura-provisioner Lambdas. The
    EC2 instance fetches them via the AWS CLI (already in AL2023) using
    the instance profile's secrets-read policy granted in iam_resources().
    Secrets are written to /opt/arcnode/<name>.url so docker-compose can
    source them via env_file: directives.
    """
    secret_slots = ("aurora-document", "aurora-vector", "tiger", "neo4j-aura")
    fetch_lines = "\n".join(
        f'aws secretsmanager get-secret-value --secret-id "ems/{deployment_uuid}/persistence/{slot}" '
        f'--query SecretString --output text > /opt/arcnode/{slot}.url'
        for slot in secret_slots
    )
    return (
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "mkdir -p /opt/arcnode\n"
        "cat > /opt/arcnode/deployment.env <<ENV\n"
        f"DEPLOYMENT_UUID={deployment_uuid}\n"
        f"DTM_URL={dtm_url}\n"
        f"EMS_MODE={ems_mode}\n"
        "ENV\n"
        "# Fetch persistence connection strings from Secrets Manager.\n"
        f"{fetch_lines}\n"
        "# Fetch the Device Topology Manifest via presigned URL (valid 24h).\n"
        f"curl -fsSL '{dtm_url}' -o /opt/arcnode/dtm.json || "
        "echo 'DTM fetch failed; populate /opt/arcnode/dtm.json manually'\n"
        "touch /opt/arcnode/userdata.done\n"
    )
```

- [ ] **Step 4: Run all CFN tests — verify pass**

```bash
uv run pytest -vv src/cfn/
```

Expected: all PASS.

- [ ] **Step 5: Run cfn-lint via the existing test**

The `test_render_template_passes_cfn_lint` test catches structural issues. Confirm it still passes.

```bash
uv run pytest -vv src/cfn/cfn_service_test.py::test_render_template_passes_cfn_lint
```

Expected: PASS. If it fails with new errors (e.g., "AuroraCluster references undefined AuroraSubnetGroup"), fix the offending resource block.

- [ ] **Step 6: Commit**

```bash
git add src/cfn/cfn_resources.py src/cfn/cfn_service_test.py
git commit -m "feat(cfn): UserData fetches persistence secrets from Secrets Manager"
```

---

## Task 15: Full-stack integration test

**Files:**
- Modify: `src/cfn/cfn_service_test.py`

- [ ] **Step 1: Add a final integration test**

Append to `src/cfn/cfn_service_test.py`:

```python
def test_render_template_full_resource_inventory() -> None:
    """End-to-end: rendered template contains all expected logical IDs."""
    # Arrange + Act
    rendered = _render()

    expected = [
        # Network
        "EmsVpc", "EmsSubnet", "EmsSecurityGroup",
        # IAM
        "EmsInstanceRole", "EmsInstanceProfile",
        # Aurora
        "AuroraCluster", "AuroraInstance", "AuroraMasterSecret",
        "AuroraSubnetGroup", "AuroraSecurityGroup",
        "AuroraBootstrapLambda", "AuroraBootstrapCustomResource",
        # Tiger
        "TigerLambda", "TigerCustomResource", "TigerLambdaRole",
        # Aura
        "AuraLambda", "AuraCustomResource", "AuraLambdaRole",
        # EC2
        "EmsInstance",
    ]

    for logical_id in expected:
        assert logical_id in rendered, f"missing logical id: {logical_id}"


def test_ec2_instance_depends_on_all_three_persistence_resources() -> None:
    """EC2 must wait for all three custom resources before launching."""
    # Arrange + Act
    rendered = _render()

    # Assert
    assert "AuroraBootstrapCustomResource" in rendered
    assert "TigerCustomResource" in rendered
    assert "AuraCustomResource" in rendered
    # The EC2 block specifically lists them as DependsOn
    assert "DependsOn" in rendered
```

- [ ] **Step 2: Run all tests — verify pass**

```bash
uv run pytest -vv src/cfn/
```

Expected: all PASS.

- [ ] **Step 3: Run the full project check suite**

```bash
uv run poe checks
uv run poe unit
```

Expected: all green. Fix any ruff / ty / depcheck issues that the new code introduces.

- [ ] **Step 4: Commit**

```bash
git add src/cfn/cfn_service_test.py
git commit -m "test(cfn): full-resource-inventory integration test"
```

---

## Task 16: Cross-repo — ADR-004, ADR-001 banner, readme diagram

**Files (in `/home/resister/arcnode/ems/`):**
- Create: `cloud_persistence_provisioning_adr.md`
- Modify: `system_adr.md` (add banner near "Managed Postgres Service" rejection note)
- Modify: `readme.md` (Cloud Deployment PlantUML)

- [ ] **Step 1: Write ADR-004 from the spec**

Create `/home/resister/arcnode/ems/cloud_persistence_provisioning_adr.md`. Use the standard ADR template (matches `boot_strategy_adr.md`):

```markdown
# ADR-004: Cloud Persistence Provisioning Strategy

**Status:** Accepted
**Date:** 2026-05-10
**Decision Makers:** Development Team
**Consulted:** Operations, Site Integrators
**Informed:** EMS Subsystem Maintainers, OSS contributors

## Context

[Lift the Context section from the design spec at
docs/superpowers/specs/2026-05-10-cloud-persistence-provisioning-design.md]

## Decision

[Lift Decision summary from the spec — three-line version]

## Implementation

See [`docs/superpowers/specs/2026-05-10-cloud-persistence-provisioning-design.md`]
for full design and [platform-api implementation plan]
(../platform-api/docs/superpowers/plans/2026-05-10-cloud-persistence-provisioning.md).

## Consequences

[Lift from the spec]

## Alternatives Considered

[Lift from the spec]

## Review

This ADR should be reviewed:
- When marketplace SaaS-contract auto-provisioning becomes viable per vendor
- When Aurora ships a TimescaleDB-compatible extension
- When ISO deployment context changes
```

Fill in the bracketed sections by copying from the spec verbatim where possible.

- [ ] **Step 2: Add the banner to ADR-001**

Edit `/home/resister/arcnode/ems/system_adr.md`. Find the section heading
`### Managed Postgres Service (like Neon) with TimeSeries Extension`. Insert immediately after the heading:

```markdown
> **Note (2026-05-10):** [ADR-004](cloud_persistence_provisioning_adr.md) supersedes this rejection for the document + vector slice (Aurora serverless PG with `pgvector` ext, OSS plug-and-play driver). The rejection still holds for the time-series slice — Tiger Cloud is kept for TimescaleDB features.

```

- [ ] **Step 3: Update the Cloud Deployment diagram**

Edit `/home/resister/arcnode/ems/readme.md`. In the `## Cloud Deployment (AWS)` PlantUML block, replace:

```
    cloud timescale_cloud
    cloud neon_vector
    cloud neon_document
    cloud neo4j_aura
```

With:

```
    cloud timescale_cloud
    database aurora_serverless
    cloud neo4j_aura
```

- [ ] **Step 4: Commit (in ems repo)**

```bash
cd /home/resister/arcnode/ems
git add cloud_persistence_provisioning_adr.md system_adr.md readme.md
git commit -m "$(cat <<'EOF'
📝 docs: ADR-004 cloud persistence provisioning + ADR-001 banner + readme diagram

ADR-004 codifies the decision to replace Neon (doc+vector) with Aurora
serverless PG and provision Tiger Cloud + Neo4j Aura via inline-Lambda
CFN custom resources. ADR-001 §"Managed Postgres Service" rejection
banner notes the partial supersession. Cloud Deployment diagram updated
to show aurora_serverless in place of the two Neon clouds.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Confirm the cross-link from spec → ADR-004 works**

```bash
grep "cloud_persistence_provisioning_adr.md" /home/resister/arcnode/ems/docs/superpowers/specs/2026-05-10-cloud-persistence-provisioning-design.md
```

Expected: at least one match (the spec already says "this spec is the design source for ADR-004"). If the spec needs a direct link line, add one:

```markdown
**Resulting ADR:** [ADR-004 Cloud Persistence Provisioning Strategy](../../../cloud_persistence_provisioning_adr.md)
```

If you add it, commit:

```bash
git add docs/superpowers/specs/2026-05-10-cloud-persistence-provisioning-design.md
git commit -m "📝 docs: spec → ADR-004 cross-link"
```

---

## Self-Review Notes

- **Spec coverage:** Tasks 1–15 cover all sections of the spec's "Design" + "Failure modes" + "Cost floor" sections (the latter two via test assertions). Task 16 covers the spec's "Updates to existing docs" section. The spec's "Future work" section is intentionally not implemented (it's deferred work).
- **Placeholder note:** Task 0 outputs (vendor REST API endpoint paths + body shapes) feed into Tasks 7 and 9 implementations. The placeholder `https://api.tigerdata.com` and `https://api.neo4j.io` API base URLs and the request bodies in Tasks 7 + 9 should be replaced with the verified paths from Task 0 research before running the tests in those tasks.
- **psycopg2 layer ARN:** Task 6 uses a placeholder Lambda Layer ARN. Verify a current public layer ARN per region or self-publish a layer in a future hardening task. The arn shown is illustrative — replace before stack-create.
- **Single-AZ subnet group:** Task 4 reuses `EmsSubnet` twice in the subnet group. AWS RDS requires two subnets in different AZs for production clusters; this works for dev/test but a follow-up should add `EmsSubnetB` in a second AZ to `network_resources()` for production deployments.
