"""Tests for cost controls and quota management."""

from datetime import UTC, datetime

import pytest

from src.core.cost_control import (
    InMemoryUsageStore,
    QuotaExceededError,
    QuotaLimit,
    QuotaManager,
    QuotaPeriod,
    QuotaType,
    QuotaUsage,
    UsageRecord,
    estimate_cost,
    get_quota_manager,
)


class TestEstimateCost:
    """Tests for cost estimation."""

    def test_gpt4_turbo_cost(self) -> None:
        cost = estimate_cost(1000, 500, "gpt-4-turbo")
        # GPT-4 Turbo: 1K input at $0.01 plus 0.5K output at $0.03
        assert cost == 0.025

    def test_gpt35_turbo_cost(self) -> None:
        cost = estimate_cost(10000, 5000, "gpt-3.5-turbo")
        # GPT-3.5 Turbo: 10K input at $0.0005 plus 5K output at $0.0015
        assert cost == 0.0125

    def test_mock_model_zero_cost(self) -> None:
        cost = estimate_cost(100000, 50000, "mock")
        assert cost == 0.0

    def test_unknown_model_default_cost(self) -> None:
        cost = estimate_cost(1000, 500, "unknown-model")
        # Uses default: input 0.01, output 0.03
        assert cost == 0.025


class TestQuotaLimit:
    """Tests for quota limit configuration."""

    def test_create_quota_limit(self) -> None:
        limit = QuotaLimit(
            quota_type=QuotaType.TOKENS,
            period=QuotaPeriod.DAILY,
            limit=1_000_000,
        )
        assert limit.quota_type == QuotaType.TOKENS
        assert limit.period == QuotaPeriod.DAILY
        assert limit.limit == 1_000_000
        assert limit.soft_limit is None

    def test_quota_with_soft_limit(self) -> None:
        limit = QuotaLimit(
            quota_type=QuotaType.COST,
            period=QuotaPeriod.MONTHLY,
            limit=1000.0,
            soft_limit=800.0,
        )
        assert limit.soft_limit == 800.0

    def test_soft_limit_exceeds_limit_raises(self) -> None:
        with pytest.raises(ValueError, match="soft_limit cannot exceed limit"):
            QuotaLimit(
                quota_type=QuotaType.TOKENS,
                period=QuotaPeriod.DAILY,
                limit=1000,
                soft_limit=2000,
            )


class TestQuotaUsage:
    """Tests for quota usage tracking."""

    def test_remaining_quota(self) -> None:
        usage = QuotaUsage(
            quota_type=QuotaType.TOKENS,
            period=QuotaPeriod.DAILY,
            current=300_000,
            limit=1_000_000,
        )
        assert usage.remaining == 700_000

    def test_percentage_used(self) -> None:
        usage = QuotaUsage(
            quota_type=QuotaType.TOKENS,
            period=QuotaPeriod.DAILY,
            current=250_000,
            limit=1_000_000,
        )
        assert usage.percentage_used == 25.0

    def test_is_exceeded(self) -> None:
        usage = QuotaUsage(
            quota_type=QuotaType.REQUESTS,
            period=QuotaPeriod.HOURLY,
            current=100,
            limit=100,
        )
        assert usage.is_exceeded is True

    def test_is_not_exceeded(self) -> None:
        usage = QuotaUsage(
            quota_type=QuotaType.REQUESTS,
            period=QuotaPeriod.HOURLY,
            current=50,
            limit=100,
        )
        assert usage.is_exceeded is False

    def test_soft_limit_exceeded(self) -> None:
        usage = QuotaUsage(
            quota_type=QuotaType.TOKENS,
            period=QuotaPeriod.DAILY,
            current=850_000,
            limit=1_000_000,
            soft_limit=800_000,
        )
        assert usage.is_soft_limit_exceeded is True
        assert usage.is_exceeded is False


