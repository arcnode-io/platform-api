"""Unit tests for the one-archive fixture fetch (no network)."""

import io
import tarfile
from pathlib import Path

from tests.fixtures.edp_assets import extract_keys

TOP: str = "edp-module-assemblies-2cfac23-deadbeef"


def _archive(path: Path, files: dict[str, bytes]) -> Path:
    """A GitLab-style tar.gz: every entry under one top-level directory."""
    with tarfile.open(path, "w:gz") as tar:
        for name, body in files.items():
            info = tarfile.TarInfo(f"{TOP}/{name}")
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    return path


def test_extract_keys_writes_each_key_and_reports_the_missing_ones(
    tmp_path: Path,
) -> None:
    # Arrange
    archive = _archive(
        tmp_path / "a.tar.gz",
        {"manifest.yaml": b"m: 1\n", "step/compute.step": b"STEP"},
    )
    dest = tmp_path / "assets"

    # Act
    missing = extract_keys(archive, ["step/compute.step", "step/absent.step"], dest)

    # Assert
    assert (dest / "step" / "compute.step").read_bytes() == b"STEP"
    assert missing == ["step/absent.step"]
