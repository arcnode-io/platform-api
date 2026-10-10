"""Playbook-style checks for the Device API page: it answers, an operator can
log in, the topology it loaded matches the order's, it reached the broker."""

import json
from pathlib import Path
from typing import Final

from src.customer_inputs import OPERATOR_LOGIN, VIEWER_LOGIN
from src.wizard.containers_compose import compose_command
from src.wizard.docker_verify import DOCKER_NETWORK
from src.wizard.secrets_env import saved_check
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import Command, DeviceApiSecrets, VerifyCheck

DEVICE_API_SERVICE: Final[str] = "device-api"
BASE_URL: Final[str] = "http://device-api:3000"
# Same curl image the Ollama page probes with.
PROBE_IMAGE: Final[str] = "curlimages/curl"
OPERATOR_USERNAME: Final[str] = "operator"
DTM_FILE: Final[str] = "dtm.json"
SAVED_NAMES: Final[list[str]] = ["AUTH_JWT_SECRET", OPERATOR_LOGIN.env_name, VIEWER_LOGIN.env_name]
LOG_HINT: Final[str] = "sudo docker compose -f /opt/arcnode/docker-compose.yaml logs device-api"


def verify_device_api(
    run: Runner, secrets: DeviceApiSecrets, secrets_env_path: Path, ems_dir: Path
) -> list[VerifyCheck]:
    """Answers → operator login → topology matches the order → broker connected → saved."""
    return [
        _answers(run),
        _spec_served(run),
        _operator_login(run, secrets),
        _topology(run, ems_dir),
        _broker_connected(run, ems_dir),
        saved_check(secrets_env_path, SAVED_NAMES),
    ]


def _probe(curl_args: list[str], stdin: str | None = None) -> Command:
    """A curl on the arcnode network. A body goes in on stdin, never argv."""
    return Command(
        args=["docker", "run", "--rm", "-i", "--network", DOCKER_NETWORK, PROBE_IMAGE, *curl_args],
        input=stdin,
    )


def _answers(run: Runner) -> VerifyCheck:
    out = run(_probe(["-fsS", f"{BASE_URL}/"]))
    ok = out.returncode == 0 and out.stdout.strip() == "ok"
    return VerifyCheck(
        name="Device API answers",
        ok=ok,
        detail="ok" if ok else (out.stdout.strip() or f"exit {out.returncode}"),
        hint=LOG_HINT,
    )


def _spec_served(run: Runner) -> VerifyCheck:
    """The industrial gateway and HMI both fetch /asyncapi at boot. A 503 here means
    the topology can't build a spec, so it shows on this page instead of the gateway's."""
    out = run(_probe(["-fsS", "-o", "/dev/null", f"{BASE_URL}/asyncapi"]))
    ok = out.returncode == 0
    return VerifyCheck(
        name="Serves its message spec",
        ok=ok,
        detail="/asyncapi answers 200" if ok else f"/asyncapi failed (curl exit {out.returncode})",
        hint=LOG_HINT,
    )


def _operator_login(run: Runner, secrets: DeviceApiSecrets) -> VerifyCheck:
    body = json.dumps({"username": OPERATOR_USERNAME, "password": secrets.operator_password})
    out = run(
        _probe(
            ["-fsS", "-H", "Content-Type: application/json", "--data-binary", "@-",
             f"{BASE_URL}/auth/login"],
            stdin=body,
        )
    )
    ok = out.returncode == 0 and '"token"' in out.stdout
    return VerifyCheck(
        name="Operator can log in",
        ok=ok,
        detail="token issued" if ok else "login refused — check the operator password you set",
        hint=LOG_HINT,
    )


def _topology(run: Runner, ems_dir: Path) -> VerifyCheck:
    out = run(_probe(["-fsS", f"{BASE_URL}/topology"]))
    expected = len(json.loads((ems_dir / DTM_FILE).read_text())["devices"])
    try:
        loaded = len(json.loads(out.stdout)["devices"]) if out.returncode == 0 else 0
    except (ValueError, KeyError):
        loaded = 0
    return VerifyCheck(
        name="Topology loaded",
        ok=loaded == expected and expected > 0,
        detail=f"{loaded} of {expected} devices",
        hint=LOG_HINT,
    )


def _broker_connected(run: Runner, ems_dir: Path) -> VerifyCheck:
    logs = run(compose_command(ems_dir, "logs", DEVICE_API_SERVICE)).stdout
    connected = "mqtt connected" in logs
    return VerifyCheck(
        name="Connected to the broker",
        ok=connected,
        detail="mqtt connected" if connected else "no broker connection in the log",
        hint=LOG_HINT,
    )
