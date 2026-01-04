"""
Server-Sent Events (SSE) streaming for real-time LLM responses.

Provides:
- SSE event formatting
- Streaming response generator
- Client connection management
"""

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.core.observability import get_logger

logger = get_logger()


class SSEEventType(str, Enum):
    """Types of SSE events."""

    MESSAGE = "message"
    TOKEN = "token"
    PROGRESS = "progress"
    ERROR = "error"
    DONE = "done"
    HEARTBEAT = "heartbeat"


@dataclass
class SSEEvent:
    """A Server-Sent Event."""

    event: SSEEventType
    data: dict[str, Any] | str
    id: str | None = None
    retry: int | None = None

    def format(self) -> str:
        """Format event as SSE string."""
        lines = []

        if self.id:
            lines.append(f"id: {self.id}")

        if self.retry:
            lines.append(f"retry: {self.retry}")

        lines.append(f"event: {self.event.value}")

        # Data can be multi-line, each line prefixed with "data: "
        data_str = json.dumps(self.data) if isinstance(self.data, dict) else str(self.data)
        for line in data_str.split("\n"):
            lines.append(f"data: {line}")

        # SSE events end with double newline
        return "\n".join(lines) + "\n\n"


class StreamingResponse:
    """
    Helper for building streaming SSE responses.

    Example:
        async def stream_handler():
            stream = StreamingResponse()

            yield stream.event(SSEEventType.PROGRESS, {"status": "starting"})

            async for token in llm_stream():
                yield stream.token(token)

            yield stream.done({"total_tokens": 100})
    """

    def __init__(self, request_id: str | None = None):
        """Initialize streaming response."""
        self.request_id = request_id
        self._event_counter = 0

    def _next_id(self) -> str:
        """Generate next event ID."""
        self._event_counter += 1
        prefix = f"{self.request_id}-" if self.request_id else ""
        return f"{prefix}{self._event_counter}"

    def event(
        self,
        event_type: SSEEventType,
        data: dict[str, Any] | str,
    ) -> str:
        """Create a formatted SSE event."""
        return SSEEvent(
            event=event_type,
            data=data,
            id=self._next_id(),
        ).format()

    def token(self, token: str) -> str:
        """Create a token event."""
        return self.event(SSEEventType.TOKEN, {"token": token})

    def progress(self, status: str, **kwargs: Any) -> str:
        """Create a progress event."""
        return self.event(SSEEventType.PROGRESS, {"status": status, **kwargs})

    def error(self, message: str, code: str | None = None) -> str:
        """Create an error event."""
        data = {"error": message}
        if code:
            data["code"] = code
        return self.event(SSEEventType.ERROR, data)

    def done(self, metadata: dict[str, Any] | None = None) -> str:
        """Create a done event."""
        return self.event(SSEEventType.DONE, metadata or {"status": "complete"})

    def heartbeat(self) -> str:
        """Create a heartbeat event (keeps connection alive)."""
        return SSEEvent(
            event=SSEEventType.HEARTBEAT,
            data="",
        ).format()


async def stream_llm_response(
    llm_gateway: Any,
    prompt: str,
    request_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    Stream LLM response as SSE events.

    This wraps the LLM gateway to provide streaming output.

    Args:
        llm_gateway: LLM gateway instance
        prompt: Prompt to send to LLM
        request_id: Optional request ID for event tracking

    Yields:
        SSE formatted event strings
    """
    stream = StreamingResponse(request_id)

    yield stream.progress("starting", message="Initializing LLM request")

    try:
        # For now, simulate streaming by chunking the response
        # In production, this would use actual streaming API
        response = await llm_gateway._complete(prompt, operation="stream")

        # Simulate token streaming
        words = response.content.split()
        for i, word in enumerate(words):
            token = word + (" " if i < len(words) - 1 else "")
            yield stream.token(token)

        yield stream.done(
            {
                "status": "complete",
                "model": response.model,
                "latency_ms": response.latency_ms,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cost_estimate": response.cost_estimate,
            }
        )

        logger.info(
            "stream_completed",
            request_id=request_id,
            tokens=response.output_tokens,
        )

    except Exception as e:
        logger.error("stream_error", request_id=request_id, error=str(e))
        yield stream.error(str(e), code="LLM_ERROR")


async def stream_agent_execution(
    agent_generator: AsyncGenerator[dict[str, Any], None],
    request_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    Stream agent execution progress as SSE events.

    Args:
        agent_generator: Async generator yielding agent state updates
        request_id: Optional request ID for event tracking

    Yields:
        SSE formatted event strings
    """
    stream = StreamingResponse(request_id)

    yield stream.progress("starting", message="Agent execution starting")

    try:
        async for update in agent_generator:
            node = update.get("node", "unknown")
            state = update.get("state", {})

            yield stream.progress(
                f"executing_{node}",
                node=node,
                state_keys=list(state.keys()) if isinstance(state, dict) else [],
            )

            # If there's a response in the state, stream it token by token
            if response := state.get("response"):
                words = response.split()
                for i, word in enumerate(words):
                    token = word + (" " if i < len(words) - 1 else "")
                    yield stream.token(token)

        yield stream.done({"status": "complete"})

    except Exception as e:
        logger.error("agent_stream_error", request_id=request_id, error=str(e))
        yield stream.error(str(e), code="AGENT_ERROR")
