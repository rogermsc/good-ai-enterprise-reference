"""
Model Fallback System for LLM Resilience.

Provides automatic failover between LLM providers/models when:
- Primary model is unavailable
- Rate limits are exceeded
- Errors occur during inference

Features:
- Configurable model priority chain
- Circuit breaker pattern for failing models
- Exponential backoff retry logic
- Health monitoring and metrics
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, TypeVar

import httpx

from src.core.config import Settings, get_settings
from src.core.observability import get_logger, get_tracer

logger = get_logger()
tracer = get_tracer()

T = TypeVar("T")


class ModelStatus(str, Enum):
    """Health status of a model."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CIRCUIT_OPEN = "circuit_open"


class ErrorType(str, Enum):
    """Types of errors that can trigger fallback."""

    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    SERVER_ERROR = "server_error"
    AUTH_ERROR = "auth_error"
    INVALID_RESPONSE = "invalid_response"
    UNKNOWN = "unknown"


@dataclass
class ModelConfig:
    """Configuration for an LLM model."""

    name: str
    provider: str  # openai, anthropic, azure, mock
    model_id: str
    priority: int = 0  # Lower = higher priority
    max_retries: int = 3
    timeout_seconds: float = 30.0
    rate_limit_rpm: int = 60  # Requests per minute
    cost_per_1k_input: float = 0.01
    cost_per_1k_output: float = 0.03
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CircuitBreakerState:
    """State for circuit breaker pattern."""

    failure_count: int = 0
    last_failure_time: datetime | None = None
    circuit_open_until: datetime | None = None
    success_count_since_half_open: int = 0

    # Configuration
    failure_threshold: int = 5
    recovery_timeout_seconds: int = 60
    half_open_max_requests: int = 3

    def record_failure(self) -> None:
        """Record a failure and potentially open the circuit."""
        self.failure_count += 1
        self.last_failure_time = datetime.now(UTC)
        self.success_count_since_half_open = 0

        if self.failure_count >= self.failure_threshold:
            self.circuit_open_until = datetime.now(UTC)

    def record_success(self) -> None:
        """Record a success."""
        if self.is_half_open:
            self.success_count_since_half_open += 1
            if self.success_count_since_half_open >= self.half_open_max_requests:
                # Close circuit - model is healthy again
                self.reset()
        else:
            # Normal success - just reset failure count
            self.failure_count = 0

    def reset(self) -> None:
        """Reset the circuit breaker."""
        self.failure_count = 0
        self.last_failure_time = None
        self.circuit_open_until = None
        self.success_count_since_half_open = 0

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (blocking requests)."""
        if self.circuit_open_until is None:
            return False

        now = datetime.now(UTC)
        recovery_time = self.circuit_open_until.timestamp() + self.recovery_timeout_seconds
        return now.timestamp() < recovery_time

    @property
    def is_half_open(self) -> bool:
        """Check if circuit is half-open (allowing test requests)."""
        if self.circuit_open_until is None:
            return False

        now = datetime.now(UTC)
        recovery_time = self.circuit_open_until.timestamp() + self.recovery_timeout_seconds
        return now.timestamp() >= recovery_time and self.failure_count >= self.failure_threshold


@dataclass
class FallbackResult:
    """Result of a fallback operation."""

    success: bool
    content: str | None = None
    model_used: str | None = None
    attempts: int = 0
    total_latency_ms: int = 0
    error: str | None = None
    error_type: ErrorType | None = None
    fallback_chain: list[str] = field(default_factory=list)


class ModelRegistry:
    """
    Registry for managing LLM models with fallback support.

    Example:
        registry = ModelRegistry()
        registry.register(ModelConfig(
            name="gpt-4",
            provider="openai",
            model_id="gpt-4-turbo",
            priority=0,
        ))
        registry.register(ModelConfig(
            name="gpt-3.5",
            provider="openai",
            model_id="gpt-3.5-turbo",
            priority=1,
        ))

        # Get models in priority order
        models = registry.get_fallback_chain()
    """

    def __init__(self) -> None:
        self._models: dict[str, ModelConfig] = {}
        self._circuit_breakers: dict[str, CircuitBreakerState] = {}

    def register(self, config: ModelConfig) -> None:
        """Register a model configuration."""
        self._models[config.name] = config
        self._circuit_breakers[config.name] = CircuitBreakerState()
        logger.info(
            "model_registered",
            name=config.name,
            provider=config.provider,
            priority=config.priority,
        )

    def unregister(self, name: str) -> bool:
        """Unregister a model."""
        if name in self._models:
            del self._models[name]
            del self._circuit_breakers[name]
            return True
        return False

    def get(self, name: str) -> ModelConfig | None:
        """Get a model by name."""
        return self._models.get(name)

    def get_circuit_breaker(self, name: str) -> CircuitBreakerState | None:
        """Get circuit breaker state for a model."""
        return self._circuit_breakers.get(name)

    def get_fallback_chain(self, exclude_unhealthy: bool = True) -> list[ModelConfig]:
        """
        Get models in priority order for fallback.

        Args:
            exclude_unhealthy: Skip models with open circuits

        Returns:
            List of ModelConfig in priority order
        """
        models = [m for m in self._models.values() if m.enabled]

        if exclude_unhealthy:
            models = [m for m in models if not self._circuit_breakers[m.name].is_open]

        return sorted(models, key=lambda m: m.priority)

    def get_status(self, name: str) -> ModelStatus:
        """Get health status of a model."""
        if name not in self._models:
            return ModelStatus.UNHEALTHY

        cb = self._circuit_breakers[name]

        if cb.is_open:
            return ModelStatus.CIRCUIT_OPEN
        if cb.is_half_open:
            return ModelStatus.DEGRADED
        if cb.failure_count > 0:
            return ModelStatus.DEGRADED

        return ModelStatus.HEALTHY

    def get_all_status(self) -> dict[str, ModelStatus]:
        """Get status of all models."""
        return {name: self.get_status(name) for name in self._models}


class ModelFallbackService:
    """
    Service for executing LLM calls with automatic fallback.

    Provides:
    - Automatic retry with exponential backoff
    - Circuit breaker pattern
    - Fallback to alternative models
    - Metrics and logging

    Example:
        service = ModelFallbackService()

        result = await service.execute(
            func=call_llm,
            prompt="Hello",
            preferred_model="gpt-4",
        )

        if result.success:
            print(f"Response from {result.model_used}: {result.content}")
        else:
            print(f"All models failed: {result.error}")
    """

    def __init__(
        self,
        registry: ModelRegistry | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.registry = registry or self._create_default_registry()
        self.settings = settings or get_settings()

    def _create_default_registry(self) -> ModelRegistry:
        """Create registry with default models."""
        registry = ModelRegistry()

        # Primary model
        registry.register(
            ModelConfig(
                name="gpt-4-turbo",
                provider="openai",
                model_id="gpt-4-turbo-preview",
                priority=0,
                cost_per_1k_input=0.01,
                cost_per_1k_output=0.03,
            )
        )

        # Fallback models
        registry.register(
            ModelConfig(
                name="gpt-4",
                provider="openai",
                model_id="gpt-4",
                priority=1,
                cost_per_1k_input=0.03,
                cost_per_1k_output=0.06,
            )
        )

        registry.register(
            ModelConfig(
                name="gpt-3.5-turbo",
                provider="openai",
                model_id="gpt-3.5-turbo",
                priority=2,
                cost_per_1k_input=0.0005,
                cost_per_1k_output=0.0015,
            )
        )

        # Mock fallback for testing
        registry.register(
            ModelConfig(
                name="mock",
                provider="mock",
                model_id="mock-model",
                priority=99,
                cost_per_1k_input=0.0,
                cost_per_1k_output=0.0,
            )
        )

        return registry

    async def execute(
        self,
        func: Callable[..., Any],
        *args: Any,
        preferred_model: str | None = None,
        max_fallbacks: int = 3,
        **kwargs: Any,
    ) -> FallbackResult:
        """
        Execute a function with automatic fallback.

        Args:
            func: Async function to execute
            *args: Positional arguments for func
            preferred_model: Preferred model name (skips to it in chain)
            max_fallbacks: Maximum number of fallback attempts
            **kwargs: Keyword arguments for func

        Returns:
            FallbackResult with outcome details
        """
        with tracer.start_as_current_span("model_fallback.execute") as span:
            start_time = time.time()
            fallback_chain = self.registry.get_fallback_chain()
            attempts = 0
            models_tried: list[str] = []

            # If preferred model specified, reorder chain
            if preferred_model:
                preferred = self.registry.get(preferred_model)
                if preferred and preferred in fallback_chain:
                    fallback_chain.remove(preferred)
                    fallback_chain.insert(0, preferred)

            span.set_attribute("fallback_chain", [m.name for m in fallback_chain])

            last_error: str | None = None
            last_error_type: ErrorType | None = None

            for model in fallback_chain[:max_fallbacks]:
                attempts += 1
                models_tried.append(model.name)

                span.set_attribute("current_model", model.name)
                span.set_attribute("attempt", attempts)

                # Check circuit breaker
                cb = self.registry.get_circuit_breaker(model.name)
                if cb and cb.is_open:
                    logger.info(
                        "model_circuit_open",
                        model=model.name,
                        skipping=True,
                    )
                    continue

                try:
                    # Execute with retry
                    result = await self._execute_with_retry(func, model, *args, **kwargs)

                    # Record success
                    if cb:
                        cb.record_success()

                    total_latency = int((time.time() - start_time) * 1000)

                    logger.info(
                        "model_fallback_success",
                        model=model.name,
                        attempts=attempts,
                        latency_ms=total_latency,
                    )

                    return FallbackResult(
                        success=True,
                        content=result,
                        model_used=model.name,
                        attempts=attempts,
                        total_latency_ms=total_latency,
                        fallback_chain=models_tried,
                    )

                except Exception as e:
                    error_type = self._classify_error(e)
                    last_error = str(e)
                    last_error_type = error_type

                    # Record failure
                    if cb:
                        cb.record_failure()

                    logger.warning(
                        "model_attempt_failed",
                        model=model.name,
                        error_type=error_type.value,
                        error=str(e),
                        attempt=attempts,
                    )

                    # Continue to next model
                    continue

            # All models failed
            total_latency = int((time.time() - start_time) * 1000)

            logger.error(
                "model_fallback_exhausted",
                attempts=attempts,
                models_tried=models_tried,
                last_error=last_error,
            )

            return FallbackResult(
                success=False,
                model_used=None,
                attempts=attempts,
                total_latency_ms=total_latency,
                error=last_error,
                error_type=last_error_type,
                fallback_chain=models_tried,
            )

    async def _execute_with_retry(
        self,
        func: Callable[..., Any],
        model: ModelConfig,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute function with exponential backoff retry."""
        last_error: Exception | None = None

        for attempt in range(model.max_retries):
            try:
                # Add model info to kwargs if function accepts it
                kwargs_with_model = {**kwargs, "model": model.model_id}

                # Execute with timeout
                result = await asyncio.wait_for(
                    func(*args, **kwargs_with_model),
                    timeout=model.timeout_seconds,
                )
                return result

            except TimeoutError as e:
                last_error = e
                logger.warning(
                    "model_timeout",
                    model=model.name,
                    attempt=attempt + 1,
                    timeout=model.timeout_seconds,
                )

            except Exception as e:
                last_error = e

                # Don't retry auth errors
                if self._classify_error(e) == ErrorType.AUTH_ERROR:
                    raise

                logger.warning(
                    "model_retry",
                    model=model.name,
                    attempt=attempt + 1,
                    error=str(e),
                )

            # Exponential backoff
            if attempt < model.max_retries - 1:
                backoff = min(2**attempt, 8)  # Max 8 seconds
                await asyncio.sleep(backoff)

        if last_error:
            raise last_error
        raise RuntimeError("No attempts made")

    def _classify_error(self, error: Exception) -> ErrorType:
        """Classify an error for appropriate handling."""
        error_str = str(error).lower()

        if isinstance(error, asyncio.TimeoutError):
            return ErrorType.TIMEOUT

        if isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code
            if status == 429:
                return ErrorType.RATE_LIMIT
            if status == 401 or status == 403:
                return ErrorType.AUTH_ERROR
            if status >= 500:
                return ErrorType.SERVER_ERROR

        if "rate limit" in error_str or "429" in error_str:
            return ErrorType.RATE_LIMIT

        if "timeout" in error_str:
            return ErrorType.TIMEOUT

        if "unauthorized" in error_str or "forbidden" in error_str:
            return ErrorType.AUTH_ERROR

        if "server error" in error_str or "500" in error_str:
            return ErrorType.SERVER_ERROR

        return ErrorType.UNKNOWN

    def get_health(self) -> dict[str, Any]:
        """Get health status of all models."""
        statuses = self.registry.get_all_status()
        healthy_count = sum(1 for s in statuses.values() if s == ModelStatus.HEALTHY)

        return {
            "overall": "healthy" if healthy_count > 0 else "unhealthy",
            "healthy_models": healthy_count,
            "total_models": len(statuses),
            "models": {
                name: {
                    "status": status.value,
                    "circuit_breaker": self._get_circuit_breaker_info(name),
                }
                for name, status in statuses.items()
            },
        }

    def _get_circuit_breaker_info(self, name: str) -> dict[str, Any]:
        """Get circuit breaker details for a model."""
        cb = self.registry.get_circuit_breaker(name)
        if not cb:
            return {}

        return {
            "failure_count": cb.failure_count,
            "is_open": cb.is_open,
            "is_half_open": cb.is_half_open,
            "last_failure": cb.last_failure_time.isoformat() if cb.last_failure_time else None,
        }


# Convenience function
async def execute_with_fallback(
    func: Callable[..., Any],
    *args: Any,
    preferred_model: str | None = None,
    **kwargs: Any,
) -> FallbackResult:
    """
    Execute a function with automatic model fallback.

    Args:
        func: Async function to execute
        *args: Positional arguments
        preferred_model: Preferred model name
        **kwargs: Keyword arguments

    Returns:
        FallbackResult with outcome
    """
    service = ModelFallbackService()
    return await service.execute(func, *args, preferred_model=preferred_model, **kwargs)
