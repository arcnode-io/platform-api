"""The hardware check — the wizard's first page and the root of the
dependency graph. The minimums come from wizard-cfg.yml (production: 1 GPU,
NVMe; test-mode.sh lowers them for under-spec test boxes)."""

from typing import Final

from src.wizard.system_runner import Runner
from src.wizard.wizard_record import Command, HardwareMinimums, VerifyCheck

GIB: Final[int] = 1024**3
GB: Final[int] = 1000**3
# Reason: a "64 GiB" box reports ~61.8 GiB in MemTotal (kernel + firmware
# reserve), so demanding the full number would fail every real 64 GiB box.
MEMORY_RESERVE: Final[float] = 0.10
NVIDIA_VENDOR_ID: Final[str] = "[10de:"
# Postgres, Docker and Ollama all keep their data under here.
DATA_DIR: Final[str] = "/var/lib"
# What run_system_command returns for a binary that isn't on PATH.
COMMAND_NOT_FOUND: Final[int] = 127
TRANSPORT_LABELS: Final[dict[str, str]] = {"nvme": "NVMe", "": "unknown transport"}


def verify_hardware(run: Runner, minimums: HardwareMinimums) -> list[VerifyCheck]:
    """vCPUs → memory → NVIDIA GPU → GPU memory → NVMe data disk."""
    gpus = _nvidia_gpus(run)
    return [
        _vcpus(run, minimums),
        _memory(run, minimums),
        _nvidia_gpu(gpus, minimums),
        _gpu_memory(run, minimums, gpu_found=bool(gpus)),
        _data_disk(run, minimums),
    ]


def _vcpus(run: Runner, minimums: HardwareMinimums) -> VerifyCheck:
    count = int(run(Command(args=["nproc"])).stdout.strip())
    return VerifyCheck(
        name="vCPUs",
        ok=count >= minimums.vcpus,
        detail=f"{count} (need ≥ {minimums.vcpus})",
        hint="nproc; lscpu",
    )


def _memory(run: Runner, minimums: HardwareMinimums) -> VerifyCheck:
    # "MemTotal:       64815992 kB"
    line = run(Command(args=["grep", "MemTotal", "/proc/meminfo"])).stdout
    gib = int(line.split()[1]) * 1024 / GIB
    return VerifyCheck(
        name="Memory",
        ok=gib >= minimums.memory_gib * (1 - MEMORY_RESERVE),
        detail=f"{gib:.1f} GiB (need ≥ {minimums.memory_gib} GiB, "
        f"{MEMORY_RESERVE:.0%} allowed for kernel reserve)",
        hint="free -h",
    )


def _nvidia_gpus(run: Runner) -> list[str]:
    """Every NVIDIA device on the PCI bus — by vendor id, not marketing name."""
    lines = run(Command(args=["lspci", "-nn"])).stdout.splitlines()
    return [line.split(": ", 1)[-1] for line in lines if NVIDIA_VENDOR_ID in line]


def _nvidia_gpu(gpus: list[str], minimums: HardwareMinimums) -> VerifyCheck:
    found = f"{len(gpus)}x {gpus[0]}" if gpus else "none found"
    return VerifyCheck(
        name="NVIDIA GPU",
        ok=len(gpus) >= minimums.gpus,
        detail=f"{found} (need ≥ {minimums.gpus})",
        hint="lspci | grep -iE 'vga|3d'",
    )


def _gpu_memory(
    run: Runner, minimums: HardwareMinimums, *, gpu_found: bool
) -> VerifyCheck:
    if not gpu_found:
        # The row above already says why; don't blame the driver for it.
        return VerifyCheck(
            name="GPU memory",
            ok=minimums.gpu_memory_gb == 0,
            detail=f"no NVIDIA GPU to measure (need ≥ {minimums.gpu_memory_gb} GB)",
            hint="lspci | grep -iE 'vga|3d'",
        )
    out = run(
        Command(
            args=[
                "nvidia-smi",
                "--query-gpu=memory.total",
                "--format=csv,noheader,nounits",
            ]
        )
    )
    if out.returncode == COMMAND_NOT_FOUND:
        return VerifyCheck(
            name="GPU memory",
            ok=False,
            detail="NVIDIA driver isn't installed",
            hint="dpkg -l nvidia-driver-cuda nvidia-kernel-open-dkms; "
            "grep -i nvidia /var/log/arcnode-late-command.log",
        )
    if out.returncode != 0:
        first_line = (out.stdout.strip().splitlines() or [f"exit {out.returncode}"])[0]
        return VerifyCheck(
            name="GPU memory",
            ok=False,
            detail=f"NVIDIA driver not loaded: {first_line}",
            # Usual cause on a fresh box: Secure Boot refusing the DKMS module.
            hint="nvidia-smi; lsmod | grep nvidia; mokutil --sb-state",
        )
    # One MiB figure per GPU; VRAM is specced as the total, like EC2 does.
    total = sum(int(mib) for mib in out.stdout.split()) * 1024**2
    return VerifyCheck(
        name="GPU memory",
        ok=total >= minimums.gpu_memory_gb * GB,
        detail=f"{total / GIB:.1f} GiB total (need ≥ {minimums.gpu_memory_gb} GB)",
        hint="nvidia-smi --query-gpu=name,memory.total --format=csv",
    )


def _data_disk(run: Runner, minimums: HardwareMinimums) -> VerifyCheck:
    # "/dev/nvme1n1p1 1000202273280"
    source, size = run(
        Command(args=["findmnt", "-bno", "SOURCE,SIZE", "--target", DATA_DIR])
    ).stdout.split()
    # btrfs subvolumes come back as "/dev/nvme0n1p3[/@]".
    device = source.split("[")[0]
    # -s walks partition → (lvm/crypt) → disk; -l drops the tree glyphs.
    tree = run(Command(args=["lsblk", "-lsno", "TYPE,TRAN", device])).stdout
    disk_rows = [row.split() for row in tree.splitlines() if row.startswith("disk")]
    transport = disk_rows[0][1] if disk_rows and len(disk_rows[0]) > 1 else ""
    label = TRANSPORT_LABELS.get(transport, transport.upper())
    gb = int(size) // GB
    nvme_ok = transport == "nvme" or not minimums.disk_nvme
    need = "NVMe " if minimums.disk_nvme else ""
    return VerifyCheck(
        name="Data disk",
        ok=nvme_ok and int(size) >= minimums.disk_gb * GB,
        detail=f"{label}, {gb} GB (need {need}≥ {minimums.disk_gb} GB)",
        hint=f"findmnt --target {DATA_DIR}; lsblk -o NAME,TRAN,ROTA,SIZE",
    )
