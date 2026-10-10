"""Fetch the edp-module-assemblies files the manifest references, at one pinned commit.

CI runs this before the checks job, and you run it by hand before the orders
integration test. The repo's keys equal the S3 keys, so each file is one raw
GitLab URL. Files the repo doesn't have (404) are reported, not faked here.

Usage: uv run python tests/fixtures/edp_assets.py --sha df0e970
"""

import argparse
import urllib.error
import urllib.request
from collections.abc import Generator
from pathlib import Path
from typing import Final

import yaml

RAW_BASE: Final[str] = "https://gitlab.com/arcnode-io/edp-module-assemblies/-/raw"
BUCKET: Final[str] = "arcnode-artifacts"
FIXTURES_DIR: Final[Path] = Path(__file__).resolve().parent
MANIFEST_PATH: Final[Path] = FIXTURES_DIR / "edp-module-assemblies-manifest.yaml"
ASSETS_DIR: Final[Path] = FIXTURES_DIR / "edp-assets"


def referenced_keys(manifest_path: Path) -> list[str]:
    """Every S3 key under the artifacts bucket that the manifest points at."""
    manifest = yaml.safe_load(manifest_path.read_text())
    prefix = f"s3://{BUCKET}/"
    return sorted({url.removeprefix(prefix) for url in walk_s3_urls(manifest) if url.startswith(prefix)})


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


def fetch(sha: str, keys: list[str], dest: Path) -> list[str]:
    """Download each key at `sha` into `dest`. Returns the keys the repo doesn't have."""
    missing: list[str] = []
    for key in keys:
        try:
            with urllib.request.urlopen(f"{RAW_BASE}/{sha}/{key}") as resp:
                target = dest / key
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(resp.read())
        except urllib.error.HTTPError as err:
            if err.code != 404:
                raise
            missing.append(key)
    return missing


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sha", required=True, help="edp-module-assemblies commit to fetch from")
    args = parser.parse_args()
    keys = referenced_keys(MANIFEST_PATH)
    missing = fetch(args.sha, keys, ASSETS_DIR)
    print(f"fetched {len(keys) - len(missing)} of {len(keys)}; not in repo: {len(missing)}")
    for key in missing:
        print(f"  not in repo: {key}")


if __name__ == "__main__":
    main()
