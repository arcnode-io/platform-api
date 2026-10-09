"""Playbook-style verification for the Docker page. Docker picks the
arcnode network's address range; everything downstream reads it from
`docker network inspect`, never from a copy."""

from ipaddress import IPv4Address, IPv4Network, ip_address
from typing import Final

from src.wizard.system_runner import Runner
from src.wizard.wizard_record import (
    Command,
    CommandOutput,
    DockerNetwork,
    VerifyCheck,
)

# The network every EMS container and host daemon meets on.
DOCKER_NETWORK: Final[str] = "arcnode"
# Pinned so the check is the same on every box.
PROBE_IMAGE: Final[str] = "busybox:1.37"
JOURNAL_HINT: Final[str] = "sudo journalctl -u docker -n 50"


def inspect_network(run: Runner) -> CommandOutput:
    """`<subnet> <gateway>` of the arcnode network, e.g.
    `172.23.0.0/16 172.23.0.1`; non-zero exit when it doesn't exist."""
    return run(
        Command(
            args=[
                "docker",
                "network",
                "inspect",
                DOCKER_NETWORK,
                "-f",
                "{{range .IPAM.Config}}{{.Subnet}} {{.Gateway}}{{end}}",
            ]
        )
    )


def read_network(run: Runner) -> DockerNetwork | None:
    """The arcnode network's range + gateway, or None if it doesn't exist."""
    out = inspect_network(run)
    if out.returncode != 0:
        return None
    subnet, gateway = out.stdout.split()
    return DockerNetwork(subnet=IPv4Network(subnet), gateway=IPv4Address(gateway))


def missing_network_check() -> VerifyCheck:
    """The one row a later daemon page shows when the Docker page hasn't
    made the network it trusts."""
    return VerifyCheck(
        name="Docker's arcnode network",
        ok=False,
        detail="not found — this page trusts the range Docker gives that network",
        hint="Finish the Docker page first; sudo docker network ls",
    )


def verify_docker(run: Runner) -> list[VerifyCheck]:
    """Daemon running → arcnode network exists → a container joins it."""
    network = inspect_network(run)
    subnet = IPv4Network(network.stdout.split()[0]) if network.returncode == 0 else None
    return [
        _daemon_running(run),
        _network(network),
        _container_joins(run, subnet),
    ]


def _daemon_running(run: Runner) -> VerifyCheck:
    out = run(Command(args=["systemctl", "is-active", "docker"]))
    state = out.stdout.strip() or f"exit {out.returncode}"
    return VerifyCheck(
        name="Docker daemon running",
        ok=state == "active",
        detail=state,
        hint=f"sudo systemctl status docker; {JOURNAL_HINT}",
    )


def _network(network: CommandOutput) -> VerifyCheck:
    if network.returncode == 0:
        subnet, gateway = network.stdout.split()
        detail = f"{subnet}, gateway {gateway}"
    else:
        detail = network.stdout.strip() or f"exit {network.returncode}"
    return VerifyCheck(
        name=f"{DOCKER_NETWORK} network",
        ok=network.returncode == 0,
        detail=detail,
        hint=f"sudo docker network ls; {JOURNAL_HINT}",
    )


def _container_joins(run: Runner, subnet: IPv4Network | None) -> VerifyCheck:
    name = "A container joins the network"
    if subnet is None:
        return VerifyCheck(
            name=name,
            ok=False,
            detail=f"no {DOCKER_NETWORK} network to join",
            hint="sudo docker network ls",
        )
    # Reason: proves the whole path the EMS containers need — pull an
    # image, start it, attach it to arcnode — not just that dockerd is up.
    out = run(
        Command(
            args=[
                "docker",
                "run",
                "--rm",
                "--network",
                DOCKER_NETWORK,
                PROBE_IMAGE,
                "ip",
                "-4",
                "-o",
                "addr",
                "show",
                "eth0",
            ]
        )
    )
    if out.returncode != 0:
        return VerifyCheck(
            name=name,
            ok=False,
            detail=out.stdout.strip() or f"exit {out.returncode}",
            hint=f"sudo docker pull {PROBE_IMAGE}; getent hosts registry-1.docker.io",
        )
    # "2: eth0    inet 172.23.0.2/16 brd ..." → 172.23.0.2. A first run
    # prints the image pull's progress above it, so find the inet line.
    inet = next(line for line in out.stdout.splitlines() if " inet " in line)
    address = ip_address(inet.split()[3].split("/")[0])
    inside = address in subnet
    return VerifyCheck(
        name=name,
        ok=inside,
        detail=f"{PROBE_IMAGE} got {address} "
        + (f"(inside {subnet})" if inside else f"— outside {subnet}"),
        hint=f"sudo docker network inspect {DOCKER_NETWORK}",
    )
