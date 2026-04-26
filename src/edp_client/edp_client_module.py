"""EDP client module — DI assembly for `EdpClientService`."""

from src.edp_client.edp_client_service import EdpClientConfig, EdpClientService


class EdpClientModule:
    """Single point of DI for the edp-api HTTP client."""

    def __init__(self, *, edp_api_url: str) -> None:
        self.service = EdpClientService(config=EdpClientConfig(base_url=edp_api_url))
