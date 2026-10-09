"""The on-prem Neo4j page: fixed memory, listen on the arcnode gateway
only, change the default password to the customer's, save GRAPH_URL for
the EMS containers, verify. The package itself was installed (and left
off) by src/iso/phases/neo4j.sh."""

import time
from pathlib import Path
from typing import Final
from urllib.parse import quote, unquote, urlsplit

from src.wizard.docker_verify import missing_network_check, read_network
from src.wizard.neo4j_verify import (
    BOLT_PORT,
    GRAPH_URL,
    HEAP_GIB,
    NEO4J_CONF,
    NEO4J_UNIT,
    PAGECACHE_GIB,
    cypher,
    listeners,
    verify_neo4j,
)
from src.wizard.secrets_env import read_secret, save_secrets
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import (
    Command,
    Deployment,
    DockerNetwork,
    PasswordRequest,
    StepResult,
)
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker

# Neo4j's published factory default, replaced on this page — not a secret.
DEFAULT_PASSWORD: Final[str] = "neo4j"  # noqa: S105  # nosec B105
# Poll interval for the readiness gate below — not a timeout.
POLL_SECONDS: Final[float] = 0.5


class Neo4jStepNotAvailableError(Exception):
    """No Neo4j page in the cloud — the graph is Aura or Neptune."""


class Neo4jService:
    """Everything the EMS containers need from the host's Neo4j."""

    def __init__(
        self,
        *,
        deployment: Deployment,
        tracker: StepTracker,
        secrets_env_path: Path,
        run: Runner,
    ) -> None:
        self._deployment = deployment
        self._tracker = tracker
        self._secrets_env_path = secrets_env_path
        self._run = run

    def apply(self, request: PasswordRequest) -> StepResult:
        """Configure, then verify — the page is only marked done when every
        check passes. Every step is idempotent, so a retry is safe."""
        if self._deployment == Deployment.CLOUD:
            raise Neo4jStepNotAvailableError("no Neo4j step in the cloud")
        if self._tracker.is_done("neo4j"):
            raise StepAlreadyDoneError("Neo4j is already set up")
        network = read_network(self._run)
        if network is None:
            return StepResult(verified=False, checks=[missing_network_check()])
        self._configure(network)
        if self._wait_for_bolt() and self._set_password(request.password, network):
            url = f"bolt://neo4j:{quote(request.password, safe='')}@{network.gateway}:{BOLT_PORT}"
            save_secrets(self._secrets_env_path, {GRAPH_URL: url})
        checks = verify_neo4j(
            self._run, request.password, network, self._secrets_env_path
        )
        verified = all(check.ok for check in checks)
        if verified:
            self._tracker.mark_done("neo4j")
        return StepResult(verified=verified, checks=checks)

    def _configure(self, network: DockerNetwork) -> None:
        """Edit neo4j.conf in place (it has no include dir), then start it."""
        settings = {
            "server.default_listen_address": str(network.gateway),
            # The browser UI port — nothing in the EMS uses it.
            "server.http.enabled": "false",
            "server.memory.heap.initial_size": f"{HEAP_GIB}g",
            "server.memory.heap.max_size": f"{HEAP_GIB}g",
            "server.memory.pagecache.size": f"{PAGECACHE_GIB}g",
        }
        # Reason: matches the shipped line, commented out or not, so a
        # retry rewrites it instead of appending a duplicate.
        expressions = [
            arg
            for name, value in settings.items()
            for arg in ("-e", f"s/^#\\?{name}=.*/{name}={value}/")
        ]
        self._run(Command(args=["sed", "-i", *expressions, NEO4J_CONF]))
        self._run(Command(args=["systemctl", "enable", NEO4J_UNIT]))
        self._run(Command(args=["systemctl", "restart", NEO4J_UNIT]))

    def _wait_for_bolt(self) -> bool:
        """Readiness gate: the unit is up the moment Java starts, bolt opens
        once the databases are; stop the moment the unit dies instead."""
        while not any(a.endswith(f":{BOLT_PORT}") for a in listeners(self._run)):
            state = self._run(Command(args=["systemctl", "is-active", NEO4J_UNIT]))
            if state.stdout.strip() not in ("active", "activating"):
                return False
            time.sleep(POLL_SECONDS)
        return True

    def _set_password(self, password: str, network: DockerNetwork) -> bool:
        """Change it from the default — or, on a retry, from the password an
        earlier try saved. False when neither works."""
        olds = [DEFAULT_PASSWORD]
        saved = read_secret(self._secrets_env_path, GRAPH_URL)
        if saved and urlsplit(saved).password:
            olds.append(unquote(urlsplit(saved).password or ""))
        for old in dict.fromkeys(olds):
            # Reason: on stdin as Cypher params — not argv (visible in ps),
            # not spliced into the statement.
            script = (
                f":param old => {_cypher_string(old)}\n"
                f":param new => {_cypher_string(password)}\n"
                "ALTER CURRENT USER SET PASSWORD FROM $old TO $new;\n"
            )
            command = cypher(network, old)
            command.input = script
            if self._run(command).returncode == 0:
                return True
        return False


def _cypher_string(value: str) -> str:
    """A single-quoted Cypher string literal."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
