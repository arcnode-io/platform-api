"""ISO helpers for integration tests — a tiny real ISO in place of the
800 MB base ISO. The bake only remaps files in it, so its size doesn't
change what's tested."""

import subprocess  # nosec B404 — xorriso, fixed args
from pathlib import Path

import boto3

BASE_ISO_KEY = "iso/arcnode-ems-amd64.iso"


def xorriso(*args: str) -> None:
    """Run the real xorriso; raise on failure."""
    subprocess.run(  # noqa: S603  # nosec B603 — fixed args
        ["xorriso", *args],  # noqa: S607
        check=True,
        capture_output=True,
    )


def tiny_base_iso(tmp_path: Path) -> Path:
    """An ISO with a preseed.cfg in it — something the bake must keep."""
    src = tmp_path / "base-src"
    src.mkdir()
    (src / "preseed.cfg").write_text("d-i preseed/late_command string true\n")
    iso = tmp_path / "base.iso"
    xorriso("-as", "mkisofs", "-quiet", "-V", "ARCNODE", "-o", str(iso), str(src))
    return iso


def seed_base_iso(localstack_url: str, bucket: str, tmp_path: Path) -> str:
    """Put a tiny base ISO where CI publishes the real one; return its URL."""
    s3 = boto3.client(
        "s3",
        endpoint_url=localstack_url,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    s3.create_bucket(Bucket=bucket)
    s3.upload_file(str(tiny_base_iso(tmp_path)), bucket, BASE_ISO_KEY)
    return f"{localstack_url}/{bucket}/{BASE_ISO_KEY}"


def extract(iso: Path, out: Path, *paths: str) -> None:
    """Pull files/dirs out of an ISO, keeping their ISO paths under `out`."""
    pairs = [arg for p in paths for arg in ("-extract", p, str(out / p.lstrip("/")))]
    xorriso("-osirrox", "on", "-indev", str(iso), *pairs)
