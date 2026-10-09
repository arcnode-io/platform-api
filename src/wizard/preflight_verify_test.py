"""Unit tests for the hardware check — every failure mode blocks, with a
console command that debugs it."""

from src.wizard.preflight_verify import verify_hardware
from src.wizard.wizard_fixtures import FakeRunner, ok
from src.wizard.wizard_record import CommandOutput, HardwareMinimums

# What setup.sh writes into wizard-cfg.yml — g6e.2xlarge class.
PRODUCTION = HardwareMinimums(
    vcpus=8, memory_gib=64, gpus=1, gpu_memory_gb=48, disk_gb=1000
)


def _g6e_2xlarge() -> FakeRunner:
    """FakeRunner's healthy defaults are a g6e.2xlarge."""
    return FakeRunner()


def test_a_g6e_2xlarge_passes_production() -> None:
    # Arrange
    runner = _g6e_2xlarge()

    # Act
    actual = verify_hardware(runner, PRODUCTION)

    # Assert
    assert [(c.name, c.ok) for c in actual] == [
        ("vCPUs", True),
        ("Memory", True),
        ("NVIDIA GPU", True),
        ("GPU memory", True),
        ("Data disk", True),
    ]
    assert (
        actual[1].detail == "61.8 GiB (need ≥ 64 GiB, 10% allowed for kernel reserve)"
    )
    assert actual[3].detail == "45.0 GiB total (need ≥ 48 GB)"
    assert actual[4].detail == "NVMe, 1000 GB (need NVMe ≥ 1000 GB)"


def test_no_nvidia_gpu_blocks() -> None:
    # Arrange
    runner = _g6e_2xlarge()
    runner.outputs["lspci"] = ok(
        "00:02.0 VGA compatible controller [0300]: Intel Corporation UHD 630\n"
    )

    # Act
    gpu = verify_hardware(runner, PRODUCTION)[2]

    # Assert
    assert (gpu.ok, gpu.detail) == (False, "none found (need ≥ 1)")
    assert gpu.hint == "lspci | grep -iE 'vga|3d'"


def test_gpu_without_a_loaded_driver_blocks_and_points_at_secure_boot() -> None:
    # Arrange: card present, nvidia-smi can't talk to it (module not loaded)
    runner = _g6e_2xlarge()
    runner.outputs["nvidia-smi"] = CommandOutput(
        returncode=9,
        stdout="NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.\n",
    )

    # Act
    memory = verify_hardware(runner, PRODUCTION)[3]

    # Assert
    assert (memory.ok, memory.detail) == (
        False,
        "NVIDIA driver not loaded: NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.",
    )
    assert memory.hint == "nvidia-smi; lsmod | grep nvidia; mokutil --sb-state"


def test_spinning_disk_blocks() -> None:
    # Arrange
    runner = _g6e_2xlarge()
    runner.outputs["findmnt"] = ok("/dev/sda2 1000202273280\n")
    runner.outputs["lsblk"] = ok("part \ndisk sata\n")

    # Act
    disk = verify_hardware(runner, PRODUCTION)[4]

    # Assert
    assert (disk.ok, disk.detail) == (False, "SATA, 1000 GB (need NVMe ≥ 1000 GB)")


def test_too_little_memory_blocks() -> None:
    # Arrange: a 32 GiB box
    runner = _g6e_2xlarge()
    runner.outputs["grep"] = ok("MemTotal:       32767884 kB\n")

    # Act
    memory = verify_hardware(runner, PRODUCTION)[1]

    # Assert
    assert memory.ok is False
    assert memory.hint == "free -h"


def test_btrfs_subvolume_source_is_resolved_to_its_device() -> None:
    # Arrange
    runner = _g6e_2xlarge()
    runner.outputs["findmnt"] = ok("/dev/nvme0n1p3[/@] 1000202273280\n")

    # Act
    verify_hardware(runner, PRODUCTION)

    # Assert
    actual = [c.args for c in runner.calls if c.args[0] == "lsblk"]
    assert actual == [["lsblk", "-lsno", "TYPE,TRAN", "/dev/nvme0n1p3"]]


def test_a_zero_gpu_minimum_lets_a_box_without_one_through() -> None:
    # Arrange: wizard-cfg.yml edited on the box for a one-off manual test
    runner = _g6e_2xlarge()
    runner.outputs["lspci"] = ok(
        "00:02.0 VGA compatible controller [0300]: Intel UHD 630\n"
    )
    runner.outputs["nvidia-smi"] = CommandOutput(
        returncode=6, stdout="No devices were found\n"
    )
    no_gpu = PRODUCTION.model_copy(update={"gpus": 0, "gpu_memory_gb": 0})

    # Act
    actual = verify_hardware(runner, no_gpu)

    # Assert
    assert [(c.name, c.ok, c.detail) for c in actual[2:4]] == [
        ("NVIDIA GPU", True, "none found (need ≥ 0)"),
        ("GPU memory", True, "no NVIDIA GPU to measure (need ≥ 0 GB)"),
    ]


def test_too_little_vram_points_at_the_cards_not_the_driver() -> None:
    # Arrange: 2x RTX 3060, driver fine
    runner = _g6e_2xlarge()
    runner.outputs["nvidia-smi"] = ok("12288\n12288\n")

    # Act
    memory = verify_hardware(runner, PRODUCTION)[3]

    # Assert
    assert (memory.ok, memory.detail) == (False, "24.0 GiB total (need ≥ 48 GB)")
    assert memory.hint == "nvidia-smi --query-gpu=name,memory.total --format=csv"


def test_no_gpu_doesnt_blame_the_driver() -> None:
    # Arrange
    runner = _g6e_2xlarge()
    runner.outputs["lspci"] = ok(
        "00:02.0 VGA compatible controller [0300]: Intel UHD 630\n"
    )
    runner.outputs["nvidia-smi"] = CommandOutput(
        returncode=6, stdout="No devices were found\n"
    )

    # Act
    memory = verify_hardware(runner, PRODUCTION)[3]

    # Assert
    assert (memory.ok, memory.detail) == (
        False,
        "no NVIDIA GPU to measure (need ≥ 48 GB)",
    )


def test_missing_nvidia_smi_points_at_the_install_log() -> None:
    # Arrange: the install-time NVIDIA phase never ran or failed
    runner = _g6e_2xlarge()
    runner.outputs["nvidia-smi"] = CommandOutput(returncode=127, stdout="")

    # Act
    memory = verify_hardware(runner, PRODUCTION)[3]

    # Assert
    assert (memory.ok, memory.detail) == (False, "NVIDIA driver isn't installed")
    assert memory.hint == (
        "dpkg -l nvidia-driver-cuda nvidia-kernel-open-dkms; "
        "grep -i nvidia /var/log/arcnode-late-command.log"
    )
