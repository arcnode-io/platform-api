"""Fetch the edp-module-assemblies files the manifest references, at one pinned commit.

CI runs this before the checks job, and you run it by hand before the orders
integration test. One archive download of the repo at that commit, then the
manifest and every referenced key are extracted from it. The repo's keys equal
the S3 keys. Files the repo doesn't have are reported, not faked here.
Reason: per-file raw fetches are rate-limited by GitLab (429 on the shared runner).

Usage: uv run python tests/fixtures/edp_assets.py --sha 2cfac23
"""

import argparse
import tarfile
import tempfile
import urllib.request
from collections.abc import Generator
from pathlib import Path
from typing import Final

import yaml

ARCHIVE_BASE: Final[str] = (
    "https://gitlab.com/arcnode-io/edp-module-assemblies/-/archive"
)
BUCKET: Final[str] = "arcnode-artifacts"
MANIFEST_KEY: Final[str] = "manifest.yaml"
FIXTURES_DIR: Final[Path] = Path(__file__).resolve().parent
MANIFEST_PATH: Final[Path] = FIXTURES_DIR / "edp-module-assemblies-manifest.yaml"
ASSETS_DIR: Final[Path] = FIXTURES_DIR / "edp-assets"


def referenced_keys(manifest_path: Path) -> list[str]:
    """Every S3 key under the artifacts bucket that the manifest points at."""
    manifest = yaml.safe_load(manifest_path.read_text())
    prefix = f"s3://{BUCKET}/"
    return sorted(
        {
            url.removeprefix(prefix)
            for url in walk_s3_urls(manifest)
            if url.startswith(prefix)
        }
    )


def walk_s3_urls(node: object) -> Generator[str]:
    """Yield every string starting with `s3://` in a nested dict/list."""
    if isinstance(node, str):
        if node.startswith("s3://"):
            yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from walk_s3_urls(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_s3_urls(item)


def download_archive(sha: str, dest: Path) -> None:
    """One request: the repo at `sha` as a tar.gz."""
    url = f"{ARCHIVE_BASE}/{sha}/edp-module-assemblies-{sha}.tar.gz"
    urllib.request.urlretrieve(url, dest)  # nosec B310 — fixed https host


def extract_keys(archive: Path, keys: list[str], dest: Path) -> list[str]:
    """Write each key from the archive into `dest`. Returns the keys the repo doesn't have.
    GitLab archives put everything under one top-level directory, which is dropped."""
    missing: list[str] = []
    with tarfile.open(archive) as tar:
        members = {
            m.name.split("/", 1)[1]: m
            for m in tar.getmembers()
            if m.isfile() and "/" in m.name
        }
        for key in keys:
            member = members.get(key)
            if member is None:
                missing.append(key)
                continue
            body = tar.extractfile(member)
            assert body is not None, key
            target = dest / key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body.read())
    return missing


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--sha", required=True, help="edp-module-assemblies commit to fetch from"
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "edp-module-assemblies.tar.gz"
        download_archive(args.sha, archive)
        # The manifest comes out of the same archive, then says which keys to pull.
        missing_manifest = extract_keys(archive, [MANIFEST_KEY], Path(tmp))
        assert not missing_manifest, f"no {MANIFEST_KEY} in the archive at {args.sha}"
        MANIFEST_PATH.write_bytes((Path(tmp) / MANIFEST_KEY).read_bytes())
        keys = referenced_keys(MANIFEST_PATH)
        missing = extract_keys(archive, keys, ASSETS_DIR)
    print(
        f"fetched {len(keys) - len(missing)} of {len(keys)}; not in repo: {len(missing)}"
    )
    for key in missing:
        print(f"  not in repo: {key}")


if __name__ == "__main__":
    main()
