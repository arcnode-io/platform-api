"""PersistenceService — composes Aurora + variant-specific CFN resource blocks.

Variant comes from the order's DeploymentContext:
  - COMMERCIAL → Aurora (doc + vector) + Tiger/Aura URLs as customer-supplied
    CFN params, stored as CFN-native Secrets Manager secrets.
  - SOVEREIGN_GOVERNMENT or DEFENSE_FORWARD → Aurora (doc + vector +
    timeseries via pg_partman) + Neptune Serverless + AOSS, all
    CFN-provisioned, zero customer params.

Both variants share one Aurora bootstrap Lambda; it branches on the
`Slices` CFN custom-resource property (commercial omits "timeseries").
"""

from typing import Final

from src.cfn.persistence.aurora_resources import (
    PSYCOPG2_LAYER_ARN_TEMPLATE,
    aurora_cluster_resources,
)
from src.orders.configurator_payload import DeploymentContext

DEFAULT_LAMBDA_RUNTIME: Final[str] = "python3.13"


class PersistenceService:
    """Composes the per-variant persistence section of the CFN template.

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

    def build_resources(
        self,
        *,
        deployment_context: DeploymentContext,  # noqa: ARG002 — wired in next commit
    ) -> dict[str, dict]:
        """Return the merged resource dict for the per-variant persistence stack.

        Commercial returns Aurora resources + vendor-URL secrets (built in a
        follow-up commit). Defense returns Aurora + Neptune + AOSS resources
        (built in a follow-up commit).
        """
        # Aurora is shared across variants. The slices parameter on the
        # bootstrap custom resource is the variant gate — commercial omits
        # "timeseries" because Tiger Cloud owns that slice for them.
        return {
            **aurora_cluster_resources(
                lambda_runtime=self._lambda_runtime,
                psycopg2_layer_arn_template=self._psycopg2_layer_arn_template,
            ),
        }
