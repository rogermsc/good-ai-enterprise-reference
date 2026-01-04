"""
Observability module for distributed tracing, metrics, and structured logging.

Provides:
- OpenTelemetry tracing with automatic instrumentation
- Custom metrics for LLM operations
- Structured JSON logging with trace correlation
"""

import logging
import sys
from contextvars import ContextVar
from functools import wraps
from typing import Any, ParamSpec, TypeVar

import structlog
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import Status, StatusCode

from src.core.config import get_settings

# Type variables for decorator
P = ParamSpec("P")
T = TypeVar("T")

# Context variable for request-scoped data (None default, use .set() to initialize)
request_context: ContextVar[dict[str, Any] | None] = ContextVar("request_context", default=None)


def setup_observability(service_name: str = "good-ai-enterprise") -> None:
    """
    Initialize OpenTelemetry tracing, metrics, and structured logging.

    Args:
        service_name: Name of the service for telemetry identification
    """
    settings = get_settings()

    # Create resource with service information
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": "1.0.0",
            "deployment.environment": settings.environment,
        }
    )

    # Setup tracing
    _setup_tracing(resource, settings.otlp_endpoint)

    # Setup metrics
    _setup_metrics(resource, settings.otlp_endpoint)

    # Setup structured logging
    _setup_logging()


def _setup_tracing(resource: Resource, otlp_endpoint: str | None) -> None:
    """Configure OpenTelemetry tracing."""
    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        # Export to OTLP collector (Jaeger, Tempo, etc.)
        otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
    else:
        # Fallback to console exporter for development
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)


def _setup_metrics(resource: Resource, otlp_endpoint: str | None) -> None:
    """Configure OpenTelemetry metrics."""
    if otlp_endpoint:
        exporter = OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)
        reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60000)
        provider = MeterProvider(resource=resource, metric_readers=[reader])
    else:
        # No-op metrics in development without collector
        provider = MeterProvider(resource=resource)

    metrics.set_meter_provider(provider)


def _setup_logging() -> None:
    """Configure structured logging with structlog."""

    # Add trace context to log entries
    def add_trace_context(
        logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
    ) -> dict[str, Any]:
        span = trace.get_current_span()
        if span.is_recording():
            ctx = span.get_span_context()
            event_dict["trace_id"] = format(ctx.trace_id, "032x")
            event_dict["span_id"] = format(ctx.span_id, "016x")

        # Add request context
        req_ctx = request_context.get()
        if req_ctx:
            event_dict.update(req_ctx)

        return event_dict

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            add_trace_context,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def instrument_app(app: Any) -> None:
    """
    Instrument FastAPI application with automatic tracing.

    Args:
        app: FastAPI application instance
    """
    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()
    AsyncPGInstrumentor().instrument()


def get_tracer(name: str = "good-ai-enterprise") -> trace.Tracer:
    """Get a tracer instance for manual instrumentation."""
    return trace.get_tracer(name)


def get_meter(name: str = "good-ai-enterprise") -> metrics.Meter:
    """Get a meter instance for custom metrics."""
    return metrics.get_meter(name)


def get_logger(name: str = "good-ai-enterprise") -> structlog.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)


# Pre-configured metrics for LLM operations
_meter = get_meter()

llm_request_counter = _meter.create_counter(
    name="llm.requests",
    description="Number of LLM requests",
    unit="1",
)

llm_request_duration = _meter.create_histogram(
    name="llm.request.duration",
    description="LLM request duration in milliseconds",
    unit="ms",
)

llm_token_counter = _meter.create_counter(
    name="llm.tokens",
    description="Number of tokens processed",
    unit="1",
)

llm_cost_counter = _meter.create_counter(
    name="llm.cost",
    description="Estimated cost of LLM operations",
    unit="USD",
)

pii_detection_counter = _meter.create_counter(
    name="pii.detections",
    description="Number of PII items detected",
    unit="1",
)

policy_decision_counter = _meter.create_counter(
    name="policy.decisions",
    description="Number of policy decisions made",
    unit="1",
)


def trace_llm_call(operation: str):
    """
    Decorator to trace LLM operations with timing and error handling.

    Args:
        operation: Name of the LLM operation (e.g., "classify", "generate")
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            tracer = get_tracer()
            logger = get_logger()

            with tracer.start_as_current_span(f"llm.{operation}") as span:
                span.set_attribute("llm.operation", operation)

                try:
                    result = await func(*args, **kwargs)

                    # Record success metrics
                    llm_request_counter.add(1, {"operation": operation, "status": "success"})

                    if hasattr(result, "cost_estimate"):
                        llm_cost_counter.add(result.cost_estimate, {"operation": operation})

                    span.set_status(Status(StatusCode.OK))
                    return result

                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.record_exception(e)

                    llm_request_counter.add(1, {"operation": operation, "status": "error"})
                    logger.error("llm_operation_failed", operation=operation, error=str(e))

                    raise

        return wrapper

    return decorator


def trace_agent_node(node_name: str):
    """
    Decorator to trace LangGraph agent nodes.

    Args:
        node_name: Name of the agent node
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            tracer = get_tracer()
            logger = get_logger()

            with tracer.start_as_current_span(f"agent.node.{node_name}") as span:
                span.set_attribute("agent.node", node_name)

                logger.info("agent_node_started", node=node_name)

                try:
                    result = await func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    logger.info("agent_node_completed", node=node_name)
                    return result

                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.record_exception(e)
                    logger.error("agent_node_failed", node=node_name, error=str(e))
                    raise

        return wrapper

    return decorator
