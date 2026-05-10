"""Manifest module — DI assembly for `ManifestService`."""

from src.manifest.manifest_service import ManifestService


class ManifestModule:
    """Single point of DI for manifest composition."""

    def __init__(self) -> None:
        self.service = ManifestService()
