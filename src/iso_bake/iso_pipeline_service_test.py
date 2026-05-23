"""Tests for IsoPipelineService — gitlab pipeline trigger + status."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.iso_bake.iso_pipeline_service import (
    IsoPipelineService,
    PipelineStatus,
)

ORDER_ID = "11111111-2222-3333-4444-555555555555"
OVERLAY_URL = "https://arcnode-public.s3.amazonaws.com/orders/123/iso-overlay/?sig=x"
TRIGGER_TOKEN = "glab-trigger-secret"  # noqa: S105 — test fixture
PROJECT_PATH = "arcnode-io/platform-ems-iso"


def _service(httpx_client: object) -> IsoPipelineService:
    return IsoPipelineService(
        gitlab_url="https://gitlab.com",
        project_path=PROJECT_PATH,
        trigger_token=TRIGGER_TOKEN,
        iso_bucket_prefix="iso/customers",
        httpx_client=httpx_client,
    )


@pytest.mark.asyncio
async def test_trigger_posts_to_gitlab_with_order_vars() -> None:
    """trigger() POSTs to the project's pipeline-trigger endpoint with our vars."""
    # Arrange — httpx client mocked
    client = MagicMock()
    client.post = AsyncMock(
        return_value=MagicMock(
            status_code=201,
            json=MagicMock(return_value={"id": 999, "status": "pending"}),
        )
    )
    svc = _service(client)

    # Act
    pid = await svc.trigger(order_id=ORDER_ID, overlay_url=OVERLAY_URL)

    # Assert — pipeline id round-trips
    assert pid == 999

    # POST URL must url-encode the project path slash
    call = client.post.call_args
    assert (
        call.args[0]
        == "https://gitlab.com/api/v4/projects/arcnode-io%2Fplatform-ems-iso/trigger/pipeline"
    )
    # Form body carries the trigger token, ref=main, and our ORDER_ID + OVERLAY_URL
    data = call.kwargs["data"]
    assert data["token"] == TRIGGER_TOKEN
    assert data["ref"] == "main"
    assert data["variables[ORDER_ID]"] == ORDER_ID
    assert data["variables[OVERLAY_URL]"] == OVERLAY_URL


@pytest.mark.asyncio
async def test_status_maps_gitlab_response_to_enum() -> None:
    """status() turns gitlab's free-text status into our enum."""
    # Arrange — gitlab returns 'success' for a finished build
    client = MagicMock()
    client.get = AsyncMock(
        return_value=MagicMock(
            status_code=200,
            json=MagicMock(return_value={"status": "success"}),
        )
    )
    svc = _service(client)

    # Act
    status = await svc.status(pipeline_id=999)

    # Assert
    assert status == PipelineStatus.SUCCESS
    # Right URL hit
    assert (
        client.get.call_args.args[0]
        == "https://gitlab.com/api/v4/projects/arcnode-io%2Fplatform-ems-iso/pipelines/999"
    )


@pytest.mark.asyncio
async def test_status_unknown_string_becomes_running() -> None:
    """Anything not success/failed/canceled is treated as still running.

    Gitlab also emits 'created', 'waiting_for_resource', 'preparing', 'pending',
    'running', 'scheduled' — for our purposes they're all RUNNING (not done).
    """
    # Arrange
    client = MagicMock()
    client.get = AsyncMock(
        return_value=MagicMock(
            status_code=200,
            json=MagicMock(return_value={"status": "preparing"}),
        )
    )
    svc = _service(client)

    # Act + Assert
    assert await svc.status(pipeline_id=42) == PipelineStatus.RUNNING


def test_iso_url_returns_well_known_s3_key() -> None:
    """ISO output path is deterministic per order_id — portal links to it directly."""
    # Arrange
    svc = _service(httpx_client=MagicMock())

    # Act
    url = svc.iso_key(order_id=ORDER_ID)

    # Assert
    assert url == f"iso/customers/{ORDER_ID}/arcnode-ems-{ORDER_ID}.iso"
