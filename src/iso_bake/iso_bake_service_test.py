"""Tests for `IsoBakeService` — pure rendering, no I/O."""

import json

import yaml

from src.iso_bake.iso_bake_service import IsoBakeService
from src.orders.configurator_payload import (
    AwsPartition,
    BessCoupling,
    ClimateZone,
    ConfiguratorPayload,
    DeploymentContext,
    EnergySource,
    GpuVariant,
    GridConnection,
    PrimaryWorkload,
    WholesaleMarket,
)

ISO_VERSION = "1.0.0-beta"
ORDER_ID = "11111111-2222-3333-4444-555555555555"


def _payload(**overrides: object) -> ConfiguratorPayload:
    """Minimal valid payload — override per test."""
    base: dict[str, object] = {
        "operator_org": "Brookside Energy LLC",
        "deployment_site_name": "Brookside DC-1",
        "contact_email": "ops@brookside.energy",
        "energy_source": EnergySource.SOLAR,
        "source_capacity_mw": 50.0,
        "primary_workload": PrimaryWorkload.AI_INFERENCE,
        "gpu_variant": GpuVariant.H100_SXM,
        "target_gpu_count": 8,
        "bess_coupling": BessCoupling.DC_INTEGRATED_PCS,
        "bess_capacity_mwh": 10.0,
        "grid_connection": GridConnection.GRID_TIED,
        "climate_zone": ClimateZone.ARID_HOT,
        "deployment_context": DeploymentContext.COMMERCIAL,
        "aws_partition": AwsPartition.NONE,  # ISO path
        "wholesale_market": WholesaleMarket.ERCOT,
        "settlement_point": "HB_NORTH",
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


def test_render_install_json_formats_market_with_hub() -> None:
    """`market` field combines wholesale market name + settlement point hub."""
    # Arrange + Act
    raw = _service().render_install_json(payload=_payload(), order_id=ORDER_ID)
    data = json.loads(raw)

    # Assert — UI displays "ERCOT · HB_NORTH" — middle-dot separator from designer
    assert data["market"] == "ERCOT · HB_NORTH"


def test_render_customer_cfg_carries_site_and_market() -> None:
    """cfg.customer.yml lands on the appliance with the per-customer overrides."""
    # Arrange + Act
    raw = _service().render_customer_cfg(payload=_payload(), order_id=ORDER_ID)
    data = yaml.safe_load(raw)

    # Assert — these are the only things a per-customer override needs at MVP
    assert data["site_id"] == "brookside_dc_1"
    assert data["wholesale_market"] == "ercot"
    assert data["settlement_point"] == "HB_NORTH"
    assert data["order_id"] == ORDER_ID


def test_render_install_json_unicode_site_name_survives() -> None:
    """Site names with non-ascii must round-trip through json without mangling."""
    # Arrange
    payload = _payload(deployment_site_name="Café 🔥 Site")

    # Act
    raw = _service().render_install_json(payload=payload, order_id=ORDER_ID)
    data = json.loads(raw)

    # Assert
    assert data["site"] == "Café 🔥 Site"
