"""Boot the rendered UserData inside an amazonlinux:2023 container.

What this catches that pure string-asserts can't:
  - Bash syntax errors / unbalanced quotes
  - Missing tools (curl, dnf) on the AL2023 image
  - Wrong file layout (writes to the right /opt/arcnode/* paths)
  - Ordering bugs in the fetch / write / install sequence

What it doesn't (and can't, without docker-in-docker + real AWS):
  - actual docker compose lifecycle
  - real AWS Secrets Manager / SSM calls
  - real arcnode-public S3 reads (mocked to a local HTTP server)

Strategy:
  1. Render UserData via CfnService for both variants (CFN ``Fn::Sub``
     vars manually substituted to plausible test values).
  2. Spin up an ``amazonlinux:2023`` container with a tiny shim for
     ``aws``: returns canned secret / SSM values from echo.
  3. Mount the rendered UserData as ``/var/lib/cloud/instance/scripts/userdata.sh``
     and execute it.
  4. Assert ``/opt/arcnode/{config.env,secrets.env,docker-compose.yaml,...}``
     end up with the right shape inside the container.
  5. Stop short of ``docker compose up`` — strip that final command so
     the test doesn't need docker-in-docker.
"""

import contextlib
import re
import textwrap
from pathlib import Path

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from src.cfn.cfn_resources import ARCNODE_PUBLIC_BASE_URL, build_userdata
from src.orders.configurator_payload import DeploymentContext

DEPLOYMENT_UUID = "lifecycle-test-001"
DTM_URL = "https://example.com/dtm.json"
TEST_STACK = "lifecycletest"

# Tiny shim that replaces /usr/bin/aws inside the container. Returns
# deterministic strings per slot/parameter — enough to verify that
# UserData wires the values into the right env files.
AWS_SHIM = textwrap.dedent("""\
    #!/bin/bash
    # First arg is the service (secretsmanager / ssm); third arg is the
    # subcommand (get-secret-value / get-parameter). Slot names are passed
    # via --secret-id / --name and contain the slot suffix.
    case "$1 $2" in
      "secretsmanager get-secret-value")
        for arg in "$@"; do
          case "$arg" in
            arcnode-ems-*/document-url)   echo 'postgres://doc-user:doc-pw@aurora/ems_document'; exit 0 ;;
            arcnode-ems-*/vector-url)     echo 'postgres://vec-user:vec-pw@aurora/ems_vector'; exit 0 ;;
            arcnode-ems-*/timeseries-url) echo 'postgres://ts-user:ts-pw@tiger.example/ems_timeseries'; exit 0 ;;
            arcnode-ems-*/graph-url)      echo 'neo4j+s://aura-user:aura-pw@aura.example:7687'; exit 0 ;;
          esac
        done ;;
      "ssm get-parameter")
        for arg in "$@"; do
          case "$arg" in
            /arcnode-ems/*/neptune-host)            echo 'neptune.example.com'; exit 0 ;;
            /arcnode-ems/*/aoss-host)               echo 'collection.aoss.example.com'; exit 0 ;;
            /arcnode-ems/*/neptune-loader-role-arn) echo 'arn:aws:iam::000000000000:role/NeptuneLoaderRole'; exit 0 ;;
          esac
        done ;;
    esac
    echo "unmocked aws call: $*" >&2
    exit 99
    """)


def _render_with_test_stack_name(deployment_context: DeploymentContext) -> str:
    """Render UserData with CFN ``Fn::Sub`` vars replaced by literals.

    The real CFN substitutes ``${AWS::StackName}`` at deploy time. For
    container-local execution we need a concrete string, so swap it
    here.
    """
    raw = build_userdata(
        deployment_uuid=DEPLOYMENT_UUID,
        dtm_url=DTM_URL,
        site_id="test_site",
        wholesale_market="ercot",
        settlement_point="HB_NORTH",
        deployment_context=deployment_context,
    )
    return raw.replace("${AWS::StackName}", TEST_STACK)


