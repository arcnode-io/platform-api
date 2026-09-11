"""IsoBakeService — renders the per-customer ISO overlay files.

Two files land in `s3://arcnode-public/orders/{order_id}/iso-overlay/`:

  - install.json       — read by the wizard at first boot, displayed verbatim
                         on Step 1 ("you booted the right ISO for this order")
  - cfg.customer.yml   — copied to /etc/arcnode/cfg.customer.yml inside the
                         appliance, overrides cfg.defaults.yml at runtime

The build pipeline (Layer 3) downloads both into live-build's
`config/includes.chroot/etc/arcnode/` before running `lb build`.

Pure rendering — no I/O. The orchestrator does the S3 upload.
"""

import json
import re
from datetime import UTC, datetime

import yaml

from src.orders.configurator_grid import GridPath
from src.orders.configurator_payload import ConfiguratorPayload

_SITE_ID_RX = re.compile(r"[^a-z0-9]+")

# Wizard-facing label per non-off-grid path — off_grid gets its own literal
# ("Off-grid"), handled separately since it needs no wires_owner/region.
_PATH_LABELS: dict[GridPath, str] = {
    GridPath.FLEXIBLE: "Fast grid",
    GridPath.FIRM: "Firm grid",
    GridPath.GRID_REVENUE: "Grid + revenue",
}


def _slugify_site_id(name: str) -> str:
    """Mirror of orchestrator_service._slugify_site_id — kept inline so the
    bake service has no cross-layer import."""
    slug = _SITE_ID_RX.sub("_", name.lower()).strip("_")
    if not slug:
        raise ValueError(f"deployment_site_name slugifies to empty: {name!r}")
    return slug


class IsoBakeService:
    """Render the per-customer ISO overlay files (install.json + cfg.customer.yml)."""

    def __init__(self, iso_version: str) -> None:
        # Reason: iso_version is the platform-ems-iso semver from config —
        # bake-time fact, not per-order. Threaded through so the wizard
        # displays "isoVersion: 1.0.0-beta" for every customer of that build.
        self._iso_version = iso_version

    def render_install_json(
        self, *, payload: ConfiguratorPayload, order_id: str
    ) -> str:
        """install.json shape matches the wizard's InstallIdentity contract."""
        market = self._market_string(payload)
        body = {
            "customer": payload.operator_org,
            "site": payload.deployment_site_name,
            "market": market,
            "isoVersion": self._iso_version,
            "isoBuiltAt": datetime.now(UTC).strftime("%d %b %Y"),
            "orderId": order_id,
            # Rev bumps on a re-bake of the same order; v1 ships only Rev 1.
            "rev": "Rev 1",
        }
        # ensure_ascii=False so unicode site names round-trip without \uXXXX
        return json.dumps(body, ensure_ascii=False, indent=2)

    def render_customer_cfg(
        self, *, payload: ConfiguratorPayload, order_id: str
    ) -> str:
        """cfg.customer.yml — per-customer overrides loaded over cfg.defaults.yml.

        wires_owner (off-grid has none) and wholesale_market/settlement_point
        (only when a settlement point is set) are omitted rather than
        written null.
        """
        grid = payload.grid
        body: dict[str, object] = {
            "site_id": _slugify_site_id(payload.deployment_site_name),
            "grid_path": grid.path.value,
        }
        if grid.path != GridPath.OFF_GRID:
            # edp-api's V5a guarantees wires_owner is set for any non-off-grid
            # path by the time an order reaches us — fail loud, not silent,
            # if that invariant is somehow broken.
            assert grid.wires_owner is not None
            body["wires_owner"] = grid.wires_owner.name
        if grid.settlement_point is not None:
            assert grid.market_region is not None
            body["wholesale_market"] = grid.market_region.value
            body["settlement_point"] = grid.settlement_point
        body["order_id"] = order_id
        return yaml.safe_dump(body, sort_keys=False)

    @staticmethod
    def _market_string(payload: ConfiguratorPayload) -> str:
        """The wizard's Step-1 grid-program display string."""
        grid = payload.grid
        if grid.path == GridPath.OFF_GRID:
            return "Off-grid"
        # edp-api's V5a guarantees wires_owner + market_region are set for
        # any non-off-grid path by the time an order reaches us.
        assert grid.wires_owner is not None
        market = f"{_PATH_LABELS[grid.path]} · {grid.wires_owner.name}"
        if grid.settlement_point is not None:
            assert grid.market_region is not None
            market += f" · {grid.market_region.value.upper()} · {grid.settlement_point}"
        return market
