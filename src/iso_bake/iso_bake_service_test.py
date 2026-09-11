"""Tests for `IsoBakeService` — pure rendering, no I/O."""

import json

import yaml

from src.iso_bake.iso_bake_service import IsoBakeService
from src.orders.configurator_payload import ConfiguratorPayload

ISO_VERSION = "1.0.0-beta"
ORDER_ID = "11111111-2222-3333-4444-555555555555"

# grid_revenue exercises the richest case: wires_owner + market_region +
# settlement_point all set.
_GRID_REVENUE: dict[str, object] = {
    "path": "grid_revenue",
    "interconnection_level": None,
    "wires_owner": {
        "id": "oncor",
        "name": "Oncor Electric Delivery",
        "type": "tdsp",
        "eia_id": 14354,
    },
    "retail_provider_separate": True,
    "market_region": "ercot",
    "service_type": "firm",
    "flex_obligation": None,
    "export_mode": "limited_export",
    "export_limit_mw": 5.0,
    "market_access": "direct",
    "market_program": "ercot_dgr",
    "settlement_point": "HB_NORTH",
    "intentional_islanding": False,
}

_OFF_GRID: dict[str, object] = {
    "path": "off_grid",
    "interconnection_level": None,
    "wires_owner": None,
    "retail_provider_separate": False,
    "market_region": None,
    "service_type": None,
    "flex_obligation": None,
    "export_mode": "non_export",
    "export_limit_mw": None,
    "market_access": "none",
    "market_program": None,
    "settlement_point": None,
    "intentional_islanding": False,
}

_FLEXIBLE_NO_SETTLEMENT_POINT: dict[str, object] = {
    "path": "flexible",
    "interconnection_level": "distribution",
    "wires_owner": {
        "id": "nvenergy",
        "name": "NV Energy",
        "type": "iou",
        "eia_id": 13407,
    },
    "retail_provider_separate": False,
    "market_region": "non_rto",
    "service_type": "flexible",
    "flex_obligation": {
        "level": "standard",
        "depth_pct": 50.0,
        "max_duration_h": 4.0,
        "max_events_yr": 40,
        "min_interval_h": 20.0,
        "notice_s": 600,
    },
    "export_mode": "non_export",
    "export_limit_mw": None,
    "market_access": "none",
    "market_program": None,
    "settlement_point": None,
    "intentional_islanding": False,
}


def _payload(
    *, grid: dict[str, object] | None = None, **overrides: object
) -> ConfiguratorPayload:
    """Minimal valid payload — override per test. `grid=` replaces the whole
    Grid dict (nested fields don't merge with the default)."""
    base: dict[str, object] = {
        "operator_org": "Brookside Energy LLC",
        "deployment_site_name": "Brookside DC-1",
        "contact_email": "ops@brookside.energy",
        "primary_workload": "ai_inference",
        "gpu_variant": "h100_sxm",
        "target_gpu_count": 8,
        "bess_coupling": "dc_integrated_pcs",
        "bess_capacity_mwh": 10.0,
        "climate_zone": "arid_hot",
        "deployment_context": "commercial",
        "aws_partition": "none",  # ISO path
        "site": {
            "location": {"lat": 32.78, "lon": -96.8, "address": None},
            "country": "US",
            "state": "TX",
        },
        "onsite_generation": {"type": "none", "capacity_mw": None},
        "grid": grid if grid is not None else _GRID_REVENUE,
    }
    base.update(overrides)
    return ConfiguratorPayload.model_validate(base)


def _service() -> IsoBakeService:
    return IsoBakeService(iso_version=ISO_VERSION)


