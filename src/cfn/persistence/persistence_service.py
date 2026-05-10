"""PersistenceService — composes Aurora + Tiger + Aura CFN resource blocks."""

from src.cfn.persistence.aura_resources import aura_provisioning_resources
from src.cfn.persistence.aurora_resources import aurora_cluster_resources
from src.cfn.persistence.tiger_resources import tiger_provisioning_resources


class PersistenceService:
    """Single entry point for building the persistence section of the CFN template."""

    def build_resources(self) -> dict[str, object]:
        """Return the merged Aurora + Tiger + Aura resource dict (CFN `Resources:`)."""
        return {
            **aurora_cluster_resources(),
            **tiger_provisioning_resources(),
            **aura_provisioning_resources(),
        }
