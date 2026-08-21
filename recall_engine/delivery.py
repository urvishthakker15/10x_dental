"""Dry-run and Resend delivery adapters."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import EmailContent

LOGGER = logging.getLogger(__name__)


class DeliveryError(RuntimeError):
    pass


class EmailSender(Protocol):
    def send(self, recipient: str, content: EmailContent, idempotency_key: str) -> str:
        """Deliver one message and return the provider's stable message identifier."""


@dataclass
class DryRunSender:
    def send(self, recipient: str, content: EmailContent, idempotency_key: str) -> str:
        """Log recipient, subject, and key without contacting an email provider."""
        LOGGER.info(
            "DRY RUN recipient=%s subject=%r idempotency_key=%s", recipient, content.subject, idempotency_key
        )
        return "dry-run"


@dataclass
class ResendSender:
    api_key: str
    from_address: str

    def send(self, recipient: str, content: EmailContent, idempotency_key: str) -> str:
        """Send text/HTML through Resend using a retry-safe idempotency key."""
        payload = json.dumps(
            {
                "from": self.from_address,
                "to": [recipient],
                "subject": content.subject,
                "text": content.text,
                "html": content.html,
            }
        ).encode("utf-8")
        request = Request(
            "https://api.resend.com/emails",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
                "User-Agent": "recall-outreach-engine/0.1.0",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise DeliveryError(f"Resend HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise DeliveryError(f"Unable to reach Resend: {error.reason}") from error

        message_id = decoded.get("id")
        if not message_id:
            raise DeliveryError(f"Resend response did not include an email id: {decoded}")
        return str(message_id)
