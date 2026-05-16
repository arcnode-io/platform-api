"""PersistenceService — variant-aware CFN persistence section builder.

`build(deployment_context)` returns everything `CfnService.render_template`
needs for the persistence layer of one variant:

  - `resources`        — the CFN Resources block contributions
  - `parameters`       — the CFN Parameters block contributions (commercial
                         needs 2 customer-supplied URLs; defense has none)
  - `ems_instance_depends_on` — the EC2 instance must wait for these
                         logical IDs before launching so UserData can fetch
                         from Secrets Manager + SSM at boot.

Commercial: Aurora doc+vector + customer-supplied Tiger/Aura URLs as
CFN-native Secrets Manager secrets.

Defense (sovereign_government, defense_forward): Aurora doc+vector+
timeseries (via pg_partman) + Neptune Serverless + AOSS — all
CFN-provisioned, zero customer params.
"""

from dataclasses import dataclass, field
from typing import Final

from src.cfn.persistence.aoss_resources import aoss_resources
from src.cfn.persistence.aurora_resources import (
    COMMERCIAL_SLICES,
    DEFENSE_SLICES,
    PSYCOPG2_LAYER_ARN_TEMPLATE,
    aurora_cluster_resources,
)
from src.cfn.persistence.neptune_resources import neptune_resources
from src.cfn.persistence.vendor_secrets import (
    agent_api_key_parameters,
    agent_api_key_secrets,
    commercial_url_parameters,
    vendor_url_secrets,
)
from src.orders.configurator_payload import DeploymentContext

DEFAULT_LAMBDA_RUNTIME: Final[str] = "python3.13"


@dataclass(frozen=True)
class PersistenceBuild:
    """What `PersistenceService.build` publishes for one variant.

    `resources` and `parameters` plug straight into CFN's top-level blocks.
    `ems_instance_depends_on` is the variant's set of logical IDs that the
    EmsInstance must wait for — EC2 UserData reads these at boot, and CFN
    can't infer that dependency from a UserData shell script.
    """

    resources: dict[str, dict]
    parameters: dict[str, dict]
    ems_instance_depends_on: list[str] = field(default_factory=list)


class PersistenceService:
    """Composes the per-variant persistence section of the CFN template.

    Tunables (all default to prod-correct values):
      - `lambda_runtime` — LocalStack tests pass `"python3.12"`; LocalStack
        hasn't picked up the 3.13 runtime yet.
      - `psycopg2_layer_arn_template` — set to `None` in LocalStack tests
        because LocalStack community can't fetch shared layers from real
        AWS (Pro-only feature).
    """

    def __init__(
        self,
        *,
        lambda_runtime: str = DEFAULT_LAMBDA_RUNTIME,
        psycopg2_layer_arn_template: str | None = PSYCOPG2_LAYER_ARN_TEMPLATE,
    ) -> None:
        self._lambda_runtime = lambda_runtime
        self._psycopg2_layer_arn_template = psycopg2_layer_arn_template

    def build(
        self, *, deployment_context: DeploymentContext, short: str
    ) -> PersistenceBuild:
        """Return the per-variant persistence build.

        ``short`` is the 8-char prefix of the deployment uuid used for
        AWS-resource names that have tight length limits (e.g. AOSS
        policies cap at 32 chars — full StackName blows the limit).
        """
        if deployment_context == DeploymentContext.COMMERCIAL:
            return self._commercial_build()
        return self._defense_build(short=short)

    def _commercial_build(self) -> PersistenceBuild:
        return PersistenceBuild(
            resources={
                **aurora_cluster_resources(
                    lambda_runtime=self._lambda_runtime,
                    psycopg2_layer_arn_template=self._psycopg2_layer_arn_template,
                    slices=COMMERCIAL_SLICES,
                ),
                **vendor_url_secrets(),
                **agent_api_key_secrets(),
            },
            parameters={
                **commercial_url_parameters(),
                **agent_api_key_parameters(),
            },
            ems_instance_depends_on=[
                "AuroraBootstrapCustomResource",
                "TimeseriesUrlSecret",
                "GraphUrlSecret",
                "OpenweathermapApiKeySecret",
            ],
        )

    def _defense_build(self, *, short: str) -> PersistenceBuild:
        """Aurora (3 slices) + Neptune Serverless + AOSS — the full defense
        persistence stack. EmsInstance waits for each so UserData can read
        the SSM hostnames + Aurora secrets at boot.
        """
        return PersistenceBuild(
            resources={
                **aurora_cluster_resources(
                    lambda_runtime=self._lambda_runtime,
                    psycopg2_layer_arn_template=self._psycopg2_layer_arn_template,
                    slices=DEFENSE_SLICES,
                ),
                **agent_api_key_secrets(),
                **neptune_resources(),
                **aoss_resources(short=short),
            },
            parameters=agent_api_key_parameters(),
            ems_instance_depends_on=[
                "AuroraBootstrapCustomResource",
                "OpenweathermapApiKeySecret",
                "NeptuneInstance",
                "AossCollection",
                "NeptuneHostParam",
                "NeptuneLoaderRoleArnParam",
                "AossHostParam",
            ],
        )
