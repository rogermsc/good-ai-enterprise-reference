"""
LLM Gateway - Single point of control for all LLM interactions.

The gateway:
1. Accepts only pre-redacted prompts (PII must be tokenized)
2. Supports multiple providers (OpenAI, mock)
3. Tracks latency and estimated costs
4. Provides deterministic mock responses for testing

IMPORTANT: Never pass raw PII to this gateway. Use PIIRedactor first.
"""

import time
from dataclasses import dataclass

import httpx
from opentelemetry import trace

from src.core.config import Settings, get_settings
from src.core.observability import (
    get_logger,
    get_tracer,
    llm_cost_counter,
    llm_request_counter,
    llm_request_duration,
    llm_token_counter,
)

logger = get_logger()
tracer = get_tracer()


@dataclass
class LLMResponse:
    """Response from LLM gateway."""

    content: str
    model: str
    provider: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cost_estimate: float
    is_mock: bool = False


# Cost estimates per 1K tokens (approximate, for tracking)
COST_PER_1K_TOKENS: dict[str, dict[str, float]] = {
    "gpt-4": {"input": 0.03, "output": 0.06},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
}


class LLMGateway:
    """
    Gateway for LLM interactions.

    Provides a unified interface for LLM calls with:
    - Mock mode for testing without API keys
    - Cost tracking
    - Latency measurement
    - Provider abstraction

    Example:
        gateway = LLMGateway()

        # Classify severity (with redacted content)
        response = await gateway.classify_severity(
            "Customer [PII_EMAIL_1] reports [PII_CPF_2] data exposed"
        )

        # Generate response
        response = await gateway.generate_response(
            ticket_content="[Redacted ticket content]",
            severity="P2",
            context="Password reset request",
        )
    """

    def __init__(self, settings: Settings | None = None):
        """Initialize gateway with settings."""
        self.settings = settings or get_settings()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.llm_timeout_seconds),
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def classify_severity(self, ticket_content: str) -> LLMResponse:
        """
        Classify ticket severity using LLM.

        Args:
            ticket_content: Redacted ticket content

        Returns:
            LLMResponse with severity classification (P0-P4)
        """
        if self.settings.is_mock_mode:
            return self._mock_classify_severity(ticket_content)

        prompt = f"""Classify the severity of this support ticket.
Respond with ONLY one of: P0, P1, P2, P3, P4

Severity definitions:
- P0 (Critical): Production down, data breach, security incident
- P1 (High): Major feature broken, significant customer impact
- P2 (Medium): Feature degraded, workaround available
- P3 (Low): Minor issue, cosmetic problem
- P4 (Info): Question, feature request, documentation

Ticket content:
{ticket_content}

Severity:"""

        return await self._complete(prompt, operation="classify_severity")

    async def recommend_actions(
        self,
        ticket_content: str,
        severity: str,
    ) -> LLMResponse:
        """
        Recommend actions for a ticket.

        Args:
            ticket_content: Redacted ticket content
            severity: Classified severity

        Returns:
            LLMResponse with recommended actions
        """
        if self.settings.is_mock_mode:
            return self._mock_recommend_actions(ticket_content, severity)

        prompt = f"""Based on this {severity} severity support ticket, recommend appropriate actions.

Available actions:
- read_ticket: Read ticket details
- classify: Classify the ticket
- respond: Send response to customer
- escalate_to_engineering: Escalate to engineering team
- escalate_to_security: Escalate to security team
- escalate_to_management: Escalate to management
- notify_customer: Send notification to customer
- refund_customer: Process customer refund
- access_customer_data: Access customer account data
- create_incident: Create incident ticket
- page_oncall: Page on-call engineer

Respond with a JSON array of action names. Example: ["escalate_to_engineering", "notify_customer"]

Ticket content:
{ticket_content}

Recommended actions (JSON array only):"""

        return await self._complete(prompt, operation="recommend_actions")

    async def generate_response(
        self,
        ticket_content: str,
        severity: str,
        actions: list[str],
    ) -> LLMResponse:
        """
        Generate customer response.

        Args:
            ticket_content: Redacted ticket content
            severity: Ticket severity
            actions: Actions being taken

        Returns:
            LLMResponse with customer-facing response
        """
        if self.settings.is_mock_mode:
            return self._mock_generate_response(ticket_content, severity)

        prompt = f"""Generate a professional customer support response for this ticket.

Ticket severity: {severity}
Actions being taken: {", ".join(actions)}

Ticket content:
{ticket_content}

Guidelines:
- Be empathetic and professional
- Acknowledge the issue clearly
- Explain what actions are being taken
- Provide expected timeline if applicable
- Do not make promises you cannot keep
- Keep PII tokens in place (they will be replaced later)

Customer response:"""

        return await self._complete(prompt, operation="generate_response")

    async def _complete(self, prompt: str, operation: str = "complete") -> LLMResponse:
        """Make LLM API call with tracing and metrics."""
        with tracer.start_as_current_span(f"llm.{operation}") as span:
            start_time = time.time()

            # Set span attributes
            span.set_attribute("llm.provider", self.settings.llm_provider)
            span.set_attribute("llm.model", self.settings.model_name)
            span.set_attribute("llm.operation", operation)

            client = await self._get_client()

            headers = {
                "Authorization": f"Bearer {self.settings.openai_api_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": self.settings.model_name,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 500,
            }

            try:
                response = await client.post(
                    f"{self.settings.openai_base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()

                data = response.json()
                latency_ms = int((time.time() - start_time) * 1000)

                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)

                cost = self._estimate_cost(
                    self.settings.model_name,
                    input_tokens,
                    output_tokens,
                )

                # Record metrics
                labels = {"model": self.settings.model_name, "operation": operation}
                llm_request_counter.add(1, {**labels, "status": "success"})
                llm_request_duration.record(latency_ms, labels)
                llm_token_counter.add(input_tokens, {**labels, "type": "input"})
                llm_token_counter.add(output_tokens, {**labels, "type": "output"})
                llm_cost_counter.add(cost, labels)

                # Add response details to span
                span.set_attribute("llm.latency_ms", latency_ms)
                span.set_attribute("llm.input_tokens", input_tokens)
                span.set_attribute("llm.output_tokens", output_tokens)
                span.set_attribute("llm.cost_estimate", cost)
                span.set_status(trace.Status(trace.StatusCode.OK))

                logger.info(
                    "llm_request_completed",
                    operation=operation,
                    model=self.settings.model_name,
                    latency_ms=latency_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost=cost,
                )

                return LLMResponse(
                    content=content.strip(),
                    model=self.settings.model_name,
                    provider=self.settings.llm_provider,
                    latency_ms=latency_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_estimate=cost,
                    is_mock=False,
                )

            except Exception as e:
                llm_request_counter.add(
                    1,
                    {"model": self.settings.model_name, "operation": operation, "status": "error"},
                )
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                span.record_exception(e)
                logger.error("llm_request_failed", operation=operation, error=str(e))
                raise

    def _estimate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Estimate API cost based on token usage."""
        costs = COST_PER_1K_TOKENS.get(model, {"input": 0.01, "output": 0.03})
        return (input_tokens / 1000) * costs["input"] + (output_tokens / 1000) * costs["output"]

    # Mock implementations for testing without API keys
    def _mock_classify_severity(self, content: str) -> LLMResponse:
        """Mock severity classification based on keywords."""
        content_lower = content.lower()

        # Keyword-based mock classification
        if any(
            word in content_lower
            for word in [
                "breach",
                "data leak",
                "security",
                "unauthorized",
                "production down",
                "outage",
            ]
        ):
            severity = "P0"
        elif any(
            word in content_lower
            for word in ["urgent", "broken", "critical", "not working", "error", "crash"]
        ):
            severity = "P1"
        elif any(word in content_lower for word in ["slow", "issue", "problem", "bug", "degraded"]):
            severity = "P2"
        elif any(
            word in content_lower for word in ["question", "how to", "help", "password", "reset"]
        ):
            severity = "P3"
        else:
            severity = "P4"

        return LLMResponse(
            content=severity,
            model="mock",
            provider="mock",
            latency_ms=10,
            input_tokens=len(content.split()),
            output_tokens=1,
            cost_estimate=0.0,
            is_mock=True,
        )

    def _mock_recommend_actions(
        self,
        content: str,
        severity: str,
    ) -> LLMResponse:
        """Mock action recommendations based on severity."""
        content_lower = content.lower()

        if severity == "P0":
            actions = (
                '["escalate_to_security", "create_incident", "page_oncall", "notify_customer"]'
            )
        elif severity == "P1":
            actions = '["escalate_to_engineering", "create_incident", "notify_customer"]'
        elif severity == "P2":
            actions = '["classify", "respond", "notify_customer"]'
        elif "password" in content_lower or "reset" in content_lower:
            actions = '["classify", "respond"]'
        else:
            actions = '["classify", "respond"]'

        return LLMResponse(
            content=actions,
            model="mock",
            provider="mock",
            latency_ms=10,
            input_tokens=len(content.split()),
            output_tokens=len(actions.split()),
            cost_estimate=0.0,
            is_mock=True,
        )

    def _mock_generate_response(
        self,
        content: str,
        severity: str,
    ) -> LLMResponse:
        """Mock customer response generation."""
        if severity in ("P0", "P1"):
            response = """Thank you for contacting us about this urgent issue.

We have escalated your ticket to our engineering team and they are actively investigating. You will receive updates as we make progress.

We understand the impact this is having and are treating it as a top priority.

Best regards,
Support Team"""
        else:
            response = """Thank you for reaching out to our support team.

We have received your request and are working on it. A member of our team will respond with a resolution shortly.

If you have any additional information to share, please reply to this message.

Best regards,
Support Team"""

        return LLMResponse(
            content=response,
            model="mock",
            provider="mock",
            latency_ms=15,
            input_tokens=len(content.split()),
            output_tokens=len(response.split()),
            cost_estimate=0.0,
            is_mock=True,
        )
