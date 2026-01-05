"""
Cost Controls and Quota Management.

Provides:
- Per-tenant and per-user usage quotas
- Token budget tracking and enforcement
- Cost estimation and monitoring
- Usage alerts and reporting

Quotas can be configured at multiple levels:
- Global (system-wide limits)
- Tenant (organization limits)
- User (individual limits)
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.core.config import get_settings
from src.core.observability import get_logger, get_tracer

logger = get_logger()
tracer = get_tracer()


class QuotaPeriod(str, Enum):
    """Time period for quota tracking."""

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class QuotaType(str, Enum):
    """Type of quota limit."""

    TOKENS = "tokens"  # Total tokens (input + output)
    INPUT_TOKENS = "input_tokens"
    OUTPUT_TOKENS = "output_tokens"
    REQUESTS = "requests"  # Number of API calls
    COST = "cost"  # Dollar amount


@dataclass
class QuotaLimit:
    """A single quota limit configuration."""

    quota_type: QuotaType
    period: QuotaPeriod
    limit: float  # Max value for the period
    soft_limit: float | None = None  # Warning threshold (optional)

    def __post_init__(self) -> None:
        if self.soft_limit and self.soft_limit > self.limit:
            raise ValueError("soft_limit cannot exceed limit")


@dataclass
class QuotaUsage:
    """Current usage against a quota."""

    quota_type: QuotaType
    period: QuotaPeriod
    current: float
    limit: float
    soft_limit: float | None = None
    period_start: datetime = field(default_factory=lambda: datetime.now(UTC))
    period_end: datetime | None = None

    @property
    def remaining(self) -> float:
        """Remaining quota."""
        return max(0, self.limit - self.current)

    @property
    def percentage_used(self) -> float:
        """Percentage of quota used."""
        if self.limit == 0:
            return 100.0
        return (self.current / self.limit) * 100

    @property
    def is_exceeded(self) -> bool:
        """Check if quota is exceeded."""
        return self.current >= self.limit

    @property
    def is_soft_limit_exceeded(self) -> bool:
        """Check if soft limit is exceeded."""
        if self.soft_limit is None:
            return False
        return self.current >= self.soft_limit


@dataclass
class QuotaCheckResult:
    """Result of a quota check."""

    allowed: bool
    usages: list[QuotaUsage] = field(default_factory=list)
    exceeded_quotas: list[QuotaUsage] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    estimated_cost: float = 0.0

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return len(self.warnings) > 0


@dataclass
class UsageRecord:
    """Record of a single usage event."""

    tenant_id: str
    user_id: str
    timestamp: datetime
    input_tokens: int
    output_tokens: int
    cost: float
    model: str
    operation: str = "llm_call"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        """Total tokens used."""
        return self.input_tokens + self.output_tokens


# Cost estimates per 1K tokens by model
MODEL_COSTS: dict[str, dict[str, float]] = {
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-4": {"input": 0.03, "output": 0.06},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    "claude-3-opus": {"input": 0.015, "output": 0.075},
    "claude-3-sonnet": {"input": 0.003, "output": 0.015},
    "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
    "mock": {"input": 0.0, "output": 0.0},
}


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str = "gpt-4-turbo",
) -> float:
    """
    Estimate cost for token usage.

    Args:
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        model: Model name

    Returns:
        Estimated cost in dollars
    """
    costs = MODEL_COSTS.get(model, {"input": 0.01, "output": 0.03})
    input_cost = (input_tokens / 1000) * costs["input"]
    output_cost = (output_tokens / 1000) * costs["output"]
    return round(input_cost + output_cost, 6)


class InMemoryUsageStore:
    """
    In-memory storage for usage tracking.

    For production, replace with Redis or database storage.
    """

    def __init__(self) -> None:
        self._usage: dict[str, list[UsageRecord]] = {}

    def record(self, record: UsageRecord) -> None:
        """Record a usage event."""
        key = f"{record.tenant_id}:{record.user_id}"
        if key not in self._usage:
            self._usage[key] = []
        self._usage[key].append(record)

    def get_usage(
        self,
        tenant_id: str,
        user_id: str | None = None,
        since: datetime | None = None,
    ) -> list[UsageRecord]:
        """Get usage records."""
        results = []

        for key, records in self._usage.items():
            parts = key.split(":", 1)
            if parts[0] != tenant_id:
                continue
            if user_id and parts[1] != user_id:
                continue

            for record in records:
                if since and record.timestamp < since:
                    continue
                results.append(record)

        return results

    def get_aggregated_usage(
        self,
        tenant_id: str,
        user_id: str | None = None,
        period: QuotaPeriod = QuotaPeriod.DAILY,
    ) -> dict[str, float]:
        """Get aggregated usage for a period."""
        since = self._get_period_start(period)
        records = self.get_usage(tenant_id, user_id, since)

        return {
            "total_tokens": sum(r.total_tokens for r in records),
            "input_tokens": sum(r.input_tokens for r in records),
            "output_tokens": sum(r.output_tokens for r in records),
            "requests": len(records),
            "cost": sum(r.cost for r in records),
        }

    def _get_period_start(self, period: QuotaPeriod) -> datetime:
        """Get the start of the current period."""
        now = datetime.now(UTC)

        if period == QuotaPeriod.HOURLY:
            return now.replace(minute=0, second=0, microsecond=0)
        if period == QuotaPeriod.DAILY:
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == QuotaPeriod.WEEKLY:
            days_since_monday = now.weekday()
            return now.replace(hour=0, minute=0, second=0, microsecond=0) - __import__(
                "datetime"
            ).timedelta(days=days_since_monday)
        if period == QuotaPeriod.MONTHLY:
            return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        return now

    def clear(self) -> None:
        """Clear all usage data."""
        self._usage.clear()


class QuotaManager:
    """
    Manages quotas and enforces limits.

    Example:
        manager = QuotaManager()

        # Configure tenant quota
        manager.set_quota("tenant-123", QuotaLimit(
            quota_type=QuotaType.TOKENS,
            period=QuotaPeriod.DAILY,
            limit=1_000_000,
            soft_limit=800_000,
        ))

        # Check before making request
        result = manager.check_quota("tenant-123", "user-456", estimated_tokens=1000)
        if not result.allowed:
            raise QuotaExceededError(result.exceeded_quotas)

        # Record usage after request
        manager.record_usage(
            tenant_id="tenant-123",
            user_id="user-456",
            input_tokens=500,
            output_tokens=200,
            model="gpt-4",
        )
    """

    def __init__(
        self,
        usage_store: InMemoryUsageStore | None = None,
    ) -> None:
        self.usage_store = usage_store or InMemoryUsageStore()
        self._quotas: dict[str, list[QuotaLimit]] = {}
        self._default_quotas: list[QuotaLimit] = self._create_default_quotas()

    def _create_default_quotas(self) -> list[QuotaLimit]:
        """Create default quota limits."""
        # Settings can be used to customize defaults in future
        _ = get_settings()
        return [
            QuotaLimit(
                quota_type=QuotaType.TOKENS,
                period=QuotaPeriod.DAILY,
                limit=1_000_000,  # 1M tokens per day
                soft_limit=800_000,
            ),
            QuotaLimit(
                quota_type=QuotaType.REQUESTS,
                period=QuotaPeriod.HOURLY,
                limit=100,  # 100 requests per hour
                soft_limit=80,
            ),
            QuotaLimit(
                quota_type=QuotaType.COST,
                period=QuotaPeriod.DAILY,
                limit=100.0,  # $100 per day
                soft_limit=80.0,
            ),
        ]

    def set_quota(
        self,
        entity_id: str,
        quota: QuotaLimit,
    ) -> None:
        """
        Set a quota for an entity (tenant or user).

        Args:
            entity_id: Tenant ID or "tenant_id:user_id" for user quota
            quota: Quota limit to set
        """
        if entity_id not in self._quotas:
            self._quotas[entity_id] = []

        # Replace existing quota of same type/period
        self._quotas[entity_id] = [
            q
            for q in self._quotas[entity_id]
            if not (q.quota_type == quota.quota_type and q.period == quota.period)
        ]
        self._quotas[entity_id].append(quota)

        logger.info(
            "quota_set",
            entity_id=entity_id,
            quota_type=quota.quota_type.value,
            period=quota.period.value,
            limit=quota.limit,
        )

    def remove_quota(
        self,
        entity_id: str,
        quota_type: QuotaType | None = None,
        period: QuotaPeriod | None = None,
    ) -> bool:
        """Remove quota(s) for an entity."""
        if entity_id not in self._quotas:
            return False

        if quota_type is None and period is None:
            del self._quotas[entity_id]
            return True

        original_len = len(self._quotas[entity_id])
        self._quotas[entity_id] = [
            q
            for q in self._quotas[entity_id]
            if not (
                (quota_type is None or q.quota_type == quota_type)
                and (period is None or q.period == period)
            )
        ]

        if not self._quotas[entity_id]:
            del self._quotas[entity_id]

        return len(self._quotas.get(entity_id, [])) < original_len

    def get_quotas(self, entity_id: str) -> list[QuotaLimit]:
        """Get quotas for an entity, falling back to defaults."""
        return self._quotas.get(entity_id, self._default_quotas)

    def check_quota(
        self,
        tenant_id: str,
        user_id: str,
        estimated_tokens: int = 0,
        estimated_cost: float = 0.0,
    ) -> QuotaCheckResult:
        """
        Check if a request is within quota limits.

        Args:
            tenant_id: Tenant identifier
            user_id: User identifier
            estimated_tokens: Estimated tokens for the request
            estimated_cost: Estimated cost (if known)

        Returns:
            QuotaCheckResult indicating if request is allowed
        """
        with tracer.start_as_current_span("quota.check") as span:
            span.set_attribute("tenant_id", tenant_id)
            span.set_attribute("user_id", user_id)

            usages: list[QuotaUsage] = []
            exceeded: list[QuotaUsage] = []
            warnings: list[str] = []

            # Check tenant quotas
            tenant_quotas = self.get_quotas(tenant_id)
            for quota in tenant_quotas:
                usage = self._check_single_quota(
                    tenant_id, None, quota, estimated_tokens, estimated_cost
                )
                usages.append(usage)

                if usage.is_exceeded:
                    exceeded.append(usage)
                elif usage.is_soft_limit_exceeded:
                    warnings.append(
                        f"Tenant {quota.quota_type.value} approaching limit: "
                        f"{usage.percentage_used:.1f}% used"
                    )

            # Check user quotas
            user_key = f"{tenant_id}:{user_id}"
            if user_key in self._quotas:
                for quota in self._quotas[user_key]:
                    usage = self._check_single_quota(
                        tenant_id, user_id, quota, estimated_tokens, estimated_cost
                    )
                    usages.append(usage)

                    if usage.is_exceeded:
                        exceeded.append(usage)
                    elif usage.is_soft_limit_exceeded:
                        warnings.append(
                            f"User {quota.quota_type.value} approaching limit: "
                            f"{usage.percentage_used:.1f}% used"
                        )

            allowed = len(exceeded) == 0

            span.set_attribute("allowed", allowed)
            span.set_attribute("exceeded_count", len(exceeded))

            if not allowed:
                logger.warning(
                    "quota_exceeded",
                    tenant_id=tenant_id,
                    user_id=user_id,
                    exceeded=[
                        {"type": q.quota_type.value, "period": q.period.value} for q in exceeded
                    ],
                )

            return QuotaCheckResult(
                allowed=allowed,
                usages=usages,
                exceeded_quotas=exceeded,
                warnings=warnings,
                estimated_cost=estimated_cost,
            )

    def _check_single_quota(
        self,
        tenant_id: str,
        user_id: str | None,
        quota: QuotaLimit,
        estimated_tokens: int,
        estimated_cost: float,
    ) -> QuotaUsage:
        """Check usage against a single quota."""
        aggregated = self.usage_store.get_aggregated_usage(tenant_id, user_id, quota.period)

        # Get current usage based on quota type
        if quota.quota_type == QuotaType.TOKENS:
            current = aggregated["total_tokens"] + estimated_tokens
        elif quota.quota_type == QuotaType.INPUT_TOKENS:
            current = aggregated["input_tokens"] + estimated_tokens
        elif quota.quota_type == QuotaType.OUTPUT_TOKENS:
            current = aggregated["output_tokens"]
        elif quota.quota_type == QuotaType.REQUESTS:
            current = aggregated["requests"] + 1
        elif quota.quota_type == QuotaType.COST:
            current = aggregated["cost"] + estimated_cost
        else:
            current = 0

        return QuotaUsage(
            quota_type=quota.quota_type,
            period=quota.period,
            current=current,
            limit=quota.limit,
            soft_limit=quota.soft_limit,
        )

    def record_usage(
        self,
        tenant_id: str,
        user_id: str,
        input_tokens: int,
        output_tokens: int,
        model: str = "gpt-4-turbo",
        operation: str = "llm_call",
        metadata: dict[str, Any] | None = None,
    ) -> UsageRecord:
        """
        Record a usage event.

        Args:
            tenant_id: Tenant identifier
            user_id: User identifier
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            model: Model used
            operation: Operation type
            metadata: Additional metadata

        Returns:
            The recorded usage record
        """
        cost = estimate_cost(input_tokens, output_tokens, model)

        record = UsageRecord(
            tenant_id=tenant_id,
            user_id=user_id,
            timestamp=datetime.now(UTC),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            model=model,
            operation=operation,
            metadata=metadata or {},
        )

        self.usage_store.record(record)

        logger.info(
            "usage_recorded",
            tenant_id=tenant_id,
            user_id=user_id,
            tokens=record.total_tokens,
            cost=cost,
            model=model,
        )

        return record

    def get_usage_summary(
        self,
        tenant_id: str,
        user_id: str | None = None,
        period: QuotaPeriod = QuotaPeriod.DAILY,
    ) -> dict[str, Any]:
        """
        Get usage summary for a tenant/user.

        Returns:
            Summary with current usage and quota status
        """
        aggregated = self.usage_store.get_aggregated_usage(tenant_id, user_id, period)
        quotas = self.get_quotas(tenant_id)

        quota_status = []
        for quota in quotas:
            if quota.period == period:
                current = aggregated.get(quota.quota_type.value, 0)
                quota_status.append(
                    {
                        "type": quota.quota_type.value,
                        "current": current,
                        "limit": quota.limit,
                        "soft_limit": quota.soft_limit,
                        "percentage_used": (current / quota.limit * 100) if quota.limit > 0 else 0,
                        "remaining": max(0, quota.limit - current),
                    }
                )

        return {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "period": period.value,
            "usage": aggregated,
            "quotas": quota_status,
        }


class QuotaExceededError(Exception):
    """Raised when quota is exceeded."""

    def __init__(self, exceeded_quotas: list[QuotaUsage]) -> None:
        self.exceeded_quotas = exceeded_quotas
        details = ", ".join(f"{q.quota_type.value} ({q.period.value})" for q in exceeded_quotas)
        super().__init__(f"Quota exceeded: {details}")


# Global quota manager instance
_quota_manager: QuotaManager | None = None


def get_quota_manager() -> QuotaManager:
    """Get the global quota manager instance."""
    global _quota_manager
    if _quota_manager is None:
        _quota_manager = QuotaManager()
    return _quota_manager
