"""
Authentication API endpoints.

Provides endpoints for:
- Token generation (login)
- Token refresh
- Token validation
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.core.auth import get_jwt_service
from src.core.observability import get_logger

logger = get_logger()
router = APIRouter(prefix="/auth", tags=["authentication"])


class TokenRequest(BaseModel):
    """Request body for token generation."""

    user_id: str = Field(..., description="User identifier", min_length=1)
    tenant_id: str = Field(..., description="Tenant identifier", min_length=1)
    roles: list[str] = Field(default_factory=list, description="User roles")


class TokenResponse(BaseModel):
    """Response containing JWT tokens."""

    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Access token expiry in seconds")


class RefreshRequest(BaseModel):
    """Request body for token refresh."""

    refresh_token: str = Field(..., description="Refresh token")


class TokenInfo(BaseModel):
    """Token validation response."""

    valid: bool
    user_id: str | None = None
    tenant_id: str | None = None
    roles: list[str] = Field(default_factory=list)
    expires_at: str | None = None


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Generate JWT tokens",
    description="""
    Generate JWT access and refresh tokens for a user.

    **Note:** In production, this endpoint should verify credentials
    against a user database. For demo purposes, it generates tokens
    directly from the provided user info.

    The access token should be included in the Authorization header
    for subsequent API calls:
    ```
    Authorization: Bearer <access_token>
    ```
    """,
)
async def create_token(request: TokenRequest) -> TokenResponse:
    """
    Generate JWT tokens for authentication.

    Returns access and refresh tokens for the provided user.
    """
    jwt_service = get_jwt_service()

    access_token = jwt_service.create_token(
        user_id=request.user_id,
        tenant_id=request.tenant_id,
        roles=request.roles,
    )

    refresh_token = jwt_service.create_refresh_token(
        user_id=request.user_id,
        tenant_id=request.tenant_id,
    )

    logger.info(
        "tokens_generated",
        user_id=request.user_id,
        tenant_id=request.tenant_id,
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=jwt_service.access_token_expire_minutes * 60,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
    description="""
    Use a refresh token to obtain a new access token.

    Refresh tokens have a longer expiry and can be used to get
    new access tokens without re-authenticating.
    """,
)
async def refresh_token(request: RefreshRequest) -> TokenResponse:
    """
    Refresh an access token using a refresh token.
    """
    jwt_service = get_jwt_service()

    try:
        # Validate refresh token and get new access token
        payload = jwt_service.validate_token(request.refresh_token)

        # Verify it's a refresh token
        if not payload.metadata or payload.metadata.get("type") != "refresh":
            raise HTTPException(
                status_code=401,
                detail="Invalid refresh token",
            )

        # Generate new access token
        # Note: In production, roles should be fetched from database
        access_token = jwt_service.create_token(
            user_id=payload.user_id,
            tenant_id=payload.tenant_id,
            roles=payload.roles,
        )

        # Generate new refresh token
        new_refresh_token = jwt_service.create_refresh_token(
            user_id=payload.user_id,
            tenant_id=payload.tenant_id,
        )

        logger.info(
            "token_refreshed",
            user_id=payload.user_id,
            tenant_id=payload.tenant_id,
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",
            expires_in=jwt_service.access_token_expire_minutes * 60,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("token_refresh_failed", error=str(e))
        raise HTTPException(
            status_code=401,
            detail="Failed to refresh token",
        )


@router.post(
    "/validate",
    response_model=TokenInfo,
    summary="Validate a token",
    description="""
    Validate a JWT token and return its payload.

    Useful for checking if a token is valid and what claims it contains.
    """,
)
async def validate_token(token: str) -> TokenInfo:
    """
    Validate a JWT token and return its information.
    """
    jwt_service = get_jwt_service()

    try:
        payload = jwt_service.validate_token(token)

        return TokenInfo(
            valid=True,
            user_id=payload.user_id,
            tenant_id=payload.tenant_id,
            roles=payload.roles,
            expires_at=payload.exp.isoformat(),
        )

    except HTTPException:
        return TokenInfo(valid=False)
    except Exception:
        return TokenInfo(valid=False)