def test_render_install_json_uses_camelcase_keys() -> None:
    """install.json schema matches the wizard's InstallIdentity contract."""
    # Arrange + Act
    raw = _service().render_install_json(payload=_payload(), order_id=ORDER_ID)
    data = json.loads(raw)

    # Assert — these keys are what the wizard's JSX renders verbatim
    assert set(data.keys()) == {
        "customer",
        "site",
        "market",
        "isoVersion",
        "isoBuiltAt",
        "orderId",
        "rev",
    }
    assert data["customer"] == "Brookside Energy LLC"
    assert data["site"] == "Brookside DC-1"
    assert data["isoVersion"] == ISO_VERSION
    assert data["orderId"] == ORDER_ID


def test_render_install_json_grid_revenue_shows_path_owner_region_hub() -> None:
    """`market` combines the path label, wires_owner name, region, and
    settlement point — grid_revenue is the only path with all four."""
    # Arrange + Act
    raw = _service().render_install_json(payload=_payload(), order_id=ORDER_ID)
    data = json.loads(raw)

    # Assert
    assert (
        data["market"] == "Grid + revenue · Oncor Electric Delivery · ERCOT · HB_NORTH"
    )


def test_render_install_json_flexible_without_settlement_point() -> None:
    """flexible doesn't require a settlement point (only grid_revenue does)
    — market string stops after the wires_owner name."""
    # Arrange + Act
    raw = _service().render_install_json(
        payload=_payload(grid=_FLEXIBLE_NO_SETTLEMENT_POINT), order_id=ORDER_ID
    )
    data = json.loads(raw)

    # Assert
    assert data["market"] == "Fast grid · NV Energy"


def test_render_install_json_off_grid() -> None:
    """off_grid has no wires_owner at all — market string is the literal."""
    # Arrange + Act
    raw = _service().render_install_json(
        payload=_payload(grid=_OFF_GRID), order_id=ORDER_ID
    )
    data = json.loads(raw)

    # Assert
    assert data["market"] == "Off-grid"


def test_render_customer_cfg_carries_site_grid_path_owner_and_market() -> None:
    """cfg.customer.yml lands on the appliance with the per-customer overrides."""
    # Arrange + Act
    raw = _service().render_customer_cfg(payload=_payload(), order_id=ORDER_ID)
    data = yaml.safe_load(raw)

    # Assert
    assert data["site_id"] == "brookside_dc_1"
    assert data["grid_path"] == "grid_revenue"
    assert data["wires_owner"] == "Oncor Electric Delivery"
    assert data["wholesale_market"] == "ercot"
    assert data["settlement_point"] == "HB_NORTH"
    assert data["order_id"] == ORDER_ID


def test_render_customer_cfg_off_grid_omits_owner_and_market() -> None:
    """off_grid: no wires_owner key, no wholesale_market/settlement_point
    pair — omitted, not written null."""
    # Arrange + Act
    raw = _service().render_customer_cfg(
        payload=_payload(grid=_OFF_GRID), order_id=ORDER_ID
    )
    data = yaml.safe_load(raw)

    # Assert
    assert "wires_owner" not in data
    assert "wholesale_market" not in data
    assert "settlement_point" not in data
    assert data["grid_path"] == "off_grid"


def test_render_customer_cfg_flexible_has_owner_but_no_market() -> None:
    """flexible: wires_owner present (non-off-grid), but no settlement
    point → no wholesale_market/settlement_point pair either."""
    # Arrange + Act
    raw = _service().render_customer_cfg(
        payload=_payload(grid=_FLEXIBLE_NO_SETTLEMENT_POINT), order_id=ORDER_ID
    )
    data = yaml.safe_load(raw)

    # Assert
    assert data["wires_owner"] == "NV Energy"
    assert "wholesale_market" not in data
    assert "settlement_point" not in data


def test_render_install_json_unicode_site_name_survives() -> None:
    """Site names with non-ascii must round-trip through json without mangling."""
    # Arrange
    payload = _payload(deployment_site_name="Café 🔥 Site")

    # Act
    raw = _service().render_install_json(payload=payload, order_id=ORDER_ID)
    data = json.loads(raw)

    # Assert
    assert data["site"] == "Café 🔥 Site"
