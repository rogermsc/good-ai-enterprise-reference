"""
Good AI Enterprise Platform SDK.

A Python client library for interacting with the Good AI Enterprise Platform API.

Example:
    from goodai import GoodAIClient

    client = GoodAIClient(
        base_url="https://api.goodai.example.com",
        api_key="your-api-key",
    )

    # Triage a support ticket
    result = await client.tickets.triage(
        subject="Cannot login to my account",
        body="I've tried resetting my password but still can't access my account.",
    )

    print(f"Severity: {result.severity}")
    print(f"Suggested Response: {result.suggested_response}")
"""

from goodai.client import GoodAIClient
from goodai.models import (
    ApprovalRequest,
    ApprovalStatus,
    HealthStatus,
    TicketTriageResult,
    TokenResponse,
)

__version__ = "1.0.0"
__all__ = [
    "GoodAIClient",
    "ApprovalRequest",
    "ApprovalStatus",
    "HealthStatus",
    "TicketTriageResult",
    "TokenResponse",
]
