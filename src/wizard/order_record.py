"""The order a per-order ISO carries in /order: platform-api's orchestrator
writes it, the wizard's Site page reads it. One model for both sides."""

from typing import Final

from pydantic import BaseModel, ConfigDict

# Both files sit side by side in /order on the ISO, then /etc/arcnode/order
# on the installed box.
SITE_FILE: Final[str] = "site.yml"
DTM_FILE: Final[str] = "dtm.json"


class OrderSite(BaseModel):
    """site.yml — the order values the cloud's UserData bakes into its cfg
    files, from the same ConfiguratorPayload fields."""

    site_id: str  # already slugified by the orchestrator
    market_region: str | None = None
    settlement_point: str | None = None


class OrderDevice(BaseModel):
    """The bits of a DTM device the Site page reports on. ems-device-api
    owns the full schema and validates it when it boots."""

    model_config = ConfigDict(extra="allow")

    template: str
    parent: str | None = None


class OrderDtm(BaseModel):
    """dtm.json — edp-api's Device Topology Manifest for the order."""

    model_config = ConfigDict(extra="allow")

    devices: dict[str, OrderDevice]