class TestUsageRecord:
    """Tests for usage records."""

    def test_total_tokens(self) -> None:
        record = UsageRecord(
            tenant_id="tenant-1",
            user_id="user-1",
            timestamp=datetime.now(UTC),
            input_tokens=500,
            output_tokens=200,
            cost=0.025,
            model="gpt-4",
        )
        assert record.total_tokens == 700


class TestInMemoryUsageStore:
    """Tests for in-memory usage store."""

    @pytest.fixture
    def store(self) -> InMemoryUsageStore:
        return InMemoryUsageStore()

    def test_record_and_get_usage(self, store: InMemoryUsageStore) -> None:
        record = UsageRecord(
            tenant_id="tenant-1",
            user_id="user-1",
            timestamp=datetime.now(UTC),
            input_tokens=100,
            output_tokens=50,
            cost=0.01,
            model="gpt-4",
        )
        store.record(record)

        usage = store.get_usage("tenant-1", "user-1")
        assert len(usage) == 1
        assert usage[0].input_tokens == 100

    def test_get_usage_by_tenant(self, store: InMemoryUsageStore) -> None:
        store.record(
            UsageRecord(
                tenant_id="tenant-1",
                user_id="user-1",
                timestamp=datetime.now(UTC),
                input_tokens=100,
                output_tokens=50,
                cost=0.01,
                model="gpt-4",
            )
        )
        store.record(
            UsageRecord(
                tenant_id="tenant-1",
                user_id="user-2",
                timestamp=datetime.now(UTC),
                input_tokens=200,
                output_tokens=100,
                cost=0.02,
                model="gpt-4",
            )
        )

        # Get all for tenant
        usage = store.get_usage("tenant-1")
        assert len(usage) == 2

    def test_aggregated_usage(self, store: InMemoryUsageStore) -> None:
        store.record(
            UsageRecord(
                tenant_id="tenant-1",
                user_id="user-1",
                timestamp=datetime.now(UTC),
                input_tokens=100,
                output_tokens=50,
                cost=0.01,
                model="gpt-4",
            )
        )
        store.record(
            UsageRecord(
                tenant_id="tenant-1",
                user_id="user-1",
                timestamp=datetime.now(UTC),
                input_tokens=200,
                output_tokens=100,
                cost=0.02,
                model="gpt-4",
            )
        )

        aggregated = store.get_aggregated_usage("tenant-1", "user-1")
        assert aggregated["total_tokens"] == 450
        assert aggregated["input_tokens"] == 300
        assert aggregated["output_tokens"] == 150
        assert aggregated["requests"] == 2
        assert aggregated["cost"] == 0.03

    def test_clear(self, store: InMemoryUsageStore) -> None:
        store.record(
            UsageRecord(
                tenant_id="tenant-1",
                user_id="user-1",
                timestamp=datetime.now(UTC),
                input_tokens=100,
                output_tokens=50,
                cost=0.01,
                model="gpt-4",
            )
        )
        store.clear()
        usage = store.get_usage("tenant-1")
        assert len(usage) == 0


