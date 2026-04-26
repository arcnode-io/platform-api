"""CFN module — DI assembly for `CfnService`."""

from src.cfn.cfn_service import CfnService


class CfnModule:
    """Single point of DI for CFN template rendering."""

    def __init__(self) -> None:
        self.service = CfnService()
