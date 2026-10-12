"""Unit tests for S3Service presigned links — signing only, no network."""

import pytest

from src.aws.s3_service import S3Service

PRESIGN_KEY_ID: str = "AKIDPRESIGNTEST"
WEEK_S: int = 604800


@pytest.mark.asyncio
async def test_presigned_link_is_signed_with_the_presign_key_and_lasts_a_week() -> None:
    """Links signed with the long-lived presign key carry its key id and the full 7-day expiry."""
    # Arrange
    s3 = S3Service(
        endpoint_url=None,
        bucket="platform-api-artifacts",
        presign_access_key_id=PRESIGN_KEY_ID,
        presign_secret_access_key="secret-for-test",
    )

    # Act
    url = await s3.generate_presigned_url(
        "orders/abc/arcnode.zip", expiration_seconds=WEEK_S
    )

    # Assert
    assert f"X-Amz-Credential={PRESIGN_KEY_ID}%2F" in url
    assert f"X-Amz-Expires={WEEK_S}" in url