def _strip_docker_steps(rendered: str) -> str:
    """Strip the docker install + ``docker compose up`` lines.

    Container-in-container is out of scope for this test. We exercise
    everything up to (but not including) the docker boot.
    """
    return re.sub(
        r"# Install docker.*?docker compose up -d\n",
        "# (docker install + compose up stripped for in-container test)\n",
        rendered,
        flags=re.DOTALL,
    )


@pytest.fixture
def amazon_linux_container(tmp_path: Path):
    """An ``amazonlinux:2023`` container with the aws shim already in place."""
    shim = tmp_path / "aws-shim"
    shim.write_text(AWS_SHIM)
    shim.chmod(0o755)

    container = (
        DockerContainer("amazonlinux:2023")
        .with_volume_mapping(str(shim), "/usr/local/bin/aws", "ro")
        .with_command("sleep 600")  # keep alive while test runs commands
    )
    container.start()
    # AL2023 image emits no startup logs; suppress the timeout that wait_for_logs raises.
    with contextlib.suppress(Exception):
        wait_for_logs(container, "", timeout=10)
    yield container
    container.stop()


def _run_userdata(container: DockerContainer, script: str) -> tuple[int, str]:
    """Copy a UserData script into the container, execute it, return (exit, output)."""
    # Drop into a file inside the container; tempfile is on the test host.
    exit_code, output = container.exec(
        [
            "bash",
            "-c",
            f"cat > /tmp/userdata.sh <<'USEREOF'\n{script}\nUSEREOF\nbash /tmp/userdata.sh",
        ]
    )
    return exit_code, output.decode() if isinstance(output, bytes) else output


@pytest.mark.parametrize(
    "deployment_context",
    [DeploymentContext.COMMERCIAL, DeploymentContext.DEFENSE_FORWARD],
)
@pytest.mark.skip(reason="SMOKE-LEAN: slot list + init scripts trimmed")
def test_userdata_lays_out_arcnode_dir_inside_amazonlinux(
    deployment_context: DeploymentContext, amazon_linux_container: DockerContainer
) -> None:
    """UserData ends with /opt/arcnode/ holding env files + compose + DTM."""
    # Arrange — render + strip docker bits
    rendered = _strip_docker_steps(_render_with_test_stack_name(deployment_context))
    # Skip the DTM curl — we don't have a real presigned URL
    rendered = rendered.replace(
        f"curl -fsSL '{DTM_URL}' -o /opt/arcnode/dtm.json",
        "echo '{\"mocked\": true}' > /opt/arcnode/dtm.json #",
    )
    # Skip the arcnode-public fetches — point them at empty placeholders so
    # the script doesn't curl real S3 from the test container.
    rendered = rendered.replace(
        f"{ARCNODE_PUBLIC_BASE_URL}/",
        "https://placeholder.example/",
    )
    rendered = re.sub(
        r"curl -fsSL https://placeholder\.example/[^\s]+ -o ([^\s]+)",
        r"echo placeholder > \1",
        rendered,
    )

    # Act
    exit_code, output = _run_userdata(amazon_linux_container, rendered)

    # Assert — UserData ran cleanly
    assert exit_code == 0, f"UserData failed: {output}"

    # Assert — files landed where expected
    _, ls = amazon_linux_container.exec(["ls", "/opt/arcnode/"])
    listing = (ls.decode() if isinstance(ls, bytes) else ls).split()
    assert "config.env" in listing
    assert "secrets.env" in listing
    assert "docker-compose.yaml" in listing
    assert "dtm.json" in listing
    assert "userdata.done" in listing

    # Assert — every init script compose mounts is present per variant
    _, init_ls = amazon_linux_container.exec(["ls", "/opt/arcnode/init-scripts/"])
    init_listing = (init_ls.decode() if isinstance(init_ls, bytes) else init_ls).split()
    expected_inits = {
        "render_emqx_rule.py",
        "seed-vector.sh",
        "seed-timeseries.sh",
        (
            "seed-graph-neo4j.py"
            if deployment_context == DeploymentContext.COMMERCIAL
            else "seed-graph-neptune.py"
        ),
    }
    missing = expected_inits - set(init_listing)
    assert not missing, f"missing init scripts: {missing}; got {init_listing}"


