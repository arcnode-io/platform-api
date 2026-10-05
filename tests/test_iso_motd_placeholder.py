"""Integration test for arcnode-motd-ip.sh's network-wait placeholder.

Runs the real script (parsed from src/iso/setup.sh, never a copy) inside
a plain Debian container — this logic is pure shell + figlet + `ip route
get`, no systemd/apt-daemon involvement, so a container is enough; no
need for the heavier Vagrant/QEMU VM the daemon-layer test uses.

`ip` itself is faked: the race-handling behavior (the `ip monitor route`
wake-up loop, the 169.254.x.x link-local rejection) was already proven
separately via real netns reproduction during development. This test's
job is narrower — does the script show an honest "still waiting" state
instead of silence while no route exists, without adding noise once a
route already exists on the very first check.
"""

import time
from collections.abc import Callable
from pathlib import Path

from testcontainers.core.container import DockerContainer

REPO_ROOT = Path(__file__).parent.parent
SETUP_SH_TEXT = (REPO_ROOT / "src" / "iso" / "setup.sh").read_text()

FAKE_IP_SCRIPT = """#!/bin/sh
if [ "$1" = "route" ] && [ "$2" = "get" ]; then
  state=$(cat /tmp/fake-route-state 2>/dev/null || echo down)
  if [ "$state" = "up" ]; then
    addr=$(cat /tmp/fake-route-addr)
    echo "1.1.1.1 via 10.0.0.1 dev eth0 src $addr uid 0"
  fi
  exit 0
elif [ "$1" = "monitor" ]; then
  sleep 100
  exit 0
fi
exit 1
"""


def _extract_heredoc(write_target: str) -> str:
    """Pull one `cat > <write_target> <<'EOF' ... EOF` block's body out of
    the real setup.sh — the single source of truth this test checks
    against, never a copy that could silently drift from what ships."""
    marker = f"cat > {write_target} <<'EOF'\n"
    start = SETUP_SH_TEXT.index(marker) + len(marker)
    end = SETUP_SH_TEXT.index("\nEOF", start)
    return SETUP_SH_TEXT[start:end]


MOTD_IP_SCRIPT = _extract_heredoc("/usr/local/sbin/arcnode-motd-ip.sh")


def _write_file(container: DockerContainer, path: str, content: str, executable: bool = False) -> None:
    exit_code, output = container.exec(["sh", "-c", f"cat > {path} <<'TEST_EOF'\n{content}\nTEST_EOF"])
    assert exit_code == 0, output
    if executable:
        exit_code, output = container.exec(["chmod", "+x", path])
        assert exit_code == 0, output


def _reset_and_deploy(container: DockerContainer) -> None:
    """Arrange: clean slate + deploy the real script + the fake `ip`."""
    # Reason: these /tmp paths live inside a throwaway container, not the host.
    container.exec(["rm", "-f", "/etc/motd", "/var/log/arcnode-motd-ip.log",
                     "/tmp/fake-route-state", "/tmp/fake-route-addr"])  # noqa: S108
    _write_file(container, "/usr/local/bin/ip", FAKE_IP_SCRIPT, executable=True)
    _write_file(container, "/usr/local/sbin/arcnode-motd-ip.sh", MOTD_IP_SCRIPT, executable=True)


def _read_motd(container: DockerContainer) -> str:
    exit_code, output = container.exec(["cat", "/etc/motd"])
    return output.decode() if exit_code == 0 else ""


def _wait_until(container: DockerContainer, predicate: Callable[[str], bool], timeout: float = 15.0) -> str:
    """Poll /etc/motd until `predicate` matches — bounded, not a blind sleep."""
    deadline = time.monotonic() + timeout
    content = ""
    while time.monotonic() < deadline:
        content = _read_motd(container)
        if predicate(content):
            return content
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for motd condition; last content: {content!r}")


def _start_container() -> DockerContainer:
    container = DockerContainer("debian:trixie-slim").with_command("sleep infinity")
    container.start()
    exit_code, output = container.exec(
        ["sh", "-c", "apt-get update && apt-get install -y iproute2 figlet coreutils"]
    )
    assert exit_code == 0, output
    return container


def test_shows_waiting_placeholder_before_route_then_final_banner_once_ready() -> None:
    """Arrange: no route exists yet. Act: start the script, observe the
    placeholder, then make a route appear. Assert: motd shows an honest
    'waiting for network' state first, then the real URL once ready."""
    container = _start_container()
    try:
        _reset_and_deploy(container)
        container.exec(["sh", "-c", "echo down > /tmp/fake-route-state"])

        container.exec(["sh", "-c", "nohup /usr/local/sbin/arcnode-motd-ip.sh >/tmp/out.log 2>&1 &"])

        waiting_motd = _wait_until(container, lambda c: "waiting for network" in c, timeout=10.0)
        assert "/var/log/arcnode-motd-ip.log" in waiting_motd
        assert "http://" not in waiting_motd

        container.exec(["sh", "-c", "echo 10.0.0.55 > /tmp/fake-route-addr && echo up > /tmp/fake-route-state"])

        final_motd = _wait_until(container, lambda c: "http://" in c, timeout=15.0)
        assert "http://10.0.0.55:8080/setup" in final_motd
    finally:
        container.stop()


def test_skips_placeholder_when_route_already_exists() -> None:
    """Arrange: a route already exists on the very first check (the
    common/fast case). Act: run the script. Assert: motd goes straight
    to the final banner — the placeholder must never appear, so the
    common case stays exactly as quiet as it always was."""
    container = _start_container()
    try:
        _reset_and_deploy(container)
        container.exec(["sh", "-c", "echo 10.0.0.77 > /tmp/fake-route-addr && echo up > /tmp/fake-route-state"])

        exit_code, output = container.exec(["/usr/local/sbin/arcnode-motd-ip.sh"])
        assert exit_code == 0, output

        final_motd = _read_motd(container)
        assert "http://10.0.0.77:8080/setup" in final_motd
        assert "waiting for network" not in final_motd
    finally:
        container.stop()
