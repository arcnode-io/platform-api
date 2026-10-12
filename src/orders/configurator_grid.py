"""Grid-model types for ConfiguratorPayload v2 — mirrored from edp-api.

Split out of configurator_payload.py per the 200-line rule (same split
edp-api uses). No cross-field validators here — platform-api forwards
verbatim and relays edp-api's 422 (unchanged policy); every structural
rule (V1-V9 in the cross-repo contract) lives only in edp-api's mirror
of these same models.

See /tmp/handoffs/handoff-configurator-grid-CONTRACT-2026-09-11.md §1.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SiteLocation(BaseModel):
    """Lat/lon feeds platform-api's /grid/resolve; address is display-only."""

    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    address: str | None = None


class Site(BaseModel):
    """country is ISO 3166-1 alpha-2, uppercase."""

    model_config = ConfigDict(extra="forbid")

    location: SiteLocation
    country: str = Field(pattern=r"^[A-Z]{2}$")
    state: str | None = None


class OnsiteGenerationType(StrEnum):
    """Firm onsite generation source. Solar counts 0 toward firm_onsite_mw
    in the sizing preview (intermittent); nuclear counts full capacity."""

    NONE = "none"
    NUCLEAR = "nuclear"
    SOLAR = "solar"


class OnsiteGeneration(BaseModel):
    """capacity_mw > 0 iff type != none, null iff type == none — edp-api's
    V7 enforces this; not duplicated here (forward-verbatim policy)."""

    model_config = ConfigDict(extra="forbid")

    type: OnsiteGenerationType
    capacity_mw: float | None = None


class WiresOwnerType(StrEnum):
    """Utility ownership structure. Drives retail-competition assumptions."""

    IOU = "iou"
    COOP = "coop"
    MUNI = "muni"
    TDSP = "tdsp"
    FEDERAL = "federal"
    OTHER = "other"


class WiresOwner(BaseModel):
    """The distribution utility at the site, resolved from site.location."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    type: WiresOwnerType
    eia_id: int | None = None


class GridPath(StrEnum):
    """Top-level grid participation choice. Drives which other Grid fields
    are required/null — edp-api's V1-V4a enforce that, not platform-api."""

    OFF_GRID = "off_grid"
    FLEXIBLE = "flexible"
    FIRM = "firm"
    GRID_REVENUE = "grid_revenue"


class InterconnectionLevel(StrEnum):
    """Server-derived (edp-api overwrites at JobsService.create) — the
    client may send null, or a stale value that gets replaced."""

    DISTRIBUTION = "distribution"
    TRANSMISSION = "transmission"


class MarketRegion(StrEnum):
    """ISO/RTO the deployment sits in, or non_rto if outside all of them.
    Renamed from WholesaleMarket (v1) — adds NON_RTO."""

    ERCOT = "ercot"
    CAISO = "caiso"
    MISO = "miso"
    PJM = "pjm"
    ISO_NE = "isone"
    NYISO = "nyiso"
    SPP = "spp"
    NON_RTO = "non_rto"


class ServiceType(StrEnum):
    """Utility interconnection service class — independent of market_access
    (a firm-service site can still sell into a wholesale market)."""

    FIRM = "firm"
    FLEXIBLE = "flexible"


class FlexLevel(StrEnum):
    """Preset curtailment depth/duration bundles, or custom numbers.
    Non-custom levels must match grid_regions.yaml's flex_levels exactly
    (edp-api's FL rule) — platform-api doesn't check this."""

    LIGHT = "light"
    STANDARD = "standard"
    HEAVY = "heavy"
    CUSTOM = "custom"


class FlexObligation(BaseModel):
    """Curtailment contract terms. Required whenever service_type ==
    flexible (edp-api's V2/V4a); null otherwise."""

    model_config = ConfigDict(extra="forbid")

    level: FlexLevel
    depth_pct: float = Field(gt=0, le=100)
    max_duration_h: float = Field(gt=0)
    max_events_yr: int = Field(ge=0)
    min_interval_h: float = Field(gt=0)
    notice_s: int = Field(ge=0)


class ExportMode(StrEnum):
    """Whether the site sells power back to the grid, and how much."""

    NON_EXPORT = "non_export"
    LIMITED_EXPORT = "limited_export"
    EXPORT = "export"


class MarketAccess(StrEnum):
    """How the site participates in wholesale/DER markets, if at all."""

    NONE = "none"
    RETAIL_PROGRAM = "retail_program"
    AGGREGATED = "aggregated"
    DIRECT = "direct"


class MarketProgram(StrEnum):
    """Named DER program. v1 ships ERCOT's two programs only."""

    ERCOT_ADER = "ercot_ader"
    ERCOT_DGR = "ercot_dgr"


class Grid(BaseModel):
    """The site's grid participation. Cross-field rules (V1-V9, EX in the
    contract) live only in edp-api — platform-api forwards verbatim."""

    model_config = ConfigDict(extra="forbid")

    path: GridPath
    interconnection_level: InterconnectionLevel | None = None
    wires_owner: WiresOwner | None = None
    retail_provider_separate: bool = False
    market_region: MarketRegion | None = None
    service_type: ServiceType | None = None
    flex_obligation: FlexObligation | None = None
    export_mode: ExportMode = ExportMode.NON_EXPORT
    export_limit_mw: float | None = None
    market_access: MarketAccess = MarketAccess.NONE
    market_program: MarketProgram | None = None
    settlement_point: str | None = None
    intentional_islanding: bool = False
