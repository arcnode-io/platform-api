"""S3Service — async aioboto3 wrapper for artifact archival.

Downloads bytes from an edp-api artifact URL and re-uploads to platform-api's
S3 bucket. Returns the new platform-api S3 URL. Same code in production
(real AWS endpoint) and tests (LocalStack endpoint) — only `endpoint_url` differs.
"""

import logging
from typing import Final

import aioboto3
import httpx
from pydantic import BaseModel

DEFAULT_REGION: Final[str] = "us-east-1"


class S3ServiceConfig(BaseModel):
    """Just the bits the S3 client needs."""

    endpoint_url: str | None
    bucket: str
    region: str = DEFAULT_REGION


class S3Service:
    """aioboto3 S3 client — fetches edp-api artifacts and re-archives to our bucket."""

    def __init__(self, *, config: S3ServiceConfig) -> None:
        self._endpoint_url = config.endpoint_url
        self._bucket = config.bucket
        self._region = config.region
        self._session = aioboto3.Session()

    async def ensure_bucket(self) -> None:
        """Create the bucket if it doesn't exist (idempotent). Tests use this on setup."""
        async with self._client() as s3:
            try:
                await s3.head_bucket(Bucket=self._bucket)
            except Exception:
                logging.info("creating S3 bucket: %s", self._bucket)
                await s3.create_bucket(Bucket=self._bucket)

    async def archive_from_url(
        self, source_url: str, key: str, content_type: str = "application/json"
    ) -> str:
        """Fetch `source_url` over HTTP, upload to S3 under `key`, return the S3 URL."""
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(source_url)
            resp.raise_for_status()
            body = resp.content

        async with self._client() as s3:
            await s3.put_object(
                Bucket=self._bucket, Key=key, Body=body, ContentType=content_type
            )
        url = self._public_url(key)
        logging.info("archived %d bytes %s → %s", len(body), source_url, url)
        return url

    def _client(self):  # noqa: ANN202 — async context manager type is ugly to spell
        # Reason: LocalStack ignores credentials but boto3 still requires non-empty
        # values; in prod we pass nothing so the standard credential chain (IAM role,
        # env vars, ~/.aws/credentials) takes over.
        kwargs: dict[str, object] = {
            "endpoint_url": self._endpoint_url,
            "region_name": self._region,
        }
        if self._endpoint_url is not None:
            kwargs["aws_access_key_id"] = "test"  # nosec B105 — LocalStack
            kwargs["aws_secret_access_key"] = "test"  # noqa: S105  # nosec B105
        return self._session.client("s3", **kwargs)

    def _public_url(self, key: str) -> str:
        """Build the public S3 URL for the bucket+key.

        Production uses the real S3 path-style URL; tests use the LocalStack endpoint
        with the bucket as the path prefix (so the URL is reachable from the host).
        """
        base = (
            self._endpoint_url
            or f"https://{self._bucket}.s3.{self._region}.amazonaws.com"
        )
        if self._endpoint_url:
            # LocalStack path-style: http://localhost:4566/<bucket>/<key>
            return f"{base.rstrip('/')}/{self._bucket}/{key}"
        return f"{base}/{key}"
