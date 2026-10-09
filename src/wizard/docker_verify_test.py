"""Unit tests for the Docker page's checks — every failure mode gets its
own console command."""

from src.wizard.docker_verify import verify_docker
from src.wizard.wizard_fixtures import FakeRunner, ok
from src.wizard.wizard_record import CommandOutput


def test_a_healthy_docker_reports_the_range_it_picked() -> None:
    # Arrange
    runner = FakeRunner()

    # Act
    actual = verify_docker(runner)

    # Assert
    assert [(c.name, c.ok, c.detail) for c in actual] == [
        ("Docker daemon running", True, "active"),
        ("arcnode network", True, "172.23.0.0/16, gateway 172.23.0.1"),
        (
            "A container joins the network",
            True,
            "busybox:1.37 got 172.23.0.2 (inside 172.23.0.0/16)",
        ),
    ]


def test_a_stopped_daemon_points_at_its_journal() -> None:
    # Arrange
    runner = FakeRunner()
    runner.queries["is-active docker"] = CommandOutput(returncode=3, stdout="failed\n")

    # Act
    daemon = verify_docker(runner)[0]

    # Assert
    assert (daemon.ok, daemon.detail) == (False, "failed")
    assert (
        daemon.hint == "sudo systemctl status docker; sudo journalctl -u docker -n 50"
    )


def test_a_missing_network_skips_the_container_check() -> None:
    # Arrange
    runner = FakeRunner()
    runner.queries["network inspect"] = CommandOutput(
        returncode=1, stdout="Error response from daemon: network arcnode not found\n"
    )

    # Act
    network, container = verify_docker(runner)[1:]

    # Assert
    assert (network.ok, network.detail) == (
        False,
        "Error response from daemon: network arcnode not found",
    )
    assert (container.ok, container.detail) == (False, "no arcnode network to join")
    assert not [c for c in runner.calls if "run" in c.args]


def test_a_failed_image_pull_says_why() -> None:
    # Arrange: no route to Docker Hub
    runner = FakeRunner()
    runner.queries["run --rm"] = CommandOutput(
        returncode=125,
        stdout="docker: Error response from daemon: Get "
        '"https://registry-1.docker.io/v2/": dial tcp: lookup registry-1.docker.io: '
        "no such host\n",
    )

    # Act
    container = verify_docker(runner)[2]

    # Assert
    assert container.ok is False
    assert container.detail.endswith("no such host")
    assert container.hint == (
        "sudo docker pull busybox:1.37; getent hosts registry-1.docker.io"
    )


def test_an_address_outside_the_range_fails() -> None:
    # Arrange
    runner = FakeRunner()
    runner.queries["run --rm"] = ok(
        "2: eth0    inet 10.9.0.2/24 brd 10.9.0.255 scope global eth0\n"
    )

    # Act
    container = verify_docker(runner)[2]

    # Assert
    assert (container.ok, container.detail) == (
        False,
        "busybox:1.37 got 10.9.0.2 — outside 172.23.0.0/16",
    )


def test_first_run_pull_progress_doesnt_break_the_check() -> None:
    # Arrange: what `docker run` prints when the image isn't local yet
    runner = FakeRunner()
    runner.queries["run --rm"] = ok(
        "Unable to find image 'busybox:1.37' locally\n"
        "1.37: Pulling from library/busybox\n"
        "Status: Downloaded newer image for busybox:1.37\n"
        "2: eth0    inet 172.23.0.2/16 brd 172.23.255.255 scope global eth0\n"
    )

    # Act
    container = verify_docker(runner)[2]

    # Assert
    assert (container.ok, container.detail) == (
        True,
        "busybox:1.37 got 172.23.0.2 (inside 172.23.0.0/16)",
    )
