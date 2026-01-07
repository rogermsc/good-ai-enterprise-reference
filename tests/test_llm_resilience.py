"""Tests for LLM resilience module - failover, circuit breaker, and cost controls."""

from datetime import UTC, datetime, timedelta

import pytest

from src.core.llm_resilience import (
    BudgetEnforcementResult,
    BudgetLimit,
    BudgetUsage,
    CircuitBreaker,
    CircuitState,
    CostTracker,
    ProviderConfig,
    ProviderManager,
    ProviderStatus,
    estimate_request_cost,
    estimate_tokens,
)


class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""

    def test_initial_state_is_closed(self) -> None:
        """Circuit starts in closed state."""
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.can_execute() is True

    def test_opens_after_threshold_failures(self) -> None:
        """Circuit opens after reaching failure threshold."""
        cb = CircuitBreaker(failure_threshold=3)

        # Record failures up to threshold
        for _ in range(3):
            cb.record_failure()

        assert cb.state == CircuitState.OPEN
        assert cb.can_execute() is False

    def test_success_resets_failure_count(self) -> None:
        """Success in closed state resets failure count."""
        cb = CircuitBreaker(failure_threshold=5)

        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2

        cb.record_success()
        assert cb.failure_count == 0

    def test_half_open_after_recovery_timeout(self) -> None:
        """Circuit transitions to half-open after recovery timeout."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=1)

        # Open the circuit
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Simulate time passing
        cb.last_failure_time = datetime.now(UTC) - timedelta(seconds=2)

        # Should transition to half-open
        assert cb.can_execute() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_closes_after_successes(self) -> None:
        """Circuit closes after enough successes in half-open state."""
        cb = CircuitBreaker(failure_threshold=2, half_open_max_calls=2)

        # Get to half-open state
        cb.state = CircuitState.HALF_OPEN
        cb.success_count = 0
        cb.half_open_calls = 0

        # Record successful calls
        cb.record_success()
        cb.record_success()

        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_half_open_reopens_on_failure(self) -> None:
        """Circuit reopens on any failure in half-open state."""
        cb = CircuitBreaker()
        cb.state = CircuitState.HALF_OPEN

        cb.record_failure()

        assert cb.state == CircuitState.OPEN


class TestBudgetUsage:
    """Tests for BudgetUsage class."""

    def test_reset_daily_counters(self) -> None:
        """Daily counters reset when date changes."""
        usage = BudgetUsage(
            tenant_id="test",
            daily_spend=100.0,
            request_count_daily=50,
            last_reset_daily=datetime.now(UTC) - timedelta(days=1),
        )

        usage.reset_if_needed()

        assert usage.daily_spend == 0.0
        assert usage.request_count_daily == 0

    def test_reset_monthly_counters(self) -> None:
        """Monthly counters reset when month changes."""
        usage = BudgetUsage(
            tenant_id="test",
            monthly_spend=500.0,
            request_count_monthly=100,
            last_reset_monthly=datetime.now(UTC) - timedelta(days=32),
        )

        usage.reset_if_needed()

        assert usage.monthly_spend == 0.0
        assert usage.request_count_monthly == 0

    def test_no_reset_same_period(self) -> None:
        """Counters not reset within same period."""
        now = datetime.now(UTC)
        usage = BudgetUsage(
            tenant_id="test",
            daily_spend=50.0,
            monthly_spend=200.0,
            last_reset_daily=now,
            last_reset_monthly=now,
        )

        usage.reset_if_needed()

        assert usage.daily_spend == 50.0
        assert usage.monthly_spend == 200.0


class TestCostTracker:
    """Tests for CostTracker class."""

    @pytest.fixture
    def tracker(self) -> CostTracker:
        """Create a cost tracker for testing."""
        return CostTracker()

    @pytest.mark.asyncio
    async def test_check_budget_allowed(self, tracker: CostTracker) -> None:
        """Request allowed when within budget."""
        result = await tracker.check_budget("tenant1", 0.10)

        assert result.result == BudgetEnforcementResult.ALLOWED
        assert result.estimated_cost == 0.10

    @pytest.mark.asyncio
    async def test_check_budget_per_request_limit_exceeded(self, tracker: CostTracker) -> None:
        """Request blocked when exceeding per-request limit."""
        tracker.set_tenant_limit("tenant1", BudgetLimit(per_request_limit=0.05))

        result = await tracker.check_budget("tenant1", 0.10)

        assert result.result == BudgetEnforcementResult.HARD_LIMIT_EXCEEDED
        assert "per-request limit" in (result.message or "")

    @pytest.mark.asyncio
    async def test_check_budget_daily_limit_exceeded(self, tracker: CostTracker) -> None:
        """Request blocked when daily limit would be exceeded."""
        tracker.set_tenant_limit("tenant1", BudgetLimit(daily_limit=1.00))

        # Record some spending
        await tracker.record_cost("tenant1", 0.95)

        # This request would exceed daily limit
        result = await tracker.check_budget("tenant1", 0.10)

        assert result.result == BudgetEnforcementResult.HARD_LIMIT_EXCEEDED
        assert "Daily budget exceeded" in (result.message or "")

    @pytest.mark.asyncio
    async def test_check_budget_monthly_limit_exceeded(self, tracker: CostTracker) -> None:
        """Request blocked when monthly limit would be exceeded."""
        tracker.set_tenant_limit("tenant1", BudgetLimit(monthly_limit=10.00))

        # Record spending
        await tracker.record_cost("tenant1", 9.95)

        result = await tracker.check_budget("tenant1", 0.10)

        assert result.result == BudgetEnforcementResult.HARD_LIMIT_EXCEEDED
        assert "Monthly budget exceeded" in (result.message or "")

    @pytest.mark.asyncio
    async def test_check_budget_soft_limit_warning(self, tracker: CostTracker) -> None:
        """Warning when approaching soft limit."""
        tracker.set_tenant_limit(
            "tenant1",
            BudgetLimit(daily_limit=10.00, soft_limit_percent=80.0),
        )

        # Record 85% of daily budget
        await tracker.record_cost("tenant1", 8.50)

        result = await tracker.check_budget("tenant1", 0.10)

        assert result.result == BudgetEnforcementResult.SOFT_LIMIT_WARNING
        assert "Daily budget at" in (result.message or "")

    @pytest.mark.asyncio
    async def test_record_cost_updates_usage(self, tracker: CostTracker) -> None:
        """Recording cost updates usage counters."""
        await tracker.record_cost("tenant1", 0.50)
        await tracker.record_cost("tenant1", 0.25)

        usage = tracker.get_usage("tenant1")

        assert usage.daily_spend == 0.75
        assert usage.monthly_spend == 0.75
        assert usage.request_count_daily == 2

    @pytest.mark.asyncio
    async def test_separate_tenant_tracking(self, tracker: CostTracker) -> None:
        """Tenants have separate budget tracking."""
        await tracker.record_cost("tenant1", 1.00)
        await tracker.record_cost("tenant2", 0.50)

        usage1 = tracker.get_usage("tenant1")
        usage2 = tracker.get_usage("tenant2")

        assert usage1.daily_spend == 1.00
        assert usage2.daily_spend == 0.50


class TestProviderManager:
    """Tests for ProviderManager class."""

    @pytest.fixture
    def providers(self) -> list[ProviderConfig]:
        """Create test providers."""
        return [
            ProviderConfig(
                name="primary",
                api_base_url="https://api.primary.com",
                api_key_env="PRIMARY_KEY",
                models=["model-a"],
                priority=1,
            ),
            ProviderConfig(
                name="secondary",
                api_base_url="https://api.secondary.com",
                api_key_env="SECONDARY_KEY",
                models=["model-b"],
                priority=2,
            ),
            ProviderConfig(
                name="fallback",
                api_base_url="https://api.fallback.com",
                api_key_env="FALLBACK_KEY",
                models=["model-c"],
                priority=3,
            ),
        ]

    @pytest.fixture
    def manager(self, providers: list[ProviderConfig]) -> ProviderManager:
        """Create provider manager with test providers."""
        return ProviderManager(providers)

    def test_returns_highest_priority_provider(self, manager: ProviderManager) -> None:
        """Returns provider with lowest priority number."""
        provider = manager.get_available_provider()

        assert provider is not None
        assert provider.name == "primary"

    def test_failover_to_secondary_when_primary_unhealthy(self, manager: ProviderManager) -> None:
        """Falls back to secondary when primary circuit is open."""
        # Open primary's circuit
        for _ in range(5):
            manager.record_failure("primary")

        provider = manager.get_available_provider()

        assert provider is not None
        assert provider.name == "secondary"

    def test_failover_chain_through_all_providers(self, manager: ProviderManager) -> None:
        """Falls back through entire chain."""
        # Open primary and secondary circuits
        for _ in range(5):
            manager.record_failure("primary")
            manager.record_failure("secondary")

        provider = manager.get_available_provider()

        assert provider is not None
        assert provider.name == "fallback"

    def test_returns_primary_as_last_resort(self, manager: ProviderManager) -> None:
        """Returns primary even when all circuits are open."""
        # Open all circuits
        for _ in range(5):
            manager.record_failure("primary")
            manager.record_failure("secondary")
            manager.record_failure("fallback")

        provider = manager.get_available_provider()

        # Should return primary as last resort
        assert provider is not None
        assert provider.name == "primary"

    def test_success_resets_circuit(self, manager: ProviderManager) -> None:
        """Successful calls reset circuit breaker."""
        # Create some failures
        manager.record_failure("primary")
        manager.record_failure("primary")

        # Record success
        manager.record_success("primary", 100.0)

        health = manager.get_health()
        primary_health = next(h for h in health if h.provider == "primary")

        assert primary_health.status == ProviderStatus.HEALTHY
        assert primary_health.failure_count == 0

    def test_health_tracking(self, manager: ProviderManager) -> None:
        """Health status reflects circuit state."""
        # Open primary circuit
        for _ in range(5):
            manager.record_failure("primary")

        health = manager.get_health()
        primary_health = next(h for h in health if h.provider == "primary")

        assert primary_health.status == ProviderStatus.UNHEALTHY
        assert primary_health.circuit_state == CircuitState.OPEN

    def test_latency_tracking(self, manager: ProviderManager) -> None:
        """Tracks average latency."""
        manager.record_success("primary", 100.0)
        manager.record_success("primary", 200.0)
        manager.record_success("primary", 150.0)

        health = manager.get_health()
        primary_health = next(h for h in health if h.provider == "primary")

        assert primary_health.avg_latency_ms == 150.0

    def test_reset_circuit_manually(self, manager: ProviderManager) -> None:
        """Can manually reset a circuit breaker."""
        # Open circuit
        for _ in range(5):
            manager.record_failure("primary")

        manager.reset_circuit("primary")

        health = manager.get_health()
        primary_health = next(h for h in health if h.provider == "primary")

        assert primary_health.status == ProviderStatus.HEALTHY
        assert primary_health.circuit_state == CircuitState.CLOSED


class TestCostEstimation:
    """Tests for cost estimation functions."""

    def test_estimate_tokens_basic(self) -> None:
        """Basic token estimation."""
        # ~4 chars per token
        text = "Hello world"  # 11 chars
        tokens = estimate_tokens(text)

        assert tokens == 3  # 11 // 4 + 1

    def test_estimate_tokens_empty_string(self) -> None:
        """Empty string returns 1 token minimum."""
        tokens = estimate_tokens("")
        assert tokens == 1

    def test_estimate_request_cost_default_model(self) -> None:
        """Estimate cost for known model."""
        cost = estimate_request_cost(
            model="gpt-4",
            estimated_input_tokens=1000,
            estimated_output_tokens=500,
        )

        # gpt-4: $0.03/1k input, $0.06/1k output
        expected = (1000 / 1000) * 0.03 + (500 / 1000) * 0.06
        assert cost == expected

    def test_estimate_request_cost_unknown_model(self) -> None:
        """Estimate cost uses default for unknown model."""
        cost = estimate_request_cost(
            model="unknown-model",
            estimated_input_tokens=1000,
            estimated_output_tokens=500,
        )

        # Default: $0.01/1k input, $0.03/1k output
        expected = (1000 / 1000) * 0.01 + (500 / 1000) * 0.03
        assert cost == expected

    def test_estimate_request_cost_with_provider_config(self) -> None:
        """Estimate cost using provider-specific pricing."""
        provider = ProviderConfig(
            name="custom",
            api_base_url="https://api.custom.com",
            api_key_env="CUSTOM_KEY",
            models=["custom-model"],
            cost_per_1k_tokens={
                "custom-model": {"input": 0.001, "output": 0.002},
            },
        )

        cost = estimate_request_cost(
            model="custom-model",
            estimated_input_tokens=1000,
            estimated_output_tokens=1000,
            provider_config=provider,
        )

        expected = (1000 / 1000) * 0.001 + (1000 / 1000) * 0.002
        assert cost == expected
