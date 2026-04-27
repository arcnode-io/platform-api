"""Lock the wire shape between arc-node.html's configurator and ConfiguratorPayload.

The website's `buildPayload()` JS produces this exact dict shape. If a Pydantic
enum gets renamed without updating the matching `<option value="...">` in
arc-node.html, this test fails and points at the drift.

Mirror of the JS shape in `website/arc-node.html` — keep them in lockstep.
"""

from src.orders.configurator_payload import ConfiguratorPayload

# The exact dict shape JS builds via buildPayload() in arc-node.html.
# Strings come from <option value="..."> selects; numbers from
# parseFloat/parseInt on numeric inputs.
JS_PAYLOAD: dict[str, object] = {
    "operator_org": "Acme Energy",
    "deployment_site_name": "Nevada Facility 2",
    "contact_email": "ops@acme.example",
    "energy_source": "nuclear",
    "source_capacity_mw": 10.0,
    "primary_workload": "ai_training",
    "gpu_variant": "h100_sxm",
    "target_gpu_count": 512,
    "bess_autonomy_hr": 4.0,
    "grid_connection": "grid_tied",
    "climate_zone": "temperate",
    "deployment_context": "commercial",
    "ems_mode": "sim",
    "aws_partition": "standard",
}


def test_configurator_js_payload_validates_against_pydantic_schema() -> None:
    """The exact dict the JS form sends parses cleanly as ConfiguratorPayload."""
    # Arrange + Act — Pydantic raises on any drift (missing field, wrong enum value)
    payload = ConfiguratorPayload.model_validate(JS_PAYLOAD)

    # Assert — round-trip values land on the right enum members
    assert payload.energy_source.value == "nuclear"
    assert payload.primary_workload.value == "ai_training"
    assert payload.gpu_variant.value == "h100_sxm"
    assert payload.grid_connection.value == "grid_tied"
    assert payload.climate_zone.value == "temperate"
    assert payload.deployment_context.value == "commercial"
    assert payload.ems_mode.value == "sim"
    assert payload.aws_partition.value == "standard"


def test_configurator_js_payload_covers_every_select_enum_value() -> None:
    """Every <option value="..."> in arc-node.html is a valid enum member.

    We can't scrape the HTML cross-repo, but we can lock the full enum
    surface on the Python side: if a new enum member lands without a
    matching <option> in the website (or vice-versa), this test gets
    updated and the discrepancy surfaces in code review.
    """
    # Mirror of every <option value="..."> in arc-node.html
    js_select_values: dict[str, set[str]] = {
        "energy_source": {"nuclear", "solar", "grid_hybrid", "off_grid"},
        "primary_workload": {"ai_training", "ai_inference", "mixed"},
        "gpu_variant": {"h100_sxm", "b200"},
        "grid_connection": {"none", "grid_tied", "grid_backup"},
        "climate_zone": {"temperate", "desert", "arctic", "tropical"},
        "deployment_context": {
            "commercial",
            "research",
            "sovereign_government",
            "defense_forward",
        },
        "ems_mode": {"sim", "live"},
        "aws_partition": {"standard", "govcloud", "none"},
    }

    # Each set must equal the Python enum's full value surface
    for field, js_values in js_select_values.items():
        py_enum = ConfiguratorPayload.model_fields[field].annotation
        assert py_enum is not None
        py_values = {member.value for member in py_enum}  # type: ignore[union-attr]
        assert (
            js_values == py_values
        ), f"{field}: html has {js_values}, python has {py_values}"
