"""EDP client module — DI assembly for `EdpClientService`."""

from src.edp_client.edp_client_service import EdpClientService


class EdpClientModule:
    """Single point of DI for the edp-api HTTP client."""

    def __init__(self, *, edp_api_url: str) -> None:
        self.service = EdpClientService(base_url=edp_api_url)
