"""Playbook-style checks for the HiveMQ page: the broker runs, refuses
anonymous logins, every account's password logs in, and the passwords are
saved for the EMS services. Each check's hint is the command that debugs it."""

from typing import Final

from src.wizard.containers_compose import compose_command
from src.wizard.docker_verify import DOCKER_NETWORK
from src.wizard.secrets_env import saved_check
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import BrokerPasswords, Command, VerifyCheck
from pathlib import Path

HIVEMQ_SERVICE: Final[str] = "hivemq"
BROKER_HOST: Final[str] = "hivemq"
BROKER_PORT: Final[int] = 1883
# Same probe image the telemetry path uses; -E exits after the connect, so
# exit 0 means the broker accepted the login.
PROBE_IMAGE: Final[str] = "eclipse-mosquitto:2"
# Any topic a gateway-style account may read; only the login is checked.
PROBE_TOPIC: Final[str] = "sites/+/devices/+/measurements/#"
LOG_HINT: Final[str] = "sudo docker compose -f /opt/arcnode/docker-compose.yaml logs hivemq"
# (BrokerPasswords field, broker username, secrets.env name) — one row per account.
# (account, username, env name, which BrokerPasswords field holds its password).
ACCOUNTS: Final[tuple[tuple[str, str, str, str], ...]] = (
    ("gateway", "arcnode_gateway", "MQTT_GATEWAY_PASSWORD", "service"),
    ("operator", "arcnode_operator", "MQTT_OPERATOR_PASSWORD", "operator"),
    ("viewer", "arcnode_viewer", "MQTT_VIEWER_PASSWORD", "viewer"),
    ("device_api", "arcnode_device_api", "MQTT_DEVICE_API_PASSWORD", "service"),
    ("telemetry_writer", "arcnode_telemetry_writer", "MQTT_TELEMETRY_WRITER_PASSWORD", "service"),
    ("der_control_api", "arcnode_der_control_api", "MQTT_DER_CONTROL_API_PASSWORD", "service"),
)


def verify_hivemq(
    run: Runner, passwords: BrokerPasswords, secrets_env_path: Path, ems_dir: Path
) -> list[VerifyCheck]:
    """Running → anonymous refused → every login accepted → saved."""
    return [
        _container_running(run, ems_dir),
        _anonymous_refused(run),
        _logins_accepted(run, passwords),
        saved_check(secrets_env_path, [env for _, _, env, _ in ACCOUNTS]),
    ]


def _container_running(run: Runner, ems_dir: Path) -> VerifyCheck:
    out = run(compose_command(ems_dir, "ps", "-q", "--status", "running", HIVEMQ_SERVICE))
    running = bool(out.stdout.strip())
    return VerifyCheck(
        name="HiveMQ container running",
        ok=running,
        detail="running" if running else (out.stdout.strip() or f"exit {out.returncode}"),
        hint=LOG_HINT,
    )


def _anonymous_refused(run: Runner) -> VerifyCheck:
    out = run(_probe(f"-h {BROKER_HOST} -p {BROKER_PORT} -t '{PROBE_TOPIC}' -E"))
    refused = out.returncode != 0
    return VerifyCheck(
        name="Refuses anonymous logins",
        ok=refused,
        detail="connection without a login was refused" if refused else "anonymous login accepted",
        hint=LOG_HINT,
    )


def _logins_accepted(run: Runner, passwords: BrokerPasswords) -> VerifyCheck:
    accepted = 0
    for _, username, _, password_field in ACCOUNTS:
        password = getattr(passwords, password_field)
        # Reason: the password goes in through the environment, then `sh -c`
        # expands it inside the probe — never in argv.
        out = run(
            _probe(
                f'-h {BROKER_HOST} -p {BROKER_PORT} -u {username} -P "$MQTT_PASSWORD" '
                f"-t '{PROBE_TOPIC}' -E",
                env={"MQTT_PASSWORD": password},
            )
        )
        accepted += out.returncode == 0
    total = len(ACCOUNTS)
    return VerifyCheck(
        name="Accepts each account's password",
        ok=accepted == total,
        detail=f"{accepted} of {total} logins accepted",
        hint=LOG_HINT,
    )


def _probe(mosquitto_args: str, env: dict[str, str] | None = None) -> Command:
    """A throwaway mosquitto client on the arcnode network, reaching the
    broker by its compose service name."""
    if env is None:
        return Command(
            args=["docker", "run", "--rm", "--network", DOCKER_NETWORK, PROBE_IMAGE,
                  "sh", "-c", f"mosquitto_sub {mosquitto_args}"],
        )  # fmt: skip
    return Command(
        args=["docker", "run", "--rm", "-e", "MQTT_PASSWORD", "--network", DOCKER_NETWORK,
              PROBE_IMAGE, "sh", "-c", f"mosquitto_sub {mosquitto_args}"],
        env=env,
    )  # fmt: skip
