"""Playbook-style verification for the Neo4j page — each check a row the
UI shows, with the console command that debugs it."""

from pathlib import Path
from typing import Final

from src.wizard.docker_verify import DOCKER_NETWORK
from src.wizard.secrets_env import saved_check
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import Command, DockerNetwork, VerifyCheck

NEO4J_UNIT: Final[str] = "neo4j"
NEO4J_CONF: Final[str] = "/etc/neo4j/neo4j.conf"
# Same version as the apt pin in src/iso/phases/neo4j.sh — the probe
# container's cypher-shell matches the server.
NEO4J_VERSION: Final[str] = "2026.09.0"
PROBE_IMAGE: Final[str] = f"neo4j:{NEO4J_VERSION}-community"
BOLT_PORT: Final[int] = 7687
# Every port Neo4j Community can listen on: bolt, http, https.
NEO4J_PORTS_FILTER: Final[str] = "( sport = :7687 or sport = :7474 or sport = :7473 )"
# Fixed, so Neo4j can't grow into Postgres's and Ollama's share of the box.
HEAP_GIB: Final[int] = 4
PAGECACHE_GIB: Final[int] = 4
MEMORY_SQL: Final[str] = (
    "SHOW SETTINGS YIELD name, value WHERE name IN ["
    "'server.memory.heap.initial_size', 'server.memory.heap.max_size', "
    "'server.memory.pagecache.size'] RETURN name, value"
)
VERSION_SQL: Final[str] = (
    "CALL dbms.components() YIELD versions, edition "
    "RETURN versions[0] + ' ' + edition AS v"
)
LOG_HINT: Final[str] = "sudo systemctl status neo4j; sudo journalctl -u neo4j -n 50"
GRAPH_URL: Final[str] = "GRAPH_URL"  # same name as the cloud's Aura URL


def cypher(network: DockerNetwork, password: str, *query: str) -> Command:
    """cypher-shell as the neo4j user against the gateway's bolt port; the
    password rides in the env. No query → the script comes on stdin."""
    return Command(
        args=[
            "cypher-shell",
            "-a",
            f"bolt://{network.gateway}:{BOLT_PORT}",
            "-u",
            "neo4j",
            "-d",
            "system" if not query else "neo4j",
            "--format",
            "plain",
            *query,
        ],
        env={"NEO4J_PASSWORD": password},
    )


def listeners(run: Runner) -> list[str]:
    """Neo4j's listening sockets as `address:port` — java's v4-mapped
    `[::ffff:172.23.0.1]:7687` reads as `172.23.0.1:7687`."""
    out = run(Command(args=["ss", "-Htln", NEO4J_PORTS_FILTER]))
    found = []
    for line in out.stdout.splitlines():
        address, _, port = line.split()[3].rpartition(":")
        found.append(f"{address.strip('[]').removeprefix('::ffff:')}:{port}")
    return found


def verify_neo4j(
    run: Runner, password: str, network: DockerNetwork, secrets_env_path: Path
) -> list[VerifyCheck]:
    """Running → password → memory → gateway only → a container connects →
    GRAPH_URL saved."""
    return [
        _running(run),
        _accepts_password(run, password, network),
        _memory(run, password, network),
        _listens(run, network),
        _container_connects(run, password, network),
        saved_check(secrets_env_path, [GRAPH_URL]),
    ]


def _first_line(stdout: str, returncode: int) -> str:
    return (stdout.strip().splitlines() or [f"exit {returncode}"])[0]


def _running(run: Runner) -> VerifyCheck:
    out = run(Command(args=["systemctl", "is-active", NEO4J_UNIT]))
    state = out.stdout.strip() or f"exit {out.returncode}"
    return VerifyCheck(
        name="Neo4j running", ok=state == "active", detail=state, hint=LOG_HINT
    )


def _accepts_password(
    run: Runner, password: str, network: DockerNetwork
) -> VerifyCheck:
    out = run(cypher(network, password, VERSION_SQL))
    lines = out.stdout.strip().splitlines()
    ok = out.returncode == 0 and len(lines) > 1
    return VerifyCheck(
        name="Accepts the password you set",
        ok=ok,
        detail=(
            f"connected as neo4j: {lines[1].strip(chr(34))}"
            if ok
            else _first_line(out.stdout, out.returncode)
        ),
        hint=LOG_HINT,
    )


def _memory(run: Runner, password: str, network: DockerNetwork) -> VerifyCheck:
    """What the running server actually uses, not what the file says."""
    out = run(cypher(network, password, MEMORY_SQL))
    settings = {}
    for line in out.stdout.strip().splitlines()[1:]:
        name, _, value = line.partition(", ")
        settings[name.strip('"')] = value.strip('"')
    heap = f"{HEAP_GIB}.00GiB"
    pagecache = f"{PAGECACHE_GIB}.00GiB"
    expected = {
        "server.memory.heap.initial_size": heap,
        "server.memory.heap.max_size": heap,
        "server.memory.pagecache.size": pagecache,
    }
    ok = out.returncode == 0 and settings == expected
    seen = (
        f"heap {settings.get('server.memory.heap.max_size', '?')}, "
        f"page cache {settings.get('server.memory.pagecache.size', '?')}"
    )
    return VerifyCheck(
        name="Memory fixed",
        ok=ok,
        detail=seen if ok else f"{seen} (want heap {heap}, page cache {pagecache})",
        hint=f"sudo grep ^server.memory {NEO4J_CONF}; free -g",
    )


def _listens(run: Runner, network: DockerNetwork) -> VerifyCheck:
    expected = f"{network.gateway}:{BOLT_PORT}"
    found = listeners(run)
    ok = found == [expected]
    seen = ", ".join(found) or "nothing"
    return VerifyCheck(
        name="Listens on Docker's gateway only",
        ok=ok,
        detail=seen if ok else f"{seen} (want {expected} only)",
        hint=f"sudo ss -ltnp | grep java; sudo grep -E 'listen_address|enabled=' {NEO4J_CONF}",
    )


def _container_connects(
    run: Runner, password: str, network: DockerNetwork
) -> VerifyCheck:
    # Reason: the path the EMS containers take — from the arcnode network
    # to the gateway, with the password. `-e NEO4J_PASSWORD` (no value)
    # passes it from this process's env, so it never lands in argv.
    url = f"bolt://{network.gateway}:{BOLT_PORT}"
    out = run(
        Command(
            args=[
                "docker",
                "run",
                "--rm",
                "--network",
                DOCKER_NETWORK,
                "-e",
                "NEO4J_PASSWORD",
                PROBE_IMAGE,
                "cypher-shell",
                "-a",
                url,
                "-u",
                "neo4j",
                "-d",
                "neo4j",
                "--format",
                "plain",
                "RETURN 1 AS ok",
            ],
            env={"NEO4J_PASSWORD": password},
        )
    )
    # A first run prints the image pull above the answer or the error.
    lines = out.stdout.strip().splitlines() or [f"exit {out.returncode}"]
    ok = out.returncode == 0 and lines[-1] == "1"
    errors = [line for line in lines if line.startswith("docker:")]
    return VerifyCheck(
        name="A container on the arcnode network connects",
        ok=ok,
        detail=f"{PROBE_IMAGE} → {url}" if ok else (errors or [lines[-1]])[0],
        hint=f"sudo ss -ltnp | grep {BOLT_PORT}; sudo journalctl -u neo4j -n 50",
    )
