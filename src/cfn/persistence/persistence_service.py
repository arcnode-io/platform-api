"""PersistenceService — composes Aurora + Tiger + Aura CFN resource blocks."""

from typing import Final

from src.cfn.persistence.aura_resources import aura_provisioning_resources
from src.cfn.persistence.aurora_resources import (
    PSYCOPG2_LAYER_ARN_TEMPLATE,
    aurora_cluster_resources,
)
from src.cfn.persistence.tiger_resources import tiger_provisioning_resources

DEFAULT_LAMBDA_RUNTIME: Final[str] = "python3.13"


class PersistenceService:
    """Single entry point for building the persistence section of the CFN template.

    Tunables (all default to prod-correct values):
      - lambda_runtime — LocalStack tests pass "python3.12"; LocalStack hasn't
        picked up the 3.13 runtime yet.
      - psycopg2_layer_arn_template — set to None in LocalStack tests because
        LocalStack community can't fetch shared layers from real AWS (Pro-only).
    """

    def __init__(
        self,
        *,
        lambda_runtime: str = DEFAULT_LAMBDA_RUNTIME,
        psycopg2_layer_arn_template: str | None = PSYCOPG2_LAYER_ARN_TEMPLATE,
    ) -> None:
        self._lambda_runtime = lambda_runtime
        self._psycopg2_layer_arn_template = psycopg2_layer_arn_template

    def build_resources(self) -> dict[str, dict]:
        """Return the merged Aurora + Tiger + Aura resource dict (CFN `Resources:`)."""
        return {
            **aurora_cluster_resources(
                lambda_runtime=self._lambda_runtime,
                psycopg2_layer_arn_template=self._psycopg2_layer_arn_template,
            ),
            **tiger_provisioning_resources(lambda_runtime=self._lambda_runtime),
            **aura_provisioning_resources(lambda_runtime=self._lambda_runtime),
        }
