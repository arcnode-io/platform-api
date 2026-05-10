"""Portal module — DI assembly for `PortalService`."""

from src.portal.portal_service import PortalService


class PortalModule:
    """Single point of DI for portal HTML rendering."""

    def __init__(self) -> None:
        self.service = PortalService()
