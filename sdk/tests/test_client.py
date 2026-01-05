"""Tests for SDK client."""

import pytest

from goodai.client import GoodAIClient


class TestGoodAIClient:
    """Tests for GoodAIClient."""

    def test_create_client(self) -> None:
        client = GoodAIClient(
            base_url="https://api.example.com",
            api_key="test-key",
            tenant_id="test-tenant",
        )

        assert client.base_url == "https://api.example.com"
        assert client.tenant_id == "test-tenant"

    def test_base_url_trailing_slash(self) -> None:
        client = GoodAIClient(base_url="https://api.example.com/")
        assert client.base_url == "https://api.example.com"

    def test_set_api_key(self) -> None:
        client = GoodAIClient(base_url="https://api.example.com")
        client.set_api_key("new-key")
        assert client._api_key == "new-key"

    def test_set_user_context(self) -> None:
        client = GoodAIClient(base_url="https://api.example.com")
        client.set_user_context(
            user_id="user-123",
            roles=["admin", "support_lead"],
        )

        assert client._user_id == "user-123"
        assert client._roles == ["admin", "support_lead"]

    def test_headers_with_api_key(self) -> None:
        client = GoodAIClient(
            base_url="https://api.example.com",
            api_key="test-key",
            tenant_id="test-tenant",
        )

        headers = client._get_headers()

        assert headers["Authorization"] == "Bearer test-key"
        assert headers["X-Tenant-ID"] == "test-tenant"
        assert headers["Content-Type"] == "application/json"

    def test_headers_with_user_context(self) -> None:
        client = GoodAIClient(base_url="https://api.example.com")
        client.set_user_context(user_id="user-1", roles=["admin"])

        headers = client._get_headers()

        assert headers["X-User-ID"] == "user-1"
        assert headers["X-Roles"] == "admin"

    def test_tickets_service_property(self) -> None:
        client = GoodAIClient(base_url="https://api.example.com")

        # Should return same instance
        tickets1 = client.tickets
        tickets2 = client.tickets

        assert tickets1 is tickets2

    def test_approvals_service_property(self) -> None:
        client = GoodAIClient(base_url="https://api.example.com")

        # Should return same instance
        approvals1 = client.approvals
        approvals2 = client.approvals

        assert approvals1 is approvals2

    def test_default_timeout(self) -> None:
        client = GoodAIClient(base_url="https://api.example.com")
        assert client.timeout == 30.0

    def test_custom_timeout(self) -> None:
        client = GoodAIClient(
            base_url="https://api.example.com",
            timeout=60.0,
        )
        assert client.timeout == 60.0

    def test_default_verify_ssl(self) -> None:
        client = GoodAIClient(base_url="https://api.example.com")
        assert client.verify_ssl is True

    def test_disable_verify_ssl(self) -> None:
        client = GoodAIClient(
            base_url="https://api.example.com",
            verify_ssl=False,
        )
        assert client.verify_ssl is False


class TestClientAsyncContext:
    """Tests for async context manager."""

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        async with GoodAIClient(base_url="https://api.example.com") as client:
            assert client._client is not None

        # Client should be closed after exiting context
        assert client._client is None

    @pytest.mark.asyncio
    async def test_close_idempotent(self) -> None:
        client = GoodAIClient(base_url="https://api.example.com")
        await client._get_async_client()  # Create client

        await client.close()
        await client.close()  # Should not raise

        assert client._client is None
