"""Sizing module — DI assembly for the /sizing/preview proxy."""

from src.sizing.sizing_controller import SizingController
from src.sizing.sizing_service import SizingService


class SizingModule:
    """Single point of DI for the sizing-preview proxy."""

    def __init__(self, *, edp_api_url: str) -> None:
        self.service = SizingService(base_url=edp_api_url)
        self.router = SizingController(service=self.service).router
