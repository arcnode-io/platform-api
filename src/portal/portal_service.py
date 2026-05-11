"""PortalService — renders the per-customer delivery portal.

Jinja2-templated. Output is a static HTML string that the orchestrator
uploads to S3 alongside the `manifest.json` artifact.

Single template (`templates/portal.html`) with the SOVEREIGN dark theme
inlined as `<style>`. SOLARPUNK light theme is a future commit.

The DeploymentManifest is the entire input contract; everything operator-facing
flows from its fields. See `src/manifest/manifest_record.py` for the shape.
"""

import json
from pathlib import Path
from typing import Final

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.manifest.artifact_metadata import SECTION_LABEL
from src.manifest.manifest_record import DeploymentManifest, ManifestSection

TEMPLATE_DIR: Final[Path] = Path(__file__).parent / "templates"
TEMPLATE_NAME: Final[str] = "portal.html"


def _filesize(n: int) -> str:
    """Format bytes as '38.4 MB' / '566 B' / '2.46 GB' (mockup-matching scale).

    Decimal (1000) base — matches modern OS file managers (macOS Finder,
    Windows Explorer post-Win11) and the mockup's hand-picked values. We
    deliberately don't use binary (1024) prefixes; operator-facing copy
    follows operator-facing conventions, not bit-twiddling tradition.
    """
    if n < 1000:
        return f"{n} B"
    units = ("KB", "MB", "GB", "TB")
    val = float(n)
    idx = -1
    while val >= 1000 and idx < len(units) - 1:
        val /= 1000
        idx += 1
    # 2 decimals at GB+ for design fidelity (mockup: "2.46 GB"); 1 below.
    return f"{val:.2f} {units[idx]}" if idx >= 2 else f"{val:.1f} {units[idx]}"


def _split_curl_url(url: str) -> tuple[str, str]:
    """Split URL into (prefix-with-trailing-slash, filename) for chip-coloring."""
    if "/" not in url:
        return "", url
    prefix, _, filename = url.rpartition("/")
    return f"{prefix}/", filename


_SECTION_NUMBERS: Final[dict[ManifestSection, str]] = {
    ManifestSection.SYSTEM_IMAGES: "01",
    ManifestSection.ENGINEERING_DRAWINGS: "02",
    ManifestSection.MANIFESTS_AND_SCHEDULES: "03",
}

_SECTION_RENDER_ORDER: Final[tuple[ManifestSection, ...]] = (
    ManifestSection.SYSTEM_IMAGES,
    ManifestSection.ENGINEERING_DRAWINGS,
    ManifestSection.MANIFESTS_AND_SCHEDULES,
)


class PortalService:
    """Renders the delivery portal HTML + matching manifest.json."""

    def __init__(self) -> None:
        self._env = Environment(
            loader=FileSystemLoader(TEMPLATE_DIR),
            autoescape=select_autoescape(["html"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._env.filters["filesize"] = _filesize

    def render(self, *, manifest: DeploymentManifest) -> str:
        """Render the portal HTML page (uploaded to S3 as `index.html`)."""
        section_specs = [
            {
                "key": s,
                "num": _SECTION_NUMBERS[s],
                "label": SECTION_LABEL[s],
            }
            for s in _SECTION_RENDER_ORDER
        ]
        curl_prefix, curl_filename = _split_curl_url(manifest.bundle_curl_url or "")
        template = self._env.get_template(TEMPLATE_NAME)
        return template.render(
            manifest=manifest,
            section_specs=section_specs,
            curl_prefix=curl_prefix,
            curl_filename=curl_filename,
        )

    def render_manifest_json(self, *, manifest: DeploymentManifest) -> str:
        """Serialize the manifest as the `manifest.json` artifact (pretty JSON)."""
        return json.dumps(
            manifest.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
        )
