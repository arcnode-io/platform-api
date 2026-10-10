"""Unit tests for the Site page — the order lands as the same files the
cloud's UserData writes, and a box with no order says so."""

import shutil
from pathlib import Path

import pytest
import yaml

from src.wizard.site_fixtures import TEST_ORDER, make_site_service
from src.wizard.site_service import SiteStepNotAvailableError
from src.wizard.wizard_fixtures import tracker
from src.wizard.wizard_record import Deployment


def _yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text())


def test_saves_the_orders_site_for_every_ems_container(tmp_path: Path) -> None:
    # Arrange
    service = make_site_service(tmp_path)
    ems = tmp_path / "opt-arcnode"

    # Act
    actual = service.apply()

    # Assert
    assert actual.verified, [c for c in actual.checks if not c.ok]
    assert (ems / "dtm.json").read_bytes() == (TEST_ORDER / "dtm.json").read_bytes()
    assert _yaml(ems / "gateway-cfg.customer.yml") == {"site_id": "test_site"}
    assert _yaml(ems / "hmi-cfg.customer.yml") == {
        "siteId": "test_site",
        "deploymentName": "test_site",
        "deviceApiUri": "/api",
        "chatApiUri": "",
        "mqttUri": "",
    }
    assert _yaml(ems / "analyst-cfg.customer.yml") == {
        "site_id": "test_site",
        "market": {"wholesale_market": "ercot", "settlement_point": "HB_HOUSTON"},
    }
    assert "site" in tracker(tmp_path).completed()


def test_keeps_the_ollama_pages_settings_in_the_analyst_cfg(tmp_path: Path) -> None:
    # Arrange: the Ollama page ran first
    service = make_site_service(tmp_path)
    analyst = tmp_path / "opt-arcnode" / "analyst-cfg.customer.yml"
    settings = {
        "llm_provider": "ollama",
        "ollama_base_url": "http://172.23.0.1:11434/v1",
        "ollama_chat_model": "gemma4:26b",
        "ollama_embedding_model": "qwen3-embedding:4b-ctx8192",
    }
    analyst.parent.mkdir(parents=True)
    analyst.write_text(yaml.safe_dump({"settings": settings}))

    # Act
    actual = service.apply()

    # Assert
    assert actual.verified
    assert _yaml(analyst) == {
        "site_id": "test_site",
        "market": {"wholesale_market": "ercot", "settlement_point": "HB_HOUSTON"},
        "settings": settings,
    }


def test_no_settlement_point_means_no_market_block(tmp_path: Path) -> None:
    # Arrange: same rule as the cloud — no pricing node, nothing to query
    order = tmp_path / "off-grid-order"
    shutil.copytree(TEST_ORDER, order)
    (order / "site.yml").write_text("site_id: remote_site\n")
    service = make_site_service(tmp_path, order=order)

    # Act
    actual = service.apply()

    # Assert
    assert actual.verified
    assert _yaml(tmp_path / "opt-arcnode" / "analyst-cfg.customer.yml") == {
        "site_id": "remote_site"
    }


def test_a_box_with_no_order_says_where_to_get_one(tmp_path: Path) -> None:
    # Arrange: installed from the generic base ISO
    service = make_site_service(tmp_path, order=None)

    # Act
    actual = service.apply()

    # Assert
    assert not actual.verified
    assert [(c.name, c.ok) for c in actual.checks] == [("Order on this box", False)]
    assert "delivery portal" in actual.checks[0].detail
    assert not (tmp_path / "opt-arcnode").exists()
    assert "site" not in tracker(tmp_path).completed()


def test_cloud_has_no_site_page(tmp_path: Path) -> None:
    # Arrange
    service = make_site_service(tmp_path, deployment=Deployment.CLOUD)

    # Act / Assert
    with pytest.raises(SiteStepNotAvailableError):
        service.apply()
