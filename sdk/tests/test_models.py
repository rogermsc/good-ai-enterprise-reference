"""Tests for SDK models."""

from datetime import UTC, datetime

import pytest

from goodai.models import (
    APIError,
    ApprovalListResponse,
    ApprovalPriority,
    ApprovalRequest,
    ApprovalStats,
    ApprovalStatus,
    HealthStatus,
    TicketTriageResult,
    TokenResponse,
)


class TestHealthStatus:
    """Tests for HealthStatus model."""

    def test_create_health_status(self) -> None:
        health = HealthStatus(
            status="healthy",
            version="1.0.0",
            environment="production",
        )

        assert health.status == "healthy"
        assert health.version == "1.0.0"
        assert health.environment == "production"

    def test_health_with_timestamp(self) -> None:
        now = datetime.now(UTC)
        health = HealthStatus(
            status="healthy",
            version="1.0.0",
            environment="production",
            timestamp=now,
        )

        assert health.timestamp == now


class TestTokenResponse:
    """Tests for TokenResponse model."""

    def test_create_token(self) -> None:
        token = TokenResponse(
            access_token="abc123",
            expires_in=3600,
        )

        assert token.access_token == "abc123"
        assert token.token_type == "bearer"
        assert token.expires_in == 3600

    def test_token_with_refresh(self) -> None:
        token = TokenResponse(
            access_token="abc123",
            token_type="bearer",
            expires_in=3600,
            refresh_token="refresh456",
        )

        assert token.refresh_token == "refresh456"


class TestTicketTriageResult:
    """Tests for TicketTriageResult model."""

    def test_create_result(self) -> None:
        result = TicketTriageResult(
            severity="P2",
            category="billing",
            suggested_response="Thank you for contacting us...",
            recommended_actions=["verify_charge", "process_refund"],
        )

        assert result.severity == "P2"
        assert result.category == "billing"
        assert len(result.recommended_actions) == 2

    def test_result_with_approval(self) -> None:
        result = TicketTriageResult(
            severity="P0",
            requires_approval=True,
            approval_id="approval-123",
        )

        assert result.requires_approval is True
        assert result.approval_id == "approval-123"

    def test_default_values(self) -> None:
        result = TicketTriageResult(severity="P3")

        assert result.recommended_actions == []
        assert result.requires_approval is False
        assert result.pii_detected is False


class TestApprovalRequest:
    """Tests for ApprovalRequest model."""

    def test_create_request(self) -> None:
        request = ApprovalRequest(
            id="req-123",
            request_type="ticket_response",
            action="send_response",
            context={"ticket_id": "123"},
            requester={"user_id": "user-1", "tenant_id": "tenant-1"},
            status=ApprovalStatus.PENDING,
            priority=ApprovalPriority.HIGH,
            created_at=datetime.now(UTC),
        )

        assert request.id == "req-123"
        assert request.status == ApprovalStatus.PENDING
        assert request.priority == ApprovalPriority.HIGH

    def test_status_enum_values(self) -> None:
        assert ApprovalStatus.PENDING.value == "pending"
        assert ApprovalStatus.APPROVED.value == "approved"
        assert ApprovalStatus.REJECTED.value == "rejected"
        assert ApprovalStatus.EXPIRED.value == "expired"

    def test_priority_enum_values(self) -> None:
        assert ApprovalPriority.CRITICAL.value == "critical"
        assert ApprovalPriority.HIGH.value == "high"
        assert ApprovalPriority.MEDIUM.value == "medium"
        assert ApprovalPriority.LOW.value == "low"


class TestApprovalListResponse:
    """Tests for ApprovalListResponse model."""

    def test_create_list(self) -> None:
        approvals = [
            ApprovalRequest(
                id=f"req-{i}",
                request_type="test",
                action="test",
                context={},
                requester={"user_id": "user-1", "tenant_id": "tenant-1"},
                status=ApprovalStatus.PENDING,
                priority=ApprovalPriority.MEDIUM,
                created_at=datetime.now(UTC),
            )
            for i in range(3)
        ]

        response = ApprovalListResponse(
            approvals=approvals,
            total=3,
        )

        assert len(response.approvals) == 3
        assert response.total == 3


class TestApprovalStats:
    """Tests for ApprovalStats model."""

    def test_create_stats(self) -> None:
        stats = ApprovalStats(
            total=100,
            by_status={"pending": 10, "approved": 80, "rejected": 10},
            by_priority={"critical": 5, "high": 20, "medium": 50, "low": 25},
            pending_count=10,
            average_wait_seconds=300.5,
        )

        assert stats.total == 100
        assert stats.by_status["approved"] == 80
        assert stats.pending_count == 10


class TestAPIError:
    """Tests for APIError exception."""

    def test_create_error(self) -> None:
        error = APIError(
            message="Not found",
            status_code=404,
            details={"path": "/approvals/123"},
        )

        assert error.message == "Not found"
        assert error.status_code == 404
        assert error.details["path"] == "/approvals/123"

    def test_error_string(self) -> None:
        error = APIError("Unauthorized", status_code=401)
        assert str(error) == "[401] Unauthorized"

    def test_error_without_status(self) -> None:
        error = APIError("Something went wrong")
        assert str(error) == "Something went wrong"

    def test_error_is_exception(self) -> None:
        error = APIError("Test error")
        assert isinstance(error, Exception)

        with pytest.raises(APIError):
            raise error
