"""Tests for model fallback system."""

import asyncio

import pytest

from src.core.model_fallback import (
    CircuitBreakerState,
    ErrorType,
    FallbackResult,
    ModelConfig,
    ModelFallbackService,
    ModelRegistry,
    ModelStatus,
)


class TestCircuitBreaker:
    """Tests for circuit breaker logic."""

    def test_initial_state(self) -> None:
        cb = CircuitBreakerState()
        assert cb.failure_count == 0
        assert not cb.is_open
        assert not cb.is_half_open

    def test_records_failures(self) -> None:
        cb = CircuitBreakerState(failure_threshold=3)
        cb.record_failure()
        assert cb.failure_count == 1
        assert not cb.is_open

        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 3
        assert cb.is_open

    def test_opens_after_threshold(self) -> None:
        cb = CircuitBreakerState(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open
        assert cb.circuit_open_until is not None

    def test_success_resets_failure_count(self) -> None:
        cb = CircuitBreakerState()
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2

        cb.record_success()
        assert cb.failure_count == 0

    def test_reset_clears_state(self) -> None:
        cb = CircuitBreakerState(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open

        cb.reset()
        assert cb.failure_count == 0
        assert not cb.is_open
        assert cb.circuit_open_until is None


class TestModelConfig:
    """Tests for model configuration."""

    def test_default_values(self) -> None:
        config = ModelConfig(
            name="test-model",
            provider="openai",
            model_id="gpt-4",
        )
        assert config.priority == 0
        assert config.max_retries == 3
        assert config.timeout_seconds == 30.0
        assert config.enabled is True

    def test_custom_values(self) -> None:
        config = ModelConfig(
            name="custom",
            provider="anthropic",
            model_id="claude-3",
            priority=5,
            max_retries=5,
            timeout_seconds=60.0,
            cost_per_1k_input=0.015,
        )
        assert config.priority == 5
        assert config.max_retries == 5
        assert config.cost_per_1k_input == 0.015


class TestModelRegistry:
    """Tests for model registry."""

    def test_register_model(self) -> None:
        registry = ModelRegistry()
        config = ModelConfig(name="test", provider="openai", model_id="gpt-4")
        registry.register(config)

        assert registry.get("test") == config

    def test_unregister_model(self) -> None:
        registry = ModelRegistry()
        config = ModelConfig(name="test", provider="openai", model_id="gpt-4")
        registry.register(config)

        assert registry.unregister("test") is True
        assert registry.get("test") is None
        assert registry.unregister("nonexistent") is False

    def test_fallback_chain_ordering(self) -> None:
        registry = ModelRegistry()
        registry.register(ModelConfig(name="low", provider="openai", model_id="a", priority=2))
        registry.register(ModelConfig(name="high", provider="openai", model_id="b", priority=0))
        registry.register(ModelConfig(name="mid", provider="openai", model_id="c", priority=1))

        chain = registry.get_fallback_chain()
        assert [m.name for m in chain] == ["high", "mid", "low"]

    def test_excludes_disabled_models(self) -> None:
        registry = ModelRegistry()
        registry.register(
            ModelConfig(name="enabled", provider="openai", model_id="a", enabled=True)
        )
        registry.register(
            ModelConfig(name="disabled", provider="openai", model_id="b", enabled=False)
        )

        chain = registry.get_fallback_chain()
        assert len(chain) == 1
        assert chain[0].name == "enabled"

    def test_excludes_circuit_open_models(self) -> None:
        registry = ModelRegistry()
        registry.register(ModelConfig(name="healthy", provider="openai", model_id="a", priority=1))
        registry.register(
            ModelConfig(name="unhealthy", provider="openai", model_id="b", priority=0)
        )

        # Open circuit for unhealthy model
        cb = registry.get_circuit_breaker("unhealthy")
        for _ in range(5):
            cb.record_failure()

        chain = registry.get_fallback_chain(exclude_unhealthy=True)
        assert len(chain) == 1
        assert chain[0].name == "healthy"

    def test_model_status(self) -> None:
        registry = ModelRegistry()
        registry.register(ModelConfig(name="test", provider="openai", model_id="a"))

        assert registry.get_status("test") == ModelStatus.HEALTHY
        assert registry.get_status("nonexistent") == ModelStatus.UNHEALTHY

        # Add failures
        cb = registry.get_circuit_breaker("test")
        cb.record_failure()
        assert registry.get_status("test") == ModelStatus.DEGRADED

        # Open circuit
        for _ in range(5):
            cb.record_failure()
        assert registry.get_status("test") == ModelStatus.CIRCUIT_OPEN


class TestModelFallbackService:
    """Tests for fallback service."""

    @pytest.fixture
    def service(self) -> ModelFallbackService:
        registry = ModelRegistry()
        registry.register(ModelConfig(name="primary", provider="mock", model_id="a", priority=0))
        registry.register(ModelConfig(name="secondary", provider="mock", model_id="b", priority=1))
        registry.register(ModelConfig(name="tertiary", provider="mock", model_id="c", priority=2))
        return ModelFallbackService(registry=registry)

    async def test_successful_execution(self, service: ModelFallbackService) -> None:
        async def success_func(*args, **kwargs) -> str:
            return "success"

        result = await service.execute(success_func)
        assert result.success is True
        assert result.content == "success"
        assert result.model_used == "primary"
        assert result.attempts == 1

    async def test_fallback_on_failure(self, service: ModelFallbackService) -> None:
        # Make primary fail always by setting max_retries to 1
        service.registry.get("primary").max_retries = 1

        async def fail_on_primary(*args, **kwargs) -> str:
            model = kwargs.get("model", "")
            if model == "a":  # primary's model_id
                raise RuntimeError("Primary always fails")
            return "fallback success"

        result = await service.execute(fail_on_primary)
        assert result.success is True
        assert result.content == "fallback success"
        assert result.model_used == "secondary"
        assert result.attempts == 2

    async def test_all_models_fail(self, service: ModelFallbackService) -> None:
        async def always_fail(*args, **kwargs) -> str:
            raise RuntimeError("Always fails")

        result = await service.execute(always_fail, max_fallbacks=3)
        assert result.success is False
        assert result.error is not None
        assert result.attempts == 3
        assert len(result.fallback_chain) == 3

    async def test_preferred_model(self, service: ModelFallbackService) -> None:
        async def return_model(*args, **kwargs) -> str:
            return kwargs.get("model", "unknown")

        result = await service.execute(return_model, preferred_model="secondary")
        assert result.success is True
        assert result.model_used == "secondary"

    async def test_circuit_breaker_skips_model(self, service: ModelFallbackService) -> None:
        # Open circuit for primary
        cb = service.registry.get_circuit_breaker("primary")
        for _ in range(5):
            cb.record_failure()

        async def success_func(*args, **kwargs) -> str:
            return kwargs.get("model", "unknown")

        result = await service.execute(success_func)
        assert result.success is True
        assert result.model_used == "secondary"

    async def test_health_check(self, service: ModelFallbackService) -> None:
        health = service.get_health()
        assert health["overall"] == "healthy"
        assert health["healthy_models"] == 3
        assert health["total_models"] == 3
        assert "primary" in health["models"]

    async def test_timeout_handling(self, service: ModelFallbackService) -> None:
        async def slow_func(*args, **kwargs) -> str:
            await asyncio.sleep(100)
            return "never"

        # Set very short timeout
        service.registry.get("primary").timeout_seconds = 0.1
        service.registry.get("secondary").timeout_seconds = 0.1
        service.registry.get("tertiary").timeout_seconds = 0.1

        result = await service.execute(slow_func, max_fallbacks=2)
        assert result.success is False
        assert result.error_type == ErrorType.TIMEOUT


class TestFallbackResult:
    """Tests for fallback result."""

    def test_success_result(self) -> None:
        result = FallbackResult(
            success=True,
            content="response",
            model_used="gpt-4",
            attempts=1,
            total_latency_ms=100,
        )
        assert result.success is True
        assert result.content == "response"
        assert result.error is None

    def test_failure_result(self) -> None:
        result = FallbackResult(
            success=False,
            error="All models failed",
            error_type=ErrorType.SERVER_ERROR,
            attempts=3,
            fallback_chain=["a", "b", "c"],
        )
        assert result.success is False
        assert result.content is None
        assert result.error == "All models failed"
        assert len(result.fallback_chain) == 3


class TestErrorClassification:
    """Tests for error classification."""

    def test_classify_timeout(self) -> None:
        service = ModelFallbackService()
        error_type = service._classify_error(TimeoutError())
        assert error_type == ErrorType.TIMEOUT

    def test_classify_rate_limit_from_string(self) -> None:
        service = ModelFallbackService()
        error_type = service._classify_error(RuntimeError("rate limit exceeded"))
        assert error_type == ErrorType.RATE_LIMIT

    def test_classify_unknown(self) -> None:
        service = ModelFallbackService()
        error_type = service._classify_error(RuntimeError("random error"))
        assert error_type == ErrorType.UNKNOWN
