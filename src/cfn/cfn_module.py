"""CFN module — DI assembly for `CfnService`."""

from src.cfn.cfn_service import CfnService
from src.cfn.persistence.persistence_module import PersistenceModule


class CfnModule:
    """Single point of DI for CFN template rendering."""

    def __init__(self) -> None:
        self.persistence = PersistenceModule()
        self.service = CfnService(persistence=self.persistence.service)
