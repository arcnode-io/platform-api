"""ConfiguratorPayload — operator submission shape, mirrored from edp-api.

Platform-api accepts this and forwards verbatim to `POST /edp-api/jobs`. edp-api
runs the structural + region-dependent validators; if either fails, edp-api
returns 422 and we relay it to the configurator. Fields stay in lock-step
with edp-api's `src/shared/schemas/configurator_payload.py` + `src/shared/enums.py`.

v2: grid participation (site, onsite_generation, grid) replaces the flat
energy_source/source_capacity_mw/grid_connection/der_utility/wholesale_market/
settlement_point fields — see configurator_grid.py and
/tmp/handoffs/handoff-configurator-grid-CONTRACT-2026-09-11.md.
"""

from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field

from src.orders.configurator_grid import Grid, OnsiteGeneration, Site


class PrimaryWorkload(StrEnum):
    """GPU workload character; drives BESS-charge simultaneity factor in edp-api."""

    AI_TRAINING = "ai_training"
    AI_INFERENCE = "ai_inference"
    MIXED = "mixed"


class GpuVariant(StrEnum):
    """GPU SKU. Selects TDP in the sizing engine."""

    H100_SXM = "h100_sxm"
    B200 = "b200"


class BessCoupling(StrEnum):
    """External BESS coupling at the grid container boundary."""

    AC_COUPLED = "ac_coupled"
    DC_INTEGRATED_PCS = "dc_integrated_pcs"
    DC_EXTERNAL_PCS = "dc_external_pcs"
    NONE = "none"


class ClimateZone(StrEnum):
    """Site climate zone; selects coolant glycol concentration + dry-cooler ambient."""

    SUBARCTIC = "subarctic"
    TEMPERATE = "temperate"
    ARID_HOT = "arid_hot"
    TROPICAL = "tropical"


class DeploymentContext(StrEnum):
    """Customer segment. Drives EDP content (compliance), not delivery routing.

    Mirrors edp-api/src/shared/enums.py:DeploymentContext exactly. Three values
    only — there is no `research` segment downstream.
    """

    COMMERCIAL = "commercial"
    SOVEREIGN_GOVERNMENT = "sovereign_government"
    DEFENSE_FORWARD = "defense_forward"


class AwsPartition(StrEnum):
    """AWS partition / delivery routing key."""

    STANDARD = "standard"
    GOVCLOUD = "govcloud"
    NONE = "none"


class ConfiguratorPayload(BaseModel):
    """Operator-submitted configuration. Forwarded verbatim to edp-api.

    No cross-field validators (policy unchanged from v1) — edp-api owns
    every structural + region-dependent rule on `site`/`onsite_generation`/
    `grid`; platform-api just relays its 422 on an invalid combo.
    """

    operator_org: str
    deployment_site_name: str
    contact_email: EmailStr
    primary_workload: PrimaryWorkload
    gpu_variant: GpuVariant
    target_gpu_count: int = Field(ge=1)
    bess_coupling: BessCoupling
    bess_capacity_mwh: float = Field(ge=0)
    climate_zone: ClimateZone
    deployment_context: DeploymentContext
    aws_partition: AwsPartition
    site: Site
    onsite_generation: OnsiteGeneration
    grid: Grid
