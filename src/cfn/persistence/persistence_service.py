"""PersistenceService — composes Aurora + Tiger + Aura CFN resource blocks."""


class PersistenceService:
    """Single entry point for building the persistence section of the CFN template."""

    def build_resources(self) -> dict[str, object]:
        """Return the merged Aurora + Tiger + Aura resource dict (CFN `Resources:`)."""
        return {}
