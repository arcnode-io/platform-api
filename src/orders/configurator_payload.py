"""ConfiguratorPayload — operator submission shape, mirrored from edp-api.

Platform-api accepts this and forwards verbatim to `POST /edp-api/jobs`. edp-api
runs the source-capacity validator; if that fails, edp-api returns 422 and we
relay it to the configurator. Fields stay in lock-step with edp-api's
`sizing_engine.payload` + `sizing_engine.enums`.
"""

from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field


class EnergySource(StrEnum):
    """Operator-declared upstream energy source."""

    NUCLEAR = "nuclear"
    SOLAR = "solar"
    GRID_HYBRID = "grid_hybrid"
    OFF_GRID = "off_grid"


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


class GridConnection(StrEnum):
    """Grid coupling. `none` = no utility tie (off-grid; grid container still present)."""

    NONE = "none"
    GRID_TIED = "grid_tied"
    GRID_BACKUP = "grid_backup"


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


class WholesaleMarket(StrEnum):
    """ISO / RTO the deployment participates in. v1 ships ERCOT only.

    Mirrors edp-api/src/shared/enums.py:WholesaleMarket exactly.
    """

    ERCOT = "ercot"
    CAISO = "caiso"
    MISO = "miso"
    PJM = "pjm"
    ISO_NE = "isone"
    NYISO = "nyiso"
    SPP = "spp"


class ConfiguratorPayload(BaseModel):
    """Operator-submitted configuration. Forwarded verbatim to edp-api."""

    operator_org: str
    deployment_site_name: str
    contact_email: EmailStr
    energy_source: EnergySource
    source_capacity_mw: float = Field(gt=0)
    primary_workload: PrimaryWorkload
    gpu_variant: GpuVariant
    target_gpu_count: int = Field(gt=0)
    bess_coupling: BessCoupling
    bess_capacity_mwh: float = Field(ge=0)
    grid_connection: GridConnection
    climate_zone: ClimateZone
    deployment_context: DeploymentContext
    aws_partition: AwsPartition
    wholesale_market: WholesaleMarket
    # Free-form; the edp-api side validates (ISO, hub) compatibility.
    settlement_point: str
