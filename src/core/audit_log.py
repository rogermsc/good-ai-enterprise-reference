"""
Audit Logging for compliance and observability.

The audit logger records all AI operations with:
- Redacted inputs (never raw PII)
- Token maps for restoration (encrypted at rest)
- Policy decisions
- Latency and cost tracking
- Timestamps

All records are append-only for compliance.
"""

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import asyncpg

from src.core.encryption import decrypt_token_map, encrypt_token_map

# Input validation patterns
_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]{1,100}$")


class ValidationError(Exception):
    """Raised when input validation fails."""

    pass


def validate_id(value: str, field_name: str) -> str:
    """
    Validate an ID field for safe database operations.

    Args:
        value: The ID value to validate
        field_name: Name of the field for error messages

    Returns:
        The validated value

    Raises:
        ValidationError: If validation fails
    """
    if not value:
        raise ValidationError(f"{field_name} cannot be empty")
    if not _ID_PATTERN.match(value):
        raise ValidationError(
            f"Invalid {field_name}: must be 1-100 alphanumeric characters, "
            f"underscores, or hyphens"
        )
    return value


@dataclass
class AuditLogPayload:
    """Payload for audit log entries."""

    ticket_id: str
    user_id: str
    tenant_id: str
    redacted_input: str
    token_map: dict[str, str]
    model_name: str
    provider: str
    severity: str
    actions: list[str]
    policy_decision: dict[str, Any]
    final_response: str | None = None
    latency_ms: int = 0
    cost_estimate: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditLogEntry:
    """Complete audit log entry with generated fields."""

    audit_id: str
    ticket_id: str
    user_id: str
    tenant_id: str
    redacted_input: str
    token_map: dict[str, str]
    model_name: str
    provider: str
    severity: str
    actions: list[str]
    policy_decision: dict[str, Any]
    final_response: str | None
    latency_ms: int
    cost_estimate: float
    created_at: datetime
    metadata: dict[str, Any]


