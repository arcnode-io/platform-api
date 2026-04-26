"""ConfiguratorPayload — operator submission shape, mirrored from edp-api.

Platform-api accepts this and forwards verbatim to `POST /edp-api/jobs`. edp-api
runs the source-capacity validator; if that fails, edp-api returns 422 and we
relay it to the configurator. Fields stay in lock-step with edp-api's
`sizing_engine.payload` + `sizing_engine.enums`.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


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


class GridConnection(StrEnum):
    """Grid coupling. `none` = no PCS, BESS-only deployment."""

    NONE = "none"
    GRID_TIED = "grid_tied"
    GRID_BACKUP = "grid_backup"


class ClimateZone(StrEnum):
    """Site climate zone; selects coolant glycol concentration + dry-cooler ambient."""

    TEMPERATE = "temperate"
    DESERT = "desert"
    ARCTIC = "arctic"
    TROPICAL = "tropical"


class DeploymentContext(StrEnum):
    """Customer segment. Drives EDP content (compliance), not delivery routing."""

    COMMERCIAL = "commercial"
    RESEARCH = "research"
    SOVEREIGN_GOVERNMENT = "sovereign_government"
    DEFENSE_FORWARD = "defense_forward"


class EmsMode(StrEnum):
    """EMS runtime mode. `sim` uses fixtures; `live` requires real protocol connections."""

    SIM = "sim"
    LIVE = "live"


class AwsPartition(StrEnum):
    """AWS partition / delivery routing key."""

    STANDARD = "standard"
    GOVCLOUD = "govcloud"
    NONE = "none"


class ConfiguratorPayload(BaseModel):
    """Operator-submitted configuration. Forwarded verbatim to edp-api."""

    operator_org: str
    deployment_site_name: str
    contact_email: str
    energy_source: EnergySource
    source_capacity_mw: float = Field(gt=0)
    primary_workload: PrimaryWorkload
    gpu_variant: GpuVariant
    target_gpu_count: int = Field(gt=0)
    bess_autonomy_hr: float = Field(gt=0)
    grid_connection: GridConnection
    climate_zone: ClimateZone
    deployment_context: DeploymentContext
    ems_mode: EmsMode
    aws_partition: AwsPartition
