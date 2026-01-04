"""
Security context and authentication utilities.

This module provides authentication context extraction from HTTP headers.
In production, replace header-based auth with OAuth 2.0 / OIDC.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class SecurityContext:
    """
    Authentication and authorization context for a request.

    Attributes:
        user_id: Authenticated user identifier
        tenant_id: Organization/tenant identifier
        roles: List of roles assigned to the user
    """

    user_id: str
    tenant_id: str
    roles: tuple[str, ...] = field(default_factory=tuple)

    def has_role(self, role: str) -> bool:
        """Check if user has a specific role."""
        return role in self.roles

    def has_any_role(self, roles: Sequence[str]) -> bool:
        """Check if user has any of the specified roles."""
        return any(role in self.roles for role in roles)

    def has_all_roles(self, roles: Sequence[str]) -> bool:
        """Check if user has all of the specified roles."""
        return all(role in self.roles for role in roles)


# Predefined roles for the demo
class Roles:
    """Standard roles for RBAC."""

    SUPPORT_AGENT = "support_agent"
    SUPPORT_LEAD = "support_lead"
    ADMIN = "admin"
    SECURITY = "security"
    COMPLIANCE = "compliance"


def get_security_context(request: Request) -> SecurityContext:
    """
    Extract security context from request headers.

    Headers:
        X-User-Id: User identifier (required)
        X-Tenant-Id: Tenant identifier (required)
        X-Roles: Comma-separated list of roles (optional)

    In production, replace with JWT validation or OAuth 2.0 token introspection.

    Raises:
        HTTPException: If required headers are missing
    """
    user_id = request.headers.get("X-User-Id")
    tenant_id = request.headers.get("X-Tenant-Id")
    roles_header = request.headers.get("X-Roles", "")

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Missing X-User-Id header",
        )

    if not tenant_id:
        raise HTTPException(
            status_code=401,
            detail="Missing X-Tenant-Id header",
        )

    # Parse roles from comma-separated header
    roles = tuple(role.strip() for role in roles_header.split(",") if role.strip())

    return SecurityContext(
        user_id=user_id,
        tenant_id=tenant_id,
        roles=roles,
    )
