"""
LLM Provider Resilience - Failover, Circuit Breaker, and Cost Controls.

Provides production-grade LLM operations with:
- Multi-provider failover chain (OpenAI → Azure → Anthropic → Mock)
- Circuit breaker pattern for provider failures
- Per-tenant budget tracking and enforcement
- Request-level cost estimation before LLM call
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum

from src.core.observability import get_logger

logger = get_logger()


class ProviderStatus(str, Enum):
    """Provider health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class ProviderConfig:
    """Configuration for an LLM provider."""

    name: str
    api_base_url: str
    api_key_env: str  # Environment variable name for API key
    models: list[str]
    priority: int = 0  # Lower = higher priority
    timeout_seconds: int = 30
    max_retries: int = 3
    cost_per_1k_tokens: dict[str, dict[str, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.cost_per_1k_tokens:
            # Default costs
            self.cost_per_1k_tokens = {
                "gpt-4": {"input": 0.03, "output": 0.06},
                "gpt-4-turbo": {"input": 0.01, "output": 0.03},
                "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
                "claude-3-opus": {"input": 0.015, "output": 0.075},
                "claude-3-sonnet": {"input": 0.003, "output": 0.015},
            }


# Default provider configurations
DEFAULT_PROVIDERS: list[ProviderConfig] = [
    ProviderConfig(
        name="openai",
        api_base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        models=["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"],
        priority=1,
    ),
    ProviderConfig(
        name="azure_openai",
        api_base_url="",  # Set via AZURE_OPENAI_ENDPOINT env var
        api_key_env="AZURE_OPENAI_API_KEY",
        models=["gpt-4", "gpt-35-turbo"],
        priority=2,
    ),
    ProviderConfig(
        name="anthropic",
        api_base_url="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        models=["claude-3-opus", "claude-3-sonnet"],
        priority=3,
    ),
]


@dataclass
class CircuitBreaker:
    """
    Circuit breaker for provider failure handling.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Provider failing, requests rejected immediately
    - HALF_OPEN: Testing if provider recovered
    """

    failure_threshold: int = 5  # Failures before opening
    recovery_timeout: int = 60  # Seconds before testing recovery
    half_open_max_calls: int = 3  # Test calls in half-open state

    # State tracking
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: datetime | None = None
    half_open_calls: int = 0

    def record_success(self) -> None:
        """Record a successful call."""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            self.half_open_calls += 1
            # If enough successes in half-open, close the circuit
            if self.success_count >= self.half_open_max_calls:
                self._close()
        else:
            self.failure_count = 0

    def record_failure(self) -> None:
        """Record a failed call."""
        self.failure_count += 1
        self.last_failure_time = datetime.now(UTC)

        if self.state == CircuitState.HALF_OPEN:
            # Any failure in half-open reopens the circuit
            self._open()
        elif self.failure_count >= self.failure_threshold:
            self._open()

    def can_execute(self) -> bool:
        """Check if a request can be executed."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if self.last_failure_time:
                time_since_failure = datetime.now(UTC) - self.last_failure_time
                if time_since_failure >= timedelta(seconds=self.recovery_timeout):
                    self._half_open()
                    return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            return self.half_open_calls < self.half_open_max_calls

        return False

    def _open(self) -> None:
        """Open the circuit (reject requests)."""
        self.state = CircuitState.OPEN
        logger.warning("circuit_breaker_opened", failure_count=self.failure_count)

    def _close(self) -> None:
        """Close the circuit (normal operation)."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.half_open_calls = 0
        logger.info("circuit_breaker_closed")

    def _half_open(self) -> None:
        """Set circuit to half-open (testing recovery)."""
        self.state = CircuitState.HALF_OPEN
        self.success_count = 0
        self.half_open_calls = 0
        logger.info("circuit_breaker_half_open")


@dataclass
class BudgetLimit:
    """Budget limit configuration."""

    daily_limit: float | None = None  # Daily spending limit in USD
    monthly_limit: float | None = None  # Monthly spending limit in USD
    per_request_limit: float | None = None  # Max cost per single request
    soft_limit_percent: float = 80.0  # Warning threshold percentage


@dataclass
class BudgetUsage:
    """Track budget usage for a tenant."""

    tenant_id: str
    daily_spend: float = 0.0
    monthly_spend: float = 0.0
    last_reset_daily: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_reset_monthly: datetime = field(default_factory=lambda: datetime.now(UTC))
    request_count_daily: int = 0
    request_count_monthly: int = 0

    def reset_if_needed(self) -> None:
        """Reset counters if time period has passed."""
        now = datetime.now(UTC)

        # Reset daily counters
        if now.date() > self.last_reset_daily.date():
            self.daily_spend = 0.0
            self.request_count_daily = 0
            self.last_reset_daily = now

        # Reset monthly counters
        if now.month != self.last_reset_monthly.month or now.year != self.last_reset_monthly.year:
            self.monthly_spend = 0.0
            self.request_count_monthly = 0
            self.last_reset_monthly = now


class BudgetEnforcementResult(str, Enum):
    """Result of budget check."""

    ALLOWED = "allowed"
    SOFT_LIMIT_WARNING = "soft_limit_warning"
    HARD_LIMIT_EXCEEDED = "hard_limit_exceeded"


@dataclass
class BudgetCheckResult:
    """Result of a budget check."""

    result: BudgetEnforcementResult
    estimated_cost: float
    daily_remaining: float | None
    monthly_remaining: float | None
    message: str | None = None


class CostTracker:
    """
    Tracks LLM costs per tenant with budget enforcement.

    Features:
    - Per-tenant cost tracking
    - Daily and monthly budget limits
    - Soft limits (warnings) and hard limits (blocking)
    - Request-level cost estimation
    """

    def __init__(self) -> None:
        """Initialize cost tracker."""
        self._usage: dict[str, BudgetUsage] = {}
        self._limits: dict[str, BudgetLimit] = {}
        self._default_limit = BudgetLimit()
        self._lock = asyncio.Lock()

    def set_tenant_limit(self, tenant_id: str, limit: BudgetLimit) -> None:
        """Set budget limits for a tenant."""
        self._limits[tenant_id] = limit

    def set_default_limit(self, limit: BudgetLimit) -> None:
        """Set default budget limits for all tenants."""
        self._default_limit = limit

    def get_limit(self, tenant_id: str) -> BudgetLimit:
        """Get budget limits for a tenant."""
        return self._limits.get(tenant_id, self._default_limit)

    async def check_budget(
        self,
        tenant_id: str,
        estimated_cost: float,
    ) -> BudgetCheckResult:
        """
        Check if a request is within budget.

        Args:
            tenant_id: Tenant identifier
            estimated_cost: Estimated cost of the request

        Returns:
            BudgetCheckResult with enforcement decision
        """
        async with self._lock:
            usage = self._get_or_create_usage(tenant_id)
            usage.reset_if_needed()

            limit = self.get_limit(tenant_id)

            # Check per-request limit
            if limit.per_request_limit and estimated_cost > limit.per_request_limit:
                return BudgetCheckResult(
                    result=BudgetEnforcementResult.HARD_LIMIT_EXCEEDED,
                    estimated_cost=estimated_cost,
                    daily_remaining=self._calculate_remaining(usage.daily_spend, limit.daily_limit),
                    monthly_remaining=self._calculate_remaining(
                        usage.monthly_spend, limit.monthly_limit
                    ),
                    message=f"Request cost ${estimated_cost:.4f} exceeds per-request limit ${limit.per_request_limit:.4f}",
                )

            # Check daily limit
            daily_remaining = None
            if limit.daily_limit:
                daily_remaining = limit.daily_limit - usage.daily_spend
                if usage.daily_spend + estimated_cost > limit.daily_limit:
                    return BudgetCheckResult(
                        result=BudgetEnforcementResult.HARD_LIMIT_EXCEEDED,
                        estimated_cost=estimated_cost,
                        daily_remaining=daily_remaining,
                        monthly_remaining=self._calculate_remaining(
                            usage.monthly_spend, limit.monthly_limit
                        ),
                        message=f"Daily budget exceeded (${usage.daily_spend:.2f}/${limit.daily_limit:.2f})",
                    )

            # Check monthly limit
            monthly_remaining = None
            if limit.monthly_limit:
                monthly_remaining = limit.monthly_limit - usage.monthly_spend
                if usage.monthly_spend + estimated_cost > limit.monthly_limit:
                    return BudgetCheckResult(
                        result=BudgetEnforcementResult.HARD_LIMIT_EXCEEDED,
                        estimated_cost=estimated_cost,
                        daily_remaining=daily_remaining,
                        monthly_remaining=monthly_remaining,
                        message=f"Monthly budget exceeded (${usage.monthly_spend:.2f}/${limit.monthly_limit:.2f})",
                    )

            # Check soft limits
            warning_message = None
            if limit.daily_limit:
                usage_percent = (usage.daily_spend / limit.daily_limit) * 100
                if usage_percent >= limit.soft_limit_percent:
                    warning_message = f"Daily budget at {usage_percent:.1f}%"

            if limit.monthly_limit:
                usage_percent = (usage.monthly_spend / limit.monthly_limit) * 100
                if usage_percent >= limit.soft_limit_percent:
                    warning_message = (
                        warning_message or ""
                    ) + f" Monthly budget at {usage_percent:.1f}%"

            if warning_message:
                return BudgetCheckResult(
                    result=BudgetEnforcementResult.SOFT_LIMIT_WARNING,
                    estimated_cost=estimated_cost,
                    daily_remaining=daily_remaining,
                    monthly_remaining=monthly_remaining,
                    message=warning_message.strip(),
                )

            return BudgetCheckResult(
                result=BudgetEnforcementResult.ALLOWED,
                estimated_cost=estimated_cost,
                daily_remaining=daily_remaining,
                monthly_remaining=monthly_remaining,
            )

    async def record_cost(self, tenant_id: str, actual_cost: float) -> None:
        """Record actual cost after a request."""
        async with self._lock:
            usage = self._get_or_create_usage(tenant_id)
            usage.reset_if_needed()
            usage.daily_spend += actual_cost
            usage.monthly_spend += actual_cost
            usage.request_count_daily += 1
            usage.request_count_monthly += 1

            logger.info(
                "cost_recorded",
                tenant_id=tenant_id,
                cost=actual_cost,
                daily_spend=usage.daily_spend,
                monthly_spend=usage.monthly_spend,
            )

    def get_usage(self, tenant_id: str) -> BudgetUsage:
        """Get current usage for a tenant."""
        usage = self._get_or_create_usage(tenant_id)
        usage.reset_if_needed()
        return usage

    def _get_or_create_usage(self, tenant_id: str) -> BudgetUsage:
        """Get or create usage record for tenant."""
        if tenant_id not in self._usage:
            self._usage[tenant_id] = BudgetUsage(tenant_id=tenant_id)
        return self._usage[tenant_id]

    def _calculate_remaining(self, spent: float, limit: float | None) -> float | None:
        """Calculate remaining budget."""
        if limit is None:
            return None
        return max(0, limit - spent)


@dataclass
class ProviderHealth:
    """Health status of a provider."""

    provider: str
    status: ProviderStatus
    circuit_state: CircuitState
    failure_count: int
    last_success: datetime | None
    last_failure: datetime | None
    avg_latency_ms: float | None


class ProviderManager:
    """
    Manages LLM providers with failover and health tracking.

    Features:
    - Provider chain with priority-based failover
    - Circuit breakers per provider
    - Health monitoring
    - Automatic recovery testing
    """

    def __init__(self, providers: list[ProviderConfig] | None = None) -> None:
        """
        Initialize provider manager.

        Args:
            providers: List of provider configurations (uses defaults if None)
        """
        self.providers = sorted(providers or DEFAULT_PROVIDERS, key=lambda p: p.priority)
        self._circuit_breakers: dict[str, CircuitBreaker] = {
            p.name: CircuitBreaker() for p in self.providers
        }
        self._last_success: dict[str, datetime] = {}
        self._last_failure: dict[str, datetime] = {}
        self._latencies: dict[str, list[float]] = {p.name: [] for p in self.providers}

    def get_available_provider(self) -> ProviderConfig | None:
        """
        Get the next available provider based on priority and health.

        Returns:
            ProviderConfig if available, None if all providers are unhealthy
        """
        for provider in self.providers:
            circuit = self._circuit_breakers[provider.name]
            if circuit.can_execute():
                return provider

        # All providers unhealthy, try the primary anyway
        logger.error("all_providers_unhealthy", providers=[p.name for p in self.providers])
        return self.providers[0] if self.providers else None

    def record_success(self, provider_name: str, latency_ms: float) -> None:
        """Record a successful request."""
        if provider_name in self._circuit_breakers:
            self._circuit_breakers[provider_name].record_success()
            self._last_success[provider_name] = datetime.now(UTC)

            # Track latency (keep last 100)
            latencies = self._latencies.get(provider_name, [])
            latencies.append(latency_ms)
            self._latencies[provider_name] = latencies[-100:]

    def record_failure(self, provider_name: str) -> None:
        """Record a failed request."""
        if provider_name in self._circuit_breakers:
            self._circuit_breakers[provider_name].record_failure()
            self._last_failure[provider_name] = datetime.now(UTC)

    def get_health(self) -> list[ProviderHealth]:
        """Get health status of all providers."""
        health: list[ProviderHealth] = []

        for provider in self.providers:
            circuit = self._circuit_breakers[provider.name]
            latencies = self._latencies.get(provider.name, [])

            status = ProviderStatus.HEALTHY
            if circuit.state == CircuitState.OPEN:
                status = ProviderStatus.UNHEALTHY
            elif circuit.state == CircuitState.HALF_OPEN:
                status = ProviderStatus.DEGRADED

            health.append(
                ProviderHealth(
                    provider=provider.name,
                    status=status,
                    circuit_state=circuit.state,
                    failure_count=circuit.failure_count,
                    last_success=self._last_success.get(provider.name),
                    last_failure=self._last_failure.get(provider.name),
                    avg_latency_ms=sum(latencies) / len(latencies) if latencies else None,
                )
            )

        return health

    def reset_circuit(self, provider_name: str) -> None:
        """Manually reset a provider's circuit breaker."""
        if provider_name in self._circuit_breakers:
            self._circuit_breakers[provider_name] = CircuitBreaker()
            logger.info("circuit_breaker_reset", provider=provider_name)


def estimate_request_cost(
    model: str,
    estimated_input_tokens: int,
    estimated_output_tokens: int,
    provider_config: ProviderConfig | None = None,
) -> float:
    """
    Estimate cost for a request before making it.

    Args:
        model: Model name
        estimated_input_tokens: Estimated input tokens
        estimated_output_tokens: Estimated output tokens
        provider_config: Optional provider config for cost lookup

    Returns:
        Estimated cost in USD
    """
    # Use provider-specific costs if available
    if provider_config and model in provider_config.cost_per_1k_tokens:
        costs = provider_config.cost_per_1k_tokens[model]
    else:
        # Default costs
        default_costs: dict[str, dict[str, float]] = {
            "gpt-4": {"input": 0.03, "output": 0.06},
            "gpt-4-turbo": {"input": 0.01, "output": 0.03},
            "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
            "claude-3-opus": {"input": 0.015, "output": 0.075},
            "claude-3-sonnet": {"input": 0.003, "output": 0.015},
        }
        costs = default_costs.get(model, {"input": 0.01, "output": 0.03})

    input_cost = (estimated_input_tokens / 1000) * costs["input"]
    output_cost = (estimated_output_tokens / 1000) * costs["output"]

    return input_cost + output_cost


def estimate_tokens(text: str) -> int:
    """
    Estimate token count for text (rough approximation).

    Uses ~4 characters per token as a rough estimate.
    For accurate counts, use tiktoken or provider-specific tokenizers.
    """
    return len(text) // 4 + 1


# Module-level singletons
_cost_tracker: CostTracker | None = None
_provider_manager: ProviderManager | None = None


def get_cost_tracker() -> CostTracker:
    """Get or create the cost tracker singleton."""
    global _cost_tracker
    if _cost_tracker is None:
        _cost_tracker = CostTracker()
    return _cost_tracker


def get_provider_manager() -> ProviderManager:
    """Get or create the provider manager singleton."""
    global _provider_manager
    if _provider_manager is None:
        _provider_manager = ProviderManager()
    return _provider_manager
