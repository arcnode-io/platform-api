"""CFN module — DI assembly for `CfnService`."""

from src.cfn.cfn_service import CfnService


class CfnModule:
    """Single point of DI for CFN template rendering + deep-link construction."""

    def __init__(self, *, region: str) -> None:
        self.service = CfnService(region=region)
