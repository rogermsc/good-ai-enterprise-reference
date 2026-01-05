"""
Tickets service for ticket triage and management.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from goodai.models import TicketTriageResult

if TYPE_CHECKING:
    from goodai.client import GoodAIClient


class TicketsService:
    """
    Service for ticket operations.

    Example:
        result = await client.tickets.triage(
            subject="Cannot access account",
            body="I forgot my password and the reset link doesn't work.",
        )
        print(f"Severity: {result.severity}")
    """

    def __init__(self, client: GoodAIClient) -> None:
        self._client = client

    async def triage(
        self,
        subject: str,
        body: str,
        customer_email: str | None = None,
        customer_name: str | None = None,
        priority_hint: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TicketTriageResult:
        """
        Triage a support ticket using AI.

        The AI analyzes the ticket and provides:
        - Severity classification (P0-P4)
        - Category identification
        - Suggested response
        - Recommended actions

        PII in the ticket is automatically detected and redacted
        before being sent to the LLM.

        Args:
            subject: Ticket subject line
            body: Full ticket body
            customer_email: Optional customer email
            customer_name: Optional customer name
            priority_hint: Optional priority hint from caller
            metadata: Additional metadata

        Returns:
            TicketTriageResult with analysis
        """
        payload = {
            "subject": subject,
            "body": body,
            "metadata": metadata or {},
        }

        if customer_email:
            payload["customer_email"] = customer_email
        if customer_name:
            payload["customer_name"] = customer_name
        if priority_hint:
            payload["priority_hint"] = priority_hint

        data = await self._client._request(
            "POST",
            "/tickets/triage",
            json=payload,
        )

        return TicketTriageResult(**data)

    def triage_sync(
        self,
        subject: str,
        body: str,
        customer_email: str | None = None,
        customer_name: str | None = None,
        priority_hint: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TicketTriageResult:
        """
        Triage a support ticket using AI (sync version).

        See `triage` for full documentation.
        """
        payload = {
            "subject": subject,
            "body": body,
            "metadata": metadata or {},
        }

        if customer_email:
            payload["customer_email"] = customer_email
        if customer_name:
            payload["customer_name"] = customer_name
        if priority_hint:
            payload["priority_hint"] = priority_hint

        data = self._client._request_sync(
            "POST",
            "/tickets/triage",
            json=payload,
        )

        return TicketTriageResult(**data)
