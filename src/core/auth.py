"""
JWT Authentication for the Enterprise AI Platform.

Provides:
- JWT token generation and validation
- FastAPI dependency for authentication
- Support for RS256 and HS256 algorithms
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.core.config import get_settings
from src.core.observability import get_logger
from src.core.security import Roles, SecurityContext

logger = get_logger()


@dataclass
class TokenPayload:
    """JWT token payload."""

    user_id: str
    tenant_id: str
    roles: list[str]
    exp: datetime
    iat: datetime
    sub: str | None = None
    jti: str | None = None
    metadata: dict[str, Any] | None = None


class JWTService:
    """
    JWT token service for authentication.

    Supports both symmetric (HS256) and asymmetric (RS256) algorithms.

    Example:
        service = JWTService()

        # Generate token
        token = service.create_token(
            user_id="user-123",
            tenant_id="tenant-456",
            roles=["support_agent"],
        )

        # Validate token
        payload = service.validate_token(token)
    """

    def __init__(
        self,
        secret_key: str | None = None,
        algorithm: str = "HS256",
        access_token_expire_minutes: int = 30,
        refresh_token_expire_days: int = 7,
    ):
        """
        Initialize JWT service.

        Args:
            secret_key: Secret key for signing (required for HS256)
            algorithm: JWT algorithm (HS256 or RS256)
            access_token_expire_minutes: Access token expiry
            refresh_token_expire_days: Refresh token expiry
        """
        settings = get_settings()
        self.secret_key = secret_key or settings.jwt_secret_key
        self.algorithm = algorithm
        self.access_token_expire_minutes = access_token_expire_minutes
        self.refresh_token_expire_days = refresh_token_expire_days

        if not self.secret_key:
            settings = get_settings()
            if settings.environment == "production":
                raise ValueError("JWT_SECRET_KEY must be configured in production environment")
            logger.warning(
                "jwt_secret_not_configured",
                message="Using random secret - tokens won't survive restart",
            )
            self.secret_key = secrets.token_urlsafe(32)

    def create_token(
        self,
        user_id: str,
        tenant_id: str,
        roles: list[str],
        expires_delta: timedelta | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Create a JWT access token.

        Args:
            user_id: User identifier
            tenant_id: Tenant/organization identifier
            roles: List of role names
            expires_delta: Custom expiration time
            metadata: Additional claims to include

        Returns:
            Encoded JWT token string
        """
        now = datetime.now(UTC)
        expire = now + (expires_delta or timedelta(minutes=self.access_token_expire_minutes))

        payload = {
            "sub": user_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "roles": roles,
            "iat": now,
            "exp": expire,
            "jti": secrets.token_urlsafe(16),
        }

        if metadata:
            payload["metadata"] = metadata

        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

        logger.info(
            "jwt_token_created",
            user_id=user_id,
            tenant_id=tenant_id,
            expires_at=expire.isoformat(),
        )

        return token

    def create_refresh_token(
        self,
        user_id: str,
        tenant_id: str,
    ) -> str:
        """
        Create a JWT refresh token.

        Refresh tokens have longer expiry and can be used to obtain
        new access tokens.
        """
        return self.create_token(
            user_id=user_id,
            tenant_id=tenant_id,
            roles=[],  # Refresh tokens don't carry roles
            expires_delta=timedelta(days=self.refresh_token_expire_days),
            metadata={"type": "refresh"},
        )

    def validate_token(self, token: str) -> TokenPayload:
        """
        Validate and decode a JWT token.

        Args:
            token: Encoded JWT token

        Returns:
            TokenPayload with decoded claims

        Raises:
            HTTPException: If token is invalid or expired
        """
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
            )

            return TokenPayload(
                user_id=payload["user_id"],
                tenant_id=payload["tenant_id"],
                roles=payload.get("roles", []),
                exp=datetime.fromtimestamp(payload["exp"], tz=UTC),
                iat=datetime.fromtimestamp(payload["iat"], tz=UTC),
                sub=payload.get("sub"),
                jti=payload.get("jti"),
                metadata=payload.get("metadata"),
            )

        except jwt.ExpiredSignatureError:
            logger.warning("jwt_token_expired")
            raise HTTPException(
                status_code=401,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.InvalidTokenError as e:
            logger.warning("jwt_token_invalid", error=str(e))
            raise HTTPException(
                status_code=401,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def refresh_access_token(self, refresh_token: str) -> str:
        """
        Create a new access token using a refresh token.

        Args:
            refresh_token: Valid refresh token

        Returns:
            New access token
        """
        payload = self.validate_token(refresh_token)

        # Verify it's a refresh token - must have metadata with type="refresh"
        if not payload.metadata or payload.metadata.get("type") != "refresh":
            raise HTTPException(
                status_code=401,
                detail="Invalid refresh token",
            )

        # Create new access token (need to fetch roles from database)
        # For now, return empty roles - in production, fetch from user service
        return self.create_token(
            user_id=payload.user_id,
            tenant_id=payload.tenant_id,
            roles=[],  # Should be fetched from database
        )


# FastAPI security scheme
bearer_scheme = HTTPBearer(auto_error=False)


async def get_jwt_security_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = None,
) -> SecurityContext:
    """
    FastAPI dependency for JWT authentication.

    Falls back to header-based auth if no JWT token is provided.

    Usage:
        @app.get("/protected")
        async def protected(ctx: SecurityContext = Depends(get_jwt_security_context)):
            return {"user": ctx.user_id}
    """
    # Try JWT authentication first
    if credentials and credentials.credentials:
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

    # Fall back to header-based authentication (for backwards compatibility)
    user_id = request.headers.get("X-User-Id")
    tenant_id = request.headers.get("X-Tenant-Id")
    roles_header = request.headers.get("X-Roles", "")

    if not user_id or not tenant_id:
        raise HTTPException(
            status_code=401,
            detail="Missing authentication. Provide JWT token or X-User-Id/X-Tenant-Id headers",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Parse roles from header - validate against known roles
    valid_roles: list[str] = []
    for role_name in roles_header.split(","):
        role_name = role_name.strip()
        if role_name:
            if Roles.is_valid(role_name):
                valid_roles.append(role_name)
            else:
                logger.warning("unknown_role_in_header", role=role_name)

    return SecurityContext(
        user_id=user_id,
        tenant_id=tenant_id,
        roles=tuple(valid_roles),
    )


# Default JWT service instance
_jwt_service: JWTService | None = None


def get_jwt_service() -> JWTService:
    """Get or create the default JWT service instance."""
    global _jwt_service
    if _jwt_service is None:
        _jwt_service = JWTService()
    return _jwt_service
