"""SesService — async aioboto3 wrapper for delivery email send.

v0 walks the SES `send_email` happy path. Email body is plain text with the
artifact URLs; HTML templating is v1.
"""

import contextlib
import logging
from typing import Final

import aioboto3
from pydantic import BaseModel

DEFAULT_REGION: Final[str] = "us-east-1"


class SesServiceConfig(BaseModel):
    """Just the bits the SES client needs."""

    endpoint_url: str | None
    sender_email: str
    region: str = DEFAULT_REGION


class SesService:
    """aioboto3 SES client — sends the operator delivery email."""

    def __init__(self, *, config: SesServiceConfig) -> None:
        self._endpoint_url = config.endpoint_url
        self._sender = config.sender_email
        self._region = config.region
        self._session = aioboto3.Session()

    async def verify_sender(self) -> None:
        """Verify the sender identity (LocalStack requires this; real SES one-time)."""
        async with self._client() as ses:
            # already-verified raises; we don't care.
            with contextlib.suppress(Exception):
                await ses.verify_email_identity(EmailAddress=self._sender)

    async def send_delivery_email(
        self, *, to: str, subject: str, body_text: str
    ) -> str:
        """Send a plain-text delivery email; return the SES MessageId."""
        async with self._client() as ses:
            resp = await ses.send_email(
                Source=self._sender,
                Destination={"ToAddresses": [to]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": body_text, "Charset": "UTF-8"}},
                },
            )
        message_id = resp["MessageId"]
        logging.info(
            "ses send: to=%s subject=%r message_id=%s", to, subject, message_id
        )
        return message_id

    def _client(self):  # noqa: ANN202
        # Reason: same as S3Service — pass test creds to LocalStack only.
        kwargs: dict[str, object] = {
            "endpoint_url": self._endpoint_url,
            "region_name": self._region,
        }
        if self._endpoint_url is not None:
            kwargs["aws_access_key_id"] = "test"  # nosec B105 — LocalStack
            kwargs["aws_secret_access_key"] = "test"  # noqa: S105  # nosec B105
        return self._session.client("ses", **kwargs)
