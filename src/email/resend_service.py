"""ResendService — the delivery email through Resend's HTTP API.

Same two calls the orchestrator makes on SesService, so the provider is a
config switch (cfg.yml `email_provider`). Plain-text body, like SES v0.
"""

import logging
from typing import Final

import httpx

SEND_URL: Final[str] = "https://api.resend.com/emails"


class ResendService:
    """Sends the operator delivery email with Resend. The key never leaves the header."""

    def __init__(
        self,
        *,
        api_key: str,
        sender_email: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._sender = sender_email
        # Reason: `transport` is test-only DI (httpx.MockTransport); None lets httpx use the network.
        self._transport = transport

    async def verify_sender(self) -> None:
        """Nothing to do: Resend verifies the sending domain, not an address."""

    async def send_delivery_email(
        self, *, to: str, subject: str, body_text: str
    ) -> str:
        """Send a plain-text delivery email; return Resend's email id."""
        async with httpx.AsyncClient(transport=self._transport) as http:
            response = await http.post(
                SEND_URL,
                headers=self._headers,
                json={
                    "from": self._sender,
                    "to": [to],
                    "subject": subject,
                    "text": body_text,
                },
            )
        if response.is_error:
            raise RuntimeError(
                f"resend send failed ({response.status_code}): "
                f"{response.json().get('message', response.text)}"
            )
        message_id = str(response.json()["id"])
        logging.info("resend send: to=%s subject=%r id=%s", to, subject, message_id)
        return message_id
