# Good AI SDK

Python SDK for the Good AI Enterprise Platform.

## Installation

```bash
pip install goodai-sdk
```

## Quick Start

```python
from goodai import GoodAIClient

# Initialize the client
client = GoodAIClient(
    base_url="https://api.goodai.example.com",
    api_key="your-api-key",
    tenant_id="your-tenant-id",
)

# Set user context
client.set_user_context(
    user_id="agent-123",
    roles=["support_agent"],
)
```

## Async Usage

```python
async with GoodAIClient(base_url="https://api.example.com") as client:
    # Authenticate
    await client.authenticate(username="user", password="pass")

    # Check health
    health = await client.health()
    print(f"API Status: {health.status}")

    # Triage a ticket
    result = await client.tickets.triage(
        subject="Cannot login to my account",
        body="I've tried resetting my password but it doesn't work.",
    )

    print(f"Severity: {result.severity}")
    print(f"Suggested Response: {result.suggested_response}")
```

## Ticket Triage

The SDK provides AI-powered ticket triage with automatic PII redaction:

```python
result = await client.tickets.triage(
    subject="Billing issue with my subscription",
    body="My credit card ending in 1234 was charged twice. Please refund.",
    customer_email="customer@example.com",
)

# Result includes:
# - severity: "P2"
# - category: "billing"
# - suggested_response: "..."
# - recommended_actions: ["verify_charge", "process_refund"]
# - pii_detected: True (credit card was redacted before LLM processing)
```

## Human-in-the-Loop Approvals

For high-risk actions, the platform requires human approval:

```python
# List pending approvals
pending = await client.approvals.list_pending()
for approval in pending.approvals:
    print(f"[{approval.priority}] {approval.action}: {approval.context}")

# Approve a request
result = await client.approvals.approve(
    approval_id="abc-123",
    notes="Verified customer identity, approved.",
)

# Reject a request
result = await client.approvals.reject(
    approval_id="xyz-456",
    notes="Insufficient justification for refund.",
)
```

## Error Handling

```python
from goodai.models import APIError

try:
    result = await client.tickets.triage(
        subject="Test",
        body="Test ticket",
    )
except APIError as e:
    print(f"API Error [{e.status_code}]: {e.message}")
```

## Sync Usage

For non-async contexts, use the sync methods:

```python
client = GoodAIClient(base_url="https://api.example.com")
client.set_api_key("your-api-key")

# Sync methods have _sync suffix
health = client.health_sync()
result = client.tickets.triage_sync(
    subject="Help needed",
    body="I have a problem...",
)
```

## Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `base_url` | API base URL | Required |
| `api_key` | API key for authentication | None |
| `tenant_id` | Tenant identifier | "default" |
| `timeout` | Request timeout (seconds) | 30.0 |
| `verify_ssl` | Verify SSL certificates | True |

## License

MIT License
