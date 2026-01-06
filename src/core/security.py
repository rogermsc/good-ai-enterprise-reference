"""
Security context and authentication utilities.

This module provides authentication context extraction from HTTP headers.
In production, replace header-based auth with OAuth 2.0 / OIDC.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


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

    # Set of all valid role values for validation
    VALID_ROLES: frozenset[str] = frozenset({
        SUPPORT_AGENT,
        SUPPORT_LEAD,
        ADMIN,
        SECURITY,
        COMPLIANCE,
    })

    @classmethod
    def is_valid(cls, role: str) -> bool:
        """Check if a role name is a valid predefined role."""
        return role in cls.VALID_ROLES


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

    # Parse roles from comma-separated header - validate against known roles
    valid_roles: list[str] = []
    for role in roles_header.split(","):
        role = role.strip()
        if role and Roles.is_valid(role):
            valid_roles.append(role)

    return SecurityContext(
        user_id=user_id,
        tenant_id=tenant_id,
        roles=tuple(valid_roles),
    )


# FastAPI security scheme for Bearer token authentication
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> SecurityContext:
    """
    FastAPI dependency for extracting the current user from a request.

    Attempts JWT authentication first, then falls back to header-based auth.

    Usage:
        @app.get("/protected")
        async def protected(user: Annotated[SecurityContext, Depends(get_current_user)]):
            return {"user": user.user_id}

    Raises:
        HTTPException: If authentication fails
    """
    # Try JWT authentication first if Bearer token is provided
    if credentials and credentials.credentials:
        # Import here to avoid circular imports
        from src.core.auth import JWTService
        from src.core.observability import get_logger

        logger = get_logger()

        try:
            jwt_service = JWTService()
            payload = jwt_service.validate_token(credentials.credentials)

            # Validate role strings against known roles
            valid_roles: list[str] = []
            for role_name in payload.roles:
                if Roles.is_valid(role_name):
                    valid_roles.append(role_name)
                else:
                    logger.warning("unknown_role_in_token", role=role_name)

            return SecurityContext(
                user_id=payload.user_id,
                tenant_id=payload.tenant_id,
                roles=tuple(valid_roles),
            )
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # Fall back to header-based authentication
    return get_security_context(request)