class AuditLogger:
    """
    Audit logging service.

    Writes immutable audit records to PostgreSQL.
    All operations are append-only for compliance.

    Example:
        logger = AuditLogger()

        audit_id = await logger.write(
            conn=db_connection,
            payload=AuditLogPayload(
                ticket_id="TKT-001",
                user_id="agent-1",
                tenant_id="acme",
                redacted_input="Customer [PII_EMAIL_1] reports...",
                token_map={"[PII_EMAIL_1]": "user@example.com"},
                model_name="gpt-4",
                provider="openai",
                severity="P2",
                actions=["classify", "respond"],
                policy_decision={"allowed": True, "requires_approval": False},
            )
        )
    """

    async def write(
        self,
        conn: asyncpg.Connection,
        payload: AuditLogPayload,
    ) -> str:
        """
        Write audit log entry.

        Args:
            conn: Database connection
            payload: Audit log payload

        Returns:
            Generated audit_id (UUID)
        """
        audit_id = str(uuid.uuid4())

        # Validate IDs
        validate_id(payload.ticket_id, "ticket_id")
        validate_id(payload.tenant_id, "tenant_id")

        # Encrypt token_map before storage for PII protection
        encrypted_token_map = encrypt_token_map(payload.token_map)

        await conn.execute(
            """
            INSERT INTO audit_logs (
                audit_id,
                ticket_id,
                user_id,
                tenant_id,
                redacted_input,
                token_map,
                model_name,
                provider,
                severity,
                actions,
                policy_decision,
                final_response,
                latency_ms,
                cost_estimate,
                metadata
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15
            )
            """,
            audit_id,
            payload.ticket_id,
            payload.user_id,
            payload.tenant_id,
            payload.redacted_input,
            encrypted_token_map,  # Now encrypted
            payload.model_name,
            payload.provider,
            payload.severity,
            json.dumps(payload.actions),
            json.dumps(payload.policy_decision),
            payload.final_response,
            payload.latency_ms,
            payload.cost_estimate,
            json.dumps(payload.metadata),
        )

        return audit_id

    async def get_by_id(
        self,
        conn: asyncpg.Connection,
        audit_id: str,
    ) -> AuditLogEntry | None:
        """
        Retrieve audit log entry by ID.

        Args:
            conn: Database connection
            audit_id: Audit log identifier

        Returns:
            AuditLogEntry or None if not found
        """
        row = await conn.fetchrow(
            """
            SELECT
                audit_id,
                ticket_id,
                user_id,
                tenant_id,
                redacted_input,
                token_map,
                model_name,
                provider,
                severity,
                actions,
                policy_decision,
                final_response,
                latency_ms,
                cost_estimate,
                created_at,
                metadata
            FROM audit_logs
            WHERE audit_id = $1
            """,
            audit_id,
        )

        if row is None:
            return None

        return self._row_to_entry(row)

    async def get_by_ticket(
        self,
        conn: asyncpg.Connection,
        ticket_id: str,
        tenant_id: str,
    ) -> list[AuditLogEntry]:
        """
        Retrieve all audit logs for a ticket.

        Args:
            conn: Database connection
            ticket_id: Ticket identifier
            tenant_id: Tenant identifier (for isolation)

        Returns:
            List of AuditLogEntry sorted by created_at desc

        Raises:
            ValidationError: If ticket_id or tenant_id are invalid
        """
        # Validate inputs
        validate_id(ticket_id, "ticket_id")
        validate_id(tenant_id, "tenant_id")

        rows = await conn.fetch(
            """
            SELECT
                audit_id,
                ticket_id,
                user_id,
                tenant_id,
                redacted_input,
                token_map,
                model_name,
                provider,
                severity,
                actions,
                policy_decision,
                final_response,
                latency_ms,
                cost_estimate,
                created_at,
                metadata
            FROM audit_logs
            WHERE ticket_id = $1 AND tenant_id = $2
            ORDER BY created_at DESC
            """,
            ticket_id,
            tenant_id,
        )

        return [self._row_to_entry(row) for row in rows]

    async def get_by_tenant(
        self,
        conn: asyncpg.Connection,
        tenant_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLogEntry]:
        """
        Retrieve audit logs for a tenant.

        Args:
            conn: Database connection
            tenant_id: Tenant identifier
            limit: Maximum number of entries
            offset: Pagination offset

        Returns:
            List of AuditLogEntry sorted by created_at desc
        """
        rows = await conn.fetch(
            """
            SELECT
                audit_id,
                ticket_id,
                user_id,
                tenant_id,
                redacted_input,
                token_map,
                model_name,
                provider,
                severity,
                actions,
                policy_decision,
                final_response,
                latency_ms,
                cost_estimate,
                created_at,
                metadata
            FROM audit_logs
            WHERE tenant_id = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            tenant_id,
            limit,
            offset,
        )

        return [self._row_to_entry(row) for row in rows]

    def _row_to_entry(self, row: asyncpg.Record) -> AuditLogEntry:
        """Convert database row to AuditLogEntry."""
        # Decrypt token_map - it's stored encrypted
        token_map: dict[str, str] = {}
        if row["token_map"]:
            try:
                # New format: encrypted string
                token_map = decrypt_token_map(row["token_map"])
            except Exception:
                # Fallback for legacy unencrypted JSON data
                try:
                    token_map = json.loads(row["token_map"])
                except json.JSONDecodeError:
                    token_map = {}

        return AuditLogEntry(
            audit_id=row["audit_id"],
            ticket_id=row["ticket_id"],
            user_id=row["user_id"],
            tenant_id=row["tenant_id"],
            redacted_input=row["redacted_input"],
            token_map=token_map,
            model_name=row["model_name"],
            provider=row["provider"],
            severity=row["severity"],
            actions=json.loads(row["actions"]) if row["actions"] else [],
            policy_decision=json.loads(row["policy_decision"]) if row["policy_decision"] else {},
            final_response=row["final_response"],
            latency_ms=row["latency_ms"],
            cost_estimate=float(row["cost_estimate"]) if row["cost_estimate"] else 0.0,
            created_at=row["created_at"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )


# Module-level convenience function
async def write_audit_log(
    conn: asyncpg.Connection,
    payload: AuditLogPayload,
) -> str:
    """Convenience function for writing audit logs."""
    logger = AuditLogger()
    return await logger.write(conn, payload)
