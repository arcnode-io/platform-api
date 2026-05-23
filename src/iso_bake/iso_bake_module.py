"""ISO bake module — DI assembly for `IsoBakeService`."""

from src.iso_bake.iso_bake_service import IsoBakeService


class IsoBakeModule:
    """Single point of DI for ISO overlay rendering."""

    def __init__(self, iso_version: str) -> None:
        self.service = IsoBakeService(iso_version=iso_version)
