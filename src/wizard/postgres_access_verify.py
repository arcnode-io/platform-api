"""The PostgreSQL page's network-facing checks: it listens where the
containers can reach it, pg_hba lets in only loopback + the range Docker
picked, and a real container on that network connects."""

from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from typing import Final

from src.wizard.docker_verify import DOCKER_NETWORK
from src.wizard.system_runner import Runner
from src.wizard.wizard_record import Command, DockerNetwork, VerifyCheck

PG_LOG_HINT: Final[str] = "sudo tail -n 50 /var/log/postgresql/postgresql-17-main.log"
# Pinned major, same client the EMS images speak.
PROBE_IMAGE: Final[str] = "postgres:17-alpine"
PROBE_DATABASE: Final[str] = "ems_document"


def _psql(sql: str) -> Command:
    # Reason: a local copy, not postgres_verify.psql_as_postgres — that
    # module imports this one.
    return Command(
        args=["runuser", "-u", "postgres", "--", "psql", "-d", "postgres", "-tAc", sql]
    )


def verify_access(
    run: Runner, password: str, network: DockerNetwork
) -> list[VerifyCheck]:
    """Listen addresses → pg_hba → a real container connects."""
    return [
        _listens(run, network),
        _hba(run, network),
        _container_connects(run, password, network),
    ]


def _listens(run: Runner, network: DockerNetwork) -> VerifyCheck:
    expected = f"localhost,{network.gateway}"
    listen = run(_psql("SHOW listen_addresses")).stdout.strip()
    return VerifyCheck(
        name="Listens on localhost + Docker's gateway",
        ok=listen == expected,
        detail=listen if listen == expected else f"{listen or '?'} (want {expected})",
        hint="sudo cat /etc/postgresql/17/main/conf.d/arcnode.conf; "
        "sudo ss -ltnp | grep 5432",
    )


def _hba(run: Runner, network: DockerNetwork) -> VerifyCheck:
    rules_out = run(
        _psql(
            "SELECT coalesce(address, '') || '|' || coalesce(netmask, '') "
            "FROM pg_hba_file_rules WHERE type = 'host'"
        )
    )
    nets: list[IPv4Network | IPv6Network] = []
    outside: list[str] = []
    for line in dict.fromkeys(rules_out.stdout.split()):  # replication rules repeat
        address, _, netmask = line.partition("|")
        if not netmask:  # keywords like 'all' / 'samenet' — not a bounded range
            outside.append(address)
            continue
        # Reason: ipaddress takes "1.2.3.0/255.255.255.0" but not an IPv6
        # mask written out that way — a prefix length works for both.
        prefix = bin(int(ip_address(netmask))).count("1")
        net = ip_network(f"{address}/{prefix}", strict=False)
        nets.append(net)
        if not (net.is_loopback or net == network.subnet):
            outside.append(str(net))
    detail = f"host rules {', '.join(str(net) for net in nets)}"
    if outside:
        detail += f" — {', '.join(outside)} is outside Docker's {network.subnet}"
    return VerifyCheck(
        name="Accepts only loopback + Docker's range",
        ok=network.subnet in nets and not outside,
        detail=detail,
        hint="sudo cat /etc/postgresql/17/main/pg_hba.conf "
        "/etc/postgresql/17/main/pg_hba.d/arcnode.conf",
    )


def _container_connects(
    run: Runner, password: str, network: DockerNetwork
) -> VerifyCheck:
    # Reason: the path the EMS containers take — from the arcnode network to
    # the gateway, with the password. `-e PGPASSWORD` (no value) passes it
    # from this process's env, so it never lands in argv.
    out = run(
        Command(
            args=[
                "docker",
                "run",
                "--rm",
                "--network",
                DOCKER_NETWORK,
                "-e",
                "PGPASSWORD",
                PROBE_IMAGE,
                "psql",
                "-h",
                str(network.gateway),
                "-U",
                "postgres",
                "-d",
                PROBE_DATABASE,
                "-tAc",
                "SELECT inet_client_addr()",
            ],
            env={"PGPASSWORD": password},
        )
    )
    lines = out.stdout.strip().splitlines() or [f"exit {out.returncode}"]
    # A first run prints the image pull above the answer; a failure's cause
    # is on psql's/docker's own error line, not the hint line under it.
    last = lines[-1]
    ok = out.returncode == 0 and ip_address(last) in network.subnet
    errors = [line for line in lines if line.startswith(("psql:", "docker:"))]
    return VerifyCheck(
        name="A container on the arcnode network connects",
        ok=ok,
        detail=(
            f"{PROBE_IMAGE} at {last} → {network.gateway}:5432/{PROBE_DATABASE}"
            if ok
            else (errors or [last])[0]
        ),
        hint=f"sudo ss -ltnp | grep 5432; {PG_LOG_HINT}",
    )
