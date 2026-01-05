"""
Good AI SDK Client.

Main client class for interacting with the Good AI Enterprise Platform API.
"""

from typing import Any

import httpx

from goodai.models import APIError, HealthStatus, TokenResponse
from goodai.services.approvals import ApprovalsService
from goodai.services.tickets import TicketsService


class GoodAIClient:
    """
    Client for the Good AI Enterprise Platform API.

    Example:
        # Async usage
        async with GoodAIClient(base_url="https://api.example.com") as client:
            await client.authenticate(username="user", password="pass")
            result = await client.tickets.triage(
                subject="Help needed",
                body="I have a problem...",
            )

        # Sync usage (blocking)
        client = GoodAIClient(base_url="https://api.example.com")
        client.set_api_key("your-api-key")
        health = client.health()
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        tenant_id: str = "default",
        timeout: float = 30.0,
        verify_ssl: bool = True,
    ) -> None:
        """
        Initialize the client.

        Args:
            base_url: Base URL of the API (e.g., "https://api.example.com")
            api_key: Optional API key for authentication
            tenant_id: Tenant identifier for multi-tenant deployments
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates
        """
        self.base_url = base_url.rstrip("/")
        self.tenant_id = tenant_id
        self.timeout = timeout
        self.verify_ssl = verify_ssl

        self._api_key: str | None = api_key
        self._access_token: str | None = None
        self._user_id: str | None = None
        self._roles: list[str] = []

        # HTTP client
        self._client: httpx.AsyncClient | None = None
        self._sync_client: httpx.Client | None = None

        # Service instances
        self._tickets: TicketsService | None = None
        self._approvals: ApprovalsService | None = None

    def set_api_key(self, api_key: str) -> None:
        """Set the API key for authentication."""
        self._api_key = api_key

    def set_user_context(
        self,
        user_id: str,
        roles: list[str] | None = None,
    ) -> None:
        """Set user context for requests."""
        self._user_id = user_id
        self._roles = roles or []

    @property
    def tickets(self) -> TicketsService:
        """Access the tickets service."""
        if self._tickets is None:
            self._tickets = TicketsService(self)
        return self._tickets

    @property
    def approvals(self) -> ApprovalsService:
        """Access the approvals service."""
        if self._approvals is None:
            self._approvals = ApprovalsService(self)
        return self._approvals

    def _get_headers(self) -> dict[str, str]:
        """Get request headers with authentication."""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Tenant-ID": self.tenant_id,
        }

        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        elif self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        if self._user_id:
            headers["X-User-ID"] = self._user_id

        if self._roles:
            headers["X-Roles"] = ",".join(self._roles)

        return headers

    async def _get_async_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
        return self._client

    def _get_sync_client(self) -> httpx.Client:
        """Get or create sync HTTP client."""
        if self._sync_client is None:
            self._sync_client = httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
        return self._sync_client

    async def __aenter__(self) -> "GoodAIClient":
        """Async context manager entry."""
        await self._get_async_client()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Async context manager exit."""
        await self.close()

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._sync_client:
            self._sync_client.close()
            self._sync_client = None

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make an async HTTP request."""
        client = await self._get_async_client()
        headers = {**self._get_headers(), **kwargs.pop("headers", {})}

        response = await client.request(
            method,
            path,
            headers=headers,
            **kwargs,
        )

        if response.status_code >= 400:
            try:
                error_data = response.json()
                message = error_data.get("detail", response.text)
            except Exception:
                message = response.text

            raise APIError(
                message=message,
                status_code=response.status_code,
                details={"path": path, "method": method},
            )

        if response.status_code == 204:
            return {}

        return response.json()

    def _request_sync(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make a sync HTTP request."""
        client = self._get_sync_client()
        headers = {**self._get_headers(), **kwargs.pop("headers", {})}

        response = client.request(
            method,
            path,
            headers=headers,
            **kwargs,
        )

        if response.status_code >= 400:
            try:
                error_data = response.json()
                message = error_data.get("detail", response.text)
            except Exception:
                message = response.text

            raise APIError(
                message=message,
                status_code=response.status_code,
                details={"path": path, "method": method},
            )

        if response.status_code == 204:
            return {}

        return response.json()

    async def authenticate(
        self,
        username: str,
        password: str,
    ) -> TokenResponse:
        """
        Authenticate with username and password.

        Args:
            username: User's username
            password: User's password

        Returns:
            TokenResponse with access token
        """
        data = await self._request(
            "POST",
            "/auth/token",
            data={"username": username, "password": password},
        )
        token = TokenResponse(**data)
        self._access_token = token.access_token
        return token

    async def health(self) -> HealthStatus:
        """Check API health status."""
        data = await self._request("GET", "/health")
        return HealthStatus(**data)

    def health_sync(self) -> HealthStatus:
        """Check API health status (sync)."""
        data = self._request_sync("GET", "/health")
        return HealthStatus(**data)