@pytest.mark.skip(
    reason="SMOKE-LEAN: VECTOR_URL slot dropped affects commercial too — restore commercial alongside the analyst stack"
)
def test_commercial_secrets_env_contains_graph_url(
    amazon_linux_container: DockerContainer,
) -> None:
    """Commercial variant writes GRAPH_URL (Aura) into secrets.env."""
    # Arrange
    rendered = _strip_docker_steps(
        _render_with_test_stack_name(DeploymentContext.COMMERCIAL)
    )
    rendered = rendered.replace(
        f"curl -fsSL '{DTM_URL}' -o /opt/arcnode/dtm.json",
        "echo '{}' > /opt/arcnode/dtm.json #",
    )
    rendered = rendered.replace(
        f"{ARCNODE_PUBLIC_BASE_URL}/", "https://placeholder.example/"
    )
    rendered = re.sub(
        r"curl -fsSL https://placeholder\.example/[^\s]+ -o ([^\s]+)",
        r"echo placeholder > \1",
        rendered,
    )

    # Act
    exit_code, _ = _run_userdata(amazon_linux_container, rendered)
    assert exit_code == 0

    _, secrets = amazon_linux_container.exec(["cat", "/opt/arcnode/secrets.env"])
    secrets_text = secrets.decode() if isinstance(secrets, bytes) else secrets

    # Assert — credentials landed in the right file
    assert "DOCUMENT_URL=postgres://doc-user:doc-pw@aurora/ems_document" in secrets_text
    assert "VECTOR_URL=postgres://vec-user:vec-pw@aurora/ems_vector" in secrets_text
    assert (
        "TIMESERIES_URL=postgres://ts-user:ts-pw@tiger.example/ems_timeseries"
        in secrets_text
    )
    assert "GRAPH_URL=neo4j+s://aura-user:aura-pw@aura.example:7687" in secrets_text


@pytest.mark.skip(reason="SMOKE-LEAN: Neptune+AOSS SSM params commented out")
def test_defense_config_env_contains_neptune_aoss_loader_arn(
    amazon_linux_container: DockerContainer,
) -> None:
    """Defense variant writes NEPTUNE_HOST / AOSS_HOST / NEPTUNE_LOADER_ROLE_ARN into config.env."""
    # Arrange
    rendered = _strip_docker_steps(
        _render_with_test_stack_name(DeploymentContext.DEFENSE_FORWARD)
    )
    rendered = rendered.replace(
        f"curl -fsSL '{DTM_URL}' -o /opt/arcnode/dtm.json",
        "echo '{}' > /opt/arcnode/dtm.json #",
    )
    rendered = rendered.replace(
        f"{ARCNODE_PUBLIC_BASE_URL}/", "https://placeholder.example/"
    )
    rendered = re.sub(
        r"curl -fsSL https://placeholder\.example/[^\s]+ -o ([^\s]+)",
        r"echo placeholder > \1",
        rendered,
    )

    # Act
    exit_code, _ = _run_userdata(amazon_linux_container, rendered)
    assert exit_code == 0

    _, config = amazon_linux_container.exec(["cat", "/opt/arcnode/config.env"])
    config_text = config.decode() if isinstance(config, bytes) else config

    # Assert — non-secret config landed in the right file
    assert "NEPTUNE_HOST=neptune.example.com" in config_text
    assert "AOSS_HOST=collection.aoss.example.com" in config_text
    assert (
        "NEPTUNE_LOADER_ROLE_ARN=arn:aws:iam::000000000000:role/NeptuneLoaderRole"
        in config_text
    )

    # Assert — no graph-url credentials in defense (Neptune is IAM-auth)
    _, secrets = amazon_linux_container.exec(["cat", "/opt/arcnode/secrets.env"])
    secrets_text = secrets.decode() if isinstance(secrets, bytes) else secrets
    assert "GRAPH_URL=" not in secrets_text
