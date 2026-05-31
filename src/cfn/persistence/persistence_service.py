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
from src.cfn.persistence.customer_url_preflight_resources import (
    customer_url_preflight_resources,
)
from src.cfn.persistence.neptune_resources import neptune_resources
from src.cfn.persistence.vendor_secrets import (
    agent_api_key_parameters,
    agent_api_key_secrets,
    commercial_url_parameters,
    vendor_url_secrets,
)
from src.cfn.persistence.auth_secrets import (
    auth_human_parameters,
    auth_human_secrets,
    auth_machine_secrets,
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
        self, *, deployment_context: DeploymentContext, short: str, e2e: bool = False
    ) -> PersistenceBuild:
        """Return the per-variant persistence build.

        ``short`` is the 8-char prefix of the deployment uuid used for
        AWS-resource names that have tight length limits (e.g. AOSS
        policies cap at 32 chars — full StackName blows the limit).

        ``e2e`` skips the customer-URL preflight resource. The preflight
        Lambda runs from a random AWS public IP; if the customer's
        Tiger Cloud / Aura allowlist (a per-tenant setting on their
        account, not ours) excludes Lambda ranges, preflight fails
        even when the actual EC2-side connection would succeed. e2e
        tests run against accounts we control where opening the
        allowlist is the operator's responsibility, not the CFN
        template's.
        """
        if deployment_context == DeploymentContext.COMMERCIAL:
            return self._commercial_build(e2e=e2e)
        return self._defense_build(short=short)

    def _commercial_build(self, *, e2e: bool = False) -> PersistenceBuild:
        resources: dict[str, dict] = {
            **aurora_cluster_resources(
                lambda_runtime=self._lambda_runtime,
                psycopg2_layer_arn_template=self._psycopg2_layer_arn_template,
                slices=COMMERCIAL_SLICES,
            ),
            **vendor_url_secrets(),
            **agent_api_key_secrets(),
            **auth_machine_secrets(),
            **auth_human_secrets(),
        }
        if not e2e:
            resources.update(
                customer_url_preflight_resources(
                    lambda_runtime=self._lambda_runtime,
                )
            )
        depends_on = [
            "AuroraBootstrapCustomResource",
            "TimeseriesUrlSecret",
            "GraphUrlSecret",
            "OpenweathermapApiKeySecret",
            # Broker + human auth secrets — UserData reads them at boot to
            # write credentials.xml + secrets.env.
            *auth_machine_secrets(),
            *auth_human_secrets(),
        ]
        if not e2e:
            depends_on.append("CustomerUrlPreflightCustomResource")
        return PersistenceBuild(
            resources=resources,
            parameters={
                **commercial_url_parameters(),
                **agent_api_key_parameters(),
                **auth_human_parameters(),
            },
            ems_instance_depends_on=depends_on,
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
                **auth_machine_secrets(),
                **auth_human_secrets(),
                **neptune_resources(),
                **aoss_resources(short=short),
            },
            parameters={
                **agent_api_key_parameters(),
                **auth_human_parameters(),
            },
            ems_instance_depends_on=[
                "AuroraBootstrapCustomResource",
                "OpenweathermapApiKeySecret",
                "NeptuneInstance",
                "AossCollection",
                "NeptuneHostParam",
                "NeptuneLoaderRoleArnParam",
                "AossHostParam",
                # Broker + human auth secrets (variant-agnostic).
                *auth_machine_secrets(),
                *auth_human_secrets(),
            ],
        )