class TestQuotaManager:
    """Tests for quota manager."""

    @pytest.fixture
    def manager(self) -> QuotaManager:
        return QuotaManager()

    def test_set_and_get_quota(self, manager: QuotaManager) -> None:
        quota = QuotaLimit(
            quota_type=QuotaType.TOKENS,
            period=QuotaPeriod.DAILY,
            limit=500_000,
        )
        manager.set_quota("tenant-1", quota)

        quotas = manager.get_quotas("tenant-1")
        assert any(q.limit == 500_000 for q in quotas)

    def test_default_quotas(self, manager: QuotaManager) -> None:
        quotas = manager.get_quotas("unknown-tenant")
        # Should return default quotas
        assert len(quotas) > 0
        assert any(q.quota_type == QuotaType.TOKENS for q in quotas)

    def test_check_quota_allowed(self, manager: QuotaManager) -> None:
        result = manager.check_quota("tenant-1", "user-1", estimated_tokens=1000)
        assert result.allowed is True
        assert len(result.exceeded_quotas) == 0

    def test_check_quota_exceeded(self, manager: QuotaManager) -> None:
        # Set a very low limit
        manager.set_quota(
            "tenant-2",
            QuotaLimit(
                quota_type=QuotaType.TOKENS,
                period=QuotaPeriod.DAILY,
                limit=100,
            ),
        )

        # Record some usage
        manager.record_usage("tenant-2", "user-1", 50, 50, "gpt-4")

        # Now try to use more
        result = manager.check_quota("tenant-2", "user-1", estimated_tokens=100)
        assert result.allowed is False
        assert len(result.exceeded_quotas) > 0

    def test_check_quota_soft_limit_warning(self, manager: QuotaManager) -> None:
        manager.set_quota(
            "tenant-3",
            QuotaLimit(
                quota_type=QuotaType.TOKENS,
                period=QuotaPeriod.DAILY,
                limit=1000,
                soft_limit=500,
            ),
        )

        # Record usage above soft limit
        manager.record_usage("tenant-3", "user-1", 300, 300, "gpt-4")

        result = manager.check_quota("tenant-3", "user-1", estimated_tokens=0)
        assert result.allowed is True
        assert result.has_warnings is True
        assert any("approaching limit" in w for w in result.warnings)

    def test_record_usage(self, manager: QuotaManager) -> None:
        record = manager.record_usage(
            tenant_id="tenant-1",
            user_id="user-1",
            input_tokens=1000,
            output_tokens=500,
            model="gpt-4-turbo",
        )
        assert record.total_tokens == 1500
        assert record.cost > 0

    def test_get_usage_summary(self, manager: QuotaManager) -> None:
        manager.record_usage("tenant-1", "user-1", 1000, 500, "gpt-4")
        manager.record_usage("tenant-1", "user-1", 2000, 1000, "gpt-4")

        summary = manager.get_usage_summary("tenant-1", "user-1")
        assert summary["tenant_id"] == "tenant-1"
        assert summary["usage"]["total_tokens"] == 4500
        assert summary["usage"]["requests"] == 2

    def test_remove_quota(self, manager: QuotaManager) -> None:
        manager.set_quota(
            "tenant-4",
            QuotaLimit(
                quota_type=QuotaType.TOKENS,
                period=QuotaPeriod.DAILY,
                limit=1000,
            ),
        )

        removed = manager.remove_quota("tenant-4")
        assert removed is True

        # Should fall back to defaults
        quotas = manager.get_quotas("tenant-4")
        assert quotas == manager._default_quotas

    def test_user_level_quota(self, manager: QuotaManager) -> None:
        # Set user-specific quota
        manager.set_quota(
            "tenant-5:user-1",
            QuotaLimit(
                quota_type=QuotaType.REQUESTS,
                period=QuotaPeriod.HOURLY,
                limit=10,
            ),
        )

        # Record usage
        for _ in range(10):
            manager.record_usage("tenant-5", "user-1", 100, 50, "gpt-4")

        result = manager.check_quota("tenant-5", "user-1")
        assert result.allowed is False


class TestQuotaExceededError:
    """Tests for quota exceeded error."""

    def test_error_message(self) -> None:
        usages = [
            QuotaUsage(
                quota_type=QuotaType.TOKENS,
                period=QuotaPeriod.DAILY,
                current=1_000_000,
                limit=1_000_000,
            ),
        ]
        error = QuotaExceededError(usages)
        assert "tokens" in str(error).lower()
        assert "daily" in str(error).lower()


class TestGetQuotaManager:
    """Tests for global quota manager."""

    def test_returns_singleton(self) -> None:
        manager1 = get_quota_manager()
        manager2 = get_quota_manager()
        assert manager1 is manager2
