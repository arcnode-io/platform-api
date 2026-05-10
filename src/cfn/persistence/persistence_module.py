"""Persistence module — DI assembly for `PersistenceService`."""

from src.cfn.persistence.persistence_service import PersistenceService


class PersistenceModule:
    """Single point of DI for persistence resource composition."""

    def __init__(self) -> None:
        self.service = PersistenceService()
