"""S3Service — async aioboto3 wrapper for artifact archival.

Downloads bytes from an edp-api artifact URL and re-uploads to platform-api's
S3 bucket. Returns the new platform-api S3 URL. Same code in production
(real AWS endpoint) and tests (LocalStack endpoint) — only `endpoint_url` differs.
"""

import logging
from typing import Final

import aioboto3
import httpx

DEFAULT_REGION: Final[str] = "us-east-1"


class S3Service:
    """aioboto3 S3 client — fetches edp-api artifacts and re-archives to our bucket."""

    def __init__(
        self,
        *,
        endpoint_url: str | None,
        bucket: str,
        region: str = DEFAULT_REGION,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._bucket = bucket
        self._region = region
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

    async def upload_html(self, key: str, body: str) -> str:
        """Upload an HTML body under `key`, return the S3 URL."""
        return await self._upload_text(key, body, "text/html; charset=utf-8")

    async def upload_yaml(self, key: str, body: str) -> str:
        """Upload a YAML body under `key`, return the S3 URL."""
        return await self._upload_text(key, body, "application/yaml")

    def generate_presigned_url(
        self, key: str, expiration_seconds: int = 86400
    ) -> str:
        """Generate a presigned GET URL for `key`. Valid for `expiration_seconds` (default: 24h)."""
        # Create a synchronous client for presigned URL generation (boto3 limitation).
        import boto3

        kwargs: dict[str, object] = {
            "endpoint_url": self._endpoint_url,
            "region_name": self._region,
        }
        if self._endpoint_url is not None:
            kwargs["aws_access_key_id"] = "test"  # nosec B105 — LocalStack
            kwargs["aws_secret_access_key"] = "test"  # noqa: S105  # nosec B105
        client = boto3.client("s3", **kwargs)  # type: ignore[var-annotated]
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expiration_seconds,
        )
        logging.info("generated presigned URL for %s (expires in %ds)", key, expiration_seconds)
        return url

    async def _upload_text(self, key: str, body: str, content_type: str) -> str:
        """Common path for text-body uploads. Returns the public URL."""
        async with self._client() as s3:
            await s3.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body.encode("utf-8"),
                ContentType=content_type,
            )
        url = self._public_url(key)
        logging.info("uploaded %d bytes %s → %s", len(body), content_type, url)
        return url

    def _client(self):  # noqa: ANN202 — async context manager type is ugly to spell
        # LocalStack ignores credentials but boto3 still requires non-empty values;
        # in prod we pass nothing so the standard credential chain takes over.
        kwargs: dict[str, object] = {
            "endpoint_url": self._endpoint_url,
            "region_name": self._region,
        }
        if self._endpoint_url is not None:
            kwargs["aws_access_key_id"] = "test"  # nosec B105 — LocalStack
            kwargs["aws_secret_access_key"] = "test"  # noqa: S105  # nosec B105
        return self._session.client("s3", **kwargs)

    def _public_url(self, key: str) -> str:
        """Path-style URL for LocalStack; virtual-host style for real S3."""
        if self._endpoint_url:
            return f"{self._endpoint_url.rstrip('/')}/{self._bucket}/{key}"
        return f"https://{self._bucket}.s3.{self._region}.amazonaws.com/{key}"
