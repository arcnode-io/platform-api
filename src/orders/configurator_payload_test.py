"""Lock the wire shape between arc-node.html's configurator and ConfiguratorPayload.

The website's `readConfiguratorState()` JS produces this exact dict shape. If
a Pydantic enum gets renamed without updating the matching `<option
value="...">` in arc-node.html, this test fails and points at the drift.

NOTE: arc-node.html hasn't landed the v2 grid model yet (still emits the v1.5
der_utility/wholesale_market shape as of this writing) — the enum-coverage
test below only locks the 6 top-level enums that are unchanged from v1.
Extend it to grid/site/onsite_generation once the website's side lands.

Mirror of the JS shape in `website/arc-node.html` — keep them in lockstep.
"""

import typing

from src.orders.configurator_grid import FlexObligation, Grid, OnsiteGeneration
from src.orders.configurator_payload import ConfiguratorPayload

# A realistic "flexible" grid path — the shape readConfiguratorState() will
# emit once arc-node.html's v2 form lands (CONTRACT §1 / §7).
JS_PAYLOAD: dict[str, object] = {
    "operator_org": "Acme Energy",
    "deployment_site_name": "Nevada Facility 2",
    "contact_email": "ops@acme.example",
    "primary_workload": "ai_training",
    "gpu_variant": "h100_sxm",
    "target_gpu_count": 512,
    "bess_coupling": "ac_coupled",
    "bess_capacity_mwh": 20.0,
    "climate_zone": "temperate",
    "deployment_context": "commercial",
    "aws_partition": "standard",
    "site": {
        "location": {"lat": 36.17, "lon": -115.14, "address": None},
        "country": "US",
        "state": "NV",
    },
    "onsite_generation": {"type": "none", "capacity_mw": None},
    "grid": {
        "path": "flexible",
        "interconnection_level": None,
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
    },
}


def test_configurator_js_payload_validates_against_pydantic_schema() -> None:
    """The shape readConfiguratorState() will emit parses cleanly."""
    # Arrange + Act — Pydantic raises on any drift (missing field, wrong enum value)
    payload = ConfiguratorPayload.model_validate(JS_PAYLOAD)

    # Assert — round-trip values land on the right enum members / nested models
    assert payload.primary_workload.value == "ai_training"
    assert payload.gpu_variant.value == "h100_sxm"
    assert payload.bess_coupling.value == "ac_coupled"
    assert payload.climate_zone.value == "temperate"
    assert payload.deployment_context.value == "commercial"
    assert payload.aws_partition.value == "standard"
    assert payload.site.country == "US"
    assert payload.site.location.lat == 36.17
    assert payload.onsite_generation.type.value == "none"
    assert payload.grid.path.value == "flexible"
    assert payload.grid.wires_owner is not None
    assert payload.grid.wires_owner.name == "NV Energy"
    assert payload.grid.market_region is not None
    assert payload.grid.market_region.value == "non_rto"


def test_configurator_js_payload_covers_every_select_enum_value() -> None:
    """Every <option value="..."> in arc-node.html is a valid enum member.

    We can't scrape the HTML cross-repo, but we can lock the full enum
    surface on the Python side: if a new enum member lands without a
    matching <option> in the website (or vice-versa), this test gets
    updated and the discrepancy surfaces in code review.

    Scoped to the 6 top-level enums unchanged since v1 — see module
    docstring for why the grid-model enums aren't covered here yet.
    """
    js_select_values: dict[str, set[str]] = {
        "primary_workload": {"ai_training", "ai_inference", "mixed"},
        "gpu_variant": {"h100_sxm", "b200"},
        "bess_coupling": {
            "ac_coupled",
            "dc_integrated_pcs",
            "dc_external_pcs",
            "none",
        },
        "climate_zone": {"subarctic", "temperate", "arid_hot", "tropical"},
        "deployment_context": {
            "commercial",
            "sovereign_government",
            "defense_forward",
        },
        "aws_partition": {"standard", "govcloud", "none"},
    }

    for field, js_values in js_select_values.items():
        annotation = ConfiguratorPayload.model_fields[field].annotation
        assert annotation is not None
        union_args = typing.get_args(annotation)
        py_enum = next((a for a in union_args if a is not type(None)), annotation)
        py_values = {member.value for member in py_enum}  # type: ignore[union-attr]
        assert (
            js_values == py_values
        ), f"{field}: html has {js_values}, python has {py_values}"


def test_off_grid_path_validates() -> None:
    """off_grid: no wires_owner/market_region/service_type/etc — edp-api's
    V1 enforces that they're null, platform-api just needs to accept them
    as such (no local validator)."""
    # Arrange + Act
    payload = ConfiguratorPayload.model_validate(
        {
            **JS_PAYLOAD,
            "grid": {
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
            },
        }
    )

    # Assert
    assert payload.grid.path.value == "off_grid"
    assert payload.grid.wires_owner is None
    assert payload.grid.market_region is None


def test_grid_revenue_path_validates_with_settlement_point() -> None:
    """grid_revenue: market_program + settlement_point set — the case that
    feeds CfnService's market: block."""
    # Arrange + Act
    payload = ConfiguratorPayload.model_validate(
        {
            **JS_PAYLOAD,
            "grid": {
                **typing.cast(dict, JS_PAYLOAD["grid"]),
                "path": "grid_revenue",
                "market_region": "ercot",
                "export_mode": "limited_export",
                "export_limit_mw": 5.0,
                "market_access": "direct",
                "market_program": "ercot_dgr",
                "settlement_point": "HB_NORTH",
            },
        }
    )

    # Assert
    assert payload.grid.path.value == "grid_revenue"
    assert payload.grid.settlement_point == "HB_NORTH"
    assert payload.grid.market_program is not None
    assert payload.grid.market_program.value == "ercot_dgr"


def test_country_must_be_uppercase_two_letter_code() -> None:
    """site.country is ISO 3166-1 alpha-2, uppercase, exactly 2 chars."""
    # Arrange + Act + Assert
    payload = ConfiguratorPayload.model_validate(JS_PAYLOAD)
    assert payload.site.country == "US"

    bad = {
        **JS_PAYLOAD,
        "site": {**typing.cast(dict, JS_PAYLOAD["site"]), "country": "usa"},
    }
    try:
        ConfiguratorPayload.model_validate(bad)
        raise AssertionError("expected a validation error for a 3-letter country code")
    except ValueError:
        pass


def test_flex_obligation_is_a_nested_model_not_a_dict() -> None:
    """Type-check the split: Grid/FlexObligation/OnsiteGeneration live in
    configurator_grid.py, not configurator_payload.py."""
    # Arrange + Act
    payload = ConfiguratorPayload.model_validate(JS_PAYLOAD)

    # Assert
    assert isinstance(payload.grid, Grid)
    assert isinstance(payload.onsite_generation, OnsiteGeneration)
    assert payload.grid.flex_obligation is not None
    assert isinstance(payload.grid.flex_obligation, FlexObligation)
    assert payload.grid.flex_obligation.level.value == "standard"
