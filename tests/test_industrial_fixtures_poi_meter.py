"""The industrial-fixtures DTM's poi_meter must read registers the mock meter serves.

The mock serves the Schneider ION9000 map (see ems-industrial-fixtures mock-modbus-server
src/registers.rs). A stale embedded template reading 4030 gave IllegalDataAddress on every
poll, so no meter data reached telemetry (found 2026-10-12, defense and commercial e2e).
"""

import json
from pathlib import Path

FIXTURES = (
    Path(__file__).resolve().parents[1] / "src" / "compose" / "industrial-fixtures.json"
)
# The registers registers.rs::holding_registers serves for the poi_meter profile.
MOCK_SERVED_ADDRESSES = {
    3060,
    3150,
    3204,
    3208,
    21330,
    21331,
    21332,
    21333,
    21334,
    21335,
}


def _poi_meter_addresses() -> dict[str, int]:
    measurements = json.loads(FIXTURES.read_text())["templates_used"]["poi_meter"][
        "measurements"
    ]
    return {
        name: m["binding"]["address"]
        for name, m in measurements.items()
        if m.get("binding", {}).get("protocol") == "modbus_tcp"
    }


def test_every_poi_meter_read_hits_a_register_the_mock_serves() -> None:
    # Arrange + Act
    addresses = _poi_meter_addresses()

    # Assert
    unserved = {
        name: a for name, a in addresses.items() if a not in MOCK_SERVED_ADDRESSES
    }
    assert (
        unserved == {}
    ), f"poi_meter reads registers the mock does not serve: {unserved}"
