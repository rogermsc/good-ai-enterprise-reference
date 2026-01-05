"""
Output Guardrails for LLM Response Validation.

Validates LLM outputs before they reach users to ensure:
- Content safety (no harmful/toxic content)
- No PII leakage in responses
- No prompt injection attempts in outputs
- Format compliance
- Topic relevance

All guardrails are configurable and can be enabled/disabled per-request.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar

from src.core.observability import get_logger, get_tracer
from src.core.pii_redaction import PIIRedactor

logger = get_logger()
tracer = get_tracer()


class GuardrailSeverity(str, Enum):
    """Severity level of guardrail violations."""

    LOW = "low"  # Warning only, allow response
    MEDIUM = "medium"  # Flag for review, may allow
    HIGH = "high"  # Block response
    CRITICAL = "critical"  # Block and alert


class GuardrailAction(str, Enum):
    """Action to take on guardrail violation."""

    ALLOW = "allow"  # Allow response through
    WARN = "warn"  # Allow but log warning
    REDACT = "redact"  # Redact problematic content
    BLOCK = "block"  # Block the response entirely


@dataclass
class GuardrailViolation:
    """A single guardrail violation."""

    guardrail_name: str
    severity: GuardrailSeverity
    message: str
    matched_content: str | None = None
    suggested_action: GuardrailAction = GuardrailAction.BLOCK
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GuardrailResult:
    """Result of running guardrails on content."""

    passed: bool
    violations: list[GuardrailViolation] = field(default_factory=list)
    filtered_content: str | None = None
    action_taken: GuardrailAction = GuardrailAction.ALLOW
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_violations(self) -> bool:
        """Check if any violations occurred."""
        return len(self.violations) > 0

    @property
    def highest_severity(self) -> GuardrailSeverity | None:
        """Get the highest severity violation."""
        if not self.violations:
            return None
        severity_order = [
            GuardrailSeverity.LOW,
            GuardrailSeverity.MEDIUM,
            GuardrailSeverity.HIGH,
            GuardrailSeverity.CRITICAL,
        ]
        return max(self.violations, key=lambda v: severity_order.index(v.severity)).severity


class Guardrail(ABC):
    """Base class for output guardrails."""

    name: str = "base_guardrail"
    description: str = "Base guardrail"
    default_severity: GuardrailSeverity = GuardrailSeverity.MEDIUM

    @abstractmethod
    def check(
        self, content: str, context: dict[str, Any] | None = None
    ) -> list[GuardrailViolation]:
        """
        Check content for violations.

        Args:
            content: The LLM output to check
            context: Optional context (original prompt, user info, etc.)

        Returns:
            List of violations found
        """
        pass


class PIILeakageGuardrail(Guardrail):
    """
    Detects PII that may have leaked into LLM outputs.

    Even though inputs are redacted, the LLM might:
    - Hallucinate PII-like patterns
    - Leak training data containing PII
    - Generate plausible but fake PII
    """

    name = "pii_leakage"
    description = "Detects PII patterns in LLM outputs"
    default_severity = GuardrailSeverity.HIGH

    def __init__(self) -> None:
        self.redactor = PIIRedactor()

    def check(
        self, content: str, context: dict[str, Any] | None = None
    ) -> list[GuardrailViolation]:
        violations = []

        # Check for PII patterns in output
        result = self.redactor.redact(content)
        if result.token_map:
            pii_types = set()
            for token in result.token_map:
                # Extract PII type from token like [PII_EMAIL_1]
                match = re.match(r"\[PII_(\w+)_\d+\]", token)
                if match:
                    pii_types.add(match.group(1))

            violations.append(
                GuardrailViolation(
                    guardrail_name=self.name,
                    severity=self.default_severity,
                    message=f"PII detected in output: {', '.join(pii_types)}",
                    matched_content=str(list(result.token_map.values())[:3]),  # Show first 3
                    suggested_action=GuardrailAction.REDACT,
                    metadata={"pii_types": list(pii_types), "count": len(result.token_map)},
                )
            )

        return violations


class ToxicityGuardrail(Guardrail):
    """
    Detects toxic, harmful, or inappropriate content.

    Uses keyword matching for demo; production should use
    a classifier model (Perspective API, OpenAI Moderation, etc.)
    """

    name = "toxicity"
    description = "Detects toxic or harmful content"
    default_severity = GuardrailSeverity.HIGH

    # Patterns that indicate harmful content (simplified for demo)
    HARMFUL_PATTERNS: ClassVar[list[tuple[str, str]]] = [
        (
            r"\b(kill|murder|attack|harm)\s+(yourself|himself|herself|themselves|someone)\b",
            "violence",
        ),
        (
            r"\b(how\s+to\s+make|instructions\s+for)\s+(bomb|weapon|poison)\b",
            "dangerous_instructions",
        ),
        (r"\b(hate|inferior|subhuman)\s+\w*\s*(race|religion|gender)\b", "hate_speech"),
    ]

    # Words that should trigger review (not immediate block)
    REVIEW_WORDS: ClassVar[list[str]] = [
        "suicide",
        "self-harm",
        "explosive",
        "illegal",
    ]

    def check(
        self, content: str, context: dict[str, Any] | None = None
    ) -> list[GuardrailViolation]:
        violations = []
        content_lower = content.lower()

        # Check harmful patterns
        for pattern, category in self.HARMFUL_PATTERNS:
            matches = re.findall(pattern, content_lower, re.IGNORECASE)
            if matches:
                violations.append(
                    GuardrailViolation(
                        guardrail_name=self.name,
                        severity=GuardrailSeverity.CRITICAL,
                        message=f"Harmful content detected: {category}",
                        matched_content=str(matches[0]) if matches else None,
                        suggested_action=GuardrailAction.BLOCK,
                        metadata={"category": category},
                    )
                )

        # Check review words
        for word in self.REVIEW_WORDS:
            if word in content_lower:
                violations.append(
                    GuardrailViolation(
                        guardrail_name=self.name,
                        severity=GuardrailSeverity.MEDIUM,
                        message=f"Content contains sensitive word: {word}",
                        matched_content=word,
                        suggested_action=GuardrailAction.WARN,
                        metadata={"word": word},
                    )
                )

        return violations


class PromptInjectionGuardrail(Guardrail):
    """
    Detects prompt injection attempts in LLM outputs.

    The LLM might be tricked into outputting instructions
    that could manipulate downstream systems.
    """

    name = "prompt_injection"
    description = "Detects prompt injection patterns in outputs"
    default_severity = GuardrailSeverity.HIGH

    # Patterns that suggest prompt injection in output
    INJECTION_PATTERNS: ClassVar[list[tuple[str, str]]] = [
        (r"ignore\s+(previous|all|above)\s+(instructions|prompts)", "instruction_override"),
        (r"you\s+are\s+now\s+in\s+\w+\s+mode", "mode_switch"),
        (r"system:\s*\w+", "system_prompt_leak"),
        (r"<\|?(system|assistant|user)\|?>", "role_tag_injection"),
        (r"```\s*(system|prompt|instruction)", "code_block_injection"),
        (r"act\s+as\s+(if\s+you\s+are|a)\s+\w+", "persona_injection"),
    ]

    def check(
        self, content: str, context: dict[str, Any] | None = None
    ) -> list[GuardrailViolation]:
        violations = []
        content_lower = content.lower()

        for pattern, category in self.INJECTION_PATTERNS:
            if re.search(pattern, content_lower, re.IGNORECASE):
                violations.append(
                    GuardrailViolation(
                        guardrail_name=self.name,
                        severity=self.default_severity,
                        message=f"Potential prompt injection detected: {category}",
                        matched_content=None,
                        suggested_action=GuardrailAction.BLOCK,
                        metadata={"category": category},
                    )
                )

        return violations


class TopicRelevanceGuardrail(Guardrail):
    """
    Ensures LLM output stays on-topic.

    Checks that responses are relevant to the expected domain.
    """

    name = "topic_relevance"
    description = "Ensures responses stay on-topic"
    default_severity = GuardrailSeverity.LOW

    # Off-topic indicators for a support ticket system
    OFF_TOPIC_PATTERNS: ClassVar[list[tuple[str, str]]] = [
        (r"(stock|crypto|bitcoin|investment)\s+(price|tip|advice)", "financial_advice"),
        (r"(recipe|cooking|baking)\s+(for|instructions)", "cooking"),
        (r"(political|vote|election)\s+(opinion|candidate)", "politics"),
    ]

    def check(
        self, content: str, context: dict[str, Any] | None = None
    ) -> list[GuardrailViolation]:
        violations = []
        content_lower = content.lower()

        # Check expected domain from context
        expected_domain = (context or {}).get("domain", "support")

        for pattern, category in self.OFF_TOPIC_PATTERNS:
            if re.search(pattern, content_lower, re.IGNORECASE):
                violations.append(
                    GuardrailViolation(
                        guardrail_name=self.name,
                        severity=self.default_severity,
                        message=f"Off-topic content detected: {category}",
                        matched_content=None,
                        suggested_action=GuardrailAction.WARN,
                        metadata={"category": category, "expected_domain": expected_domain},
                    )
                )

        return violations


class FormatComplianceGuardrail(Guardrail):
    """
    Validates that LLM output follows expected format.

    Can check for JSON validity, length limits, required fields, etc.
    """

    name = "format_compliance"
    description = "Validates output format compliance"
    default_severity = GuardrailSeverity.MEDIUM

    def __init__(
        self,
        max_length: int | None = None,
        min_length: int | None = None,
        required_patterns: list[str] | None = None,
        forbidden_patterns: list[str] | None = None,
    ) -> None:
        self.max_length = max_length
        self.min_length = min_length
        self.required_patterns = required_patterns or []
        self.forbidden_patterns = forbidden_patterns or []

    def check(
        self, content: str, context: dict[str, Any] | None = None
    ) -> list[GuardrailViolation]:
        violations = []

        # Length checks
        if self.max_length and len(content) > self.max_length:
            violations.append(
                GuardrailViolation(
                    guardrail_name=self.name,
                    severity=GuardrailSeverity.LOW,
                    message=f"Content exceeds max length: {len(content)} > {self.max_length}",
                    suggested_action=GuardrailAction.WARN,
                    metadata={"length": len(content), "max_length": self.max_length},
                )
            )

        if self.min_length and len(content) < self.min_length:
            violations.append(
                GuardrailViolation(
                    guardrail_name=self.name,
                    severity=GuardrailSeverity.LOW,
                    message=f"Content below min length: {len(content)} < {self.min_length}",
                    suggested_action=GuardrailAction.WARN,
                    metadata={"length": len(content), "min_length": self.min_length},
                )
            )

        # Required patterns
        for pattern in self.required_patterns:
            if not re.search(pattern, content, re.IGNORECASE):
                violations.append(
                    GuardrailViolation(
                        guardrail_name=self.name,
                        severity=self.default_severity,
                        message=f"Missing required pattern: {pattern}",
                        suggested_action=GuardrailAction.WARN,
                        metadata={"pattern": pattern},
                    )
                )

        # Forbidden patterns
        for pattern in self.forbidden_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                violations.append(
                    GuardrailViolation(
                        guardrail_name=self.name,
                        severity=self.default_severity,
                        message=f"Forbidden pattern found: {pattern}",
                        suggested_action=GuardrailAction.BLOCK,
                        metadata={"pattern": pattern},
                    )
                )

        return violations


class ConfidentialityGuardrail(Guardrail):
    """
    Prevents leakage of confidential information.

    Checks for internal references, system details, etc.
    """

    name = "confidentiality"
    description = "Prevents confidential information leakage"
    default_severity = GuardrailSeverity.HIGH

    CONFIDENTIAL_PATTERNS: ClassVar[list[tuple[str, str]]] = [
        (r"internal\s+(use\s+only|document|memo)", "internal_document"),
        (r"api[_\s]?key\s*[:=]\s*\S+", "api_key"),
        (r"password\s*[:=]\s*\S+", "password"),
        (r"secret\s*[:=]\s*\S+", "secret"),
        (r"Bearer\s+[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+", "bearer_token"),
        (r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----", "private_key"),
    ]

    def check(
        self, content: str, context: dict[str, Any] | None = None
    ) -> list[GuardrailViolation]:
        violations = []

        for pattern, category in self.CONFIDENTIAL_PATTERNS:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                violations.append(
                    GuardrailViolation(
                        guardrail_name=self.name,
                        severity=GuardrailSeverity.CRITICAL,
                        message=f"Confidential information detected: {category}",
                        matched_content="[REDACTED]",  # Don't log the actual content
                        suggested_action=GuardrailAction.BLOCK,
                        metadata={"category": category},
                    )
                )

        return violations


class GuardrailPipeline:
    """
    Pipeline for running multiple guardrails on content.

    Example:
        pipeline = GuardrailPipeline([
            PIILeakageGuardrail(),
            ToxicityGuardrail(),
            PromptInjectionGuardrail(),
        ])

        result = pipeline.run("LLM output text here")
        if not result.passed:
            handle_violations(result.violations)
    """

    def __init__(
        self,
        guardrails: list[Guardrail] | None = None,
        fail_fast: bool = False,
        auto_redact_pii: bool = True,
    ) -> None:
        """
        Initialize the guardrail pipeline.

        Args:
            guardrails: List of guardrails to run
            fail_fast: Stop on first violation
            auto_redact_pii: Automatically redact PII in violations
        """
        self.guardrails = guardrails or self._default_guardrails()
        self.fail_fast = fail_fast
        self.auto_redact_pii = auto_redact_pii
        self._pii_redactor = PIIRedactor() if auto_redact_pii else None

    def _default_guardrails(self) -> list[Guardrail]:
        """Get default guardrail set."""
        return [
            PIILeakageGuardrail(),
            ToxicityGuardrail(),
            PromptInjectionGuardrail(),
            ConfidentialityGuardrail(),
            TopicRelevanceGuardrail(),
        ]

    def run(
        self,
        content: str,
        context: dict[str, Any] | None = None,
    ) -> GuardrailResult:
        """
        Run all guardrails on content.

        Args:
            content: LLM output to validate
            context: Optional context for guardrails

        Returns:
            GuardrailResult with violations and recommended action
        """
        with tracer.start_as_current_span("guardrails.run") as span:
            span.set_attribute("content_length", len(content))
            span.set_attribute("guardrail_count", len(self.guardrails))

            all_violations: list[GuardrailViolation] = []
            filtered_content = content

            for guardrail in self.guardrails:
                try:
                    violations = guardrail.check(content, context)
                    all_violations.extend(violations)

                    if self.fail_fast and violations:
                        break

                except Exception as e:
                    logger.error(
                        "guardrail_error",
                        guardrail=guardrail.name,
                        error=str(e),
                    )
                    # Continue with other guardrails

            # Determine action based on violations
            action = self._determine_action(all_violations)

            # Auto-redact PII if configured and action allows
            if self.auto_redact_pii and action != GuardrailAction.BLOCK:
                redact_result = self._pii_redactor.redact(content)
                if redact_result.token_map:
                    filtered_content = redact_result.redacted_text

            # Determine if passed
            passed = action in (GuardrailAction.ALLOW, GuardrailAction.WARN)

            span.set_attribute("violations_count", len(all_violations))
            span.set_attribute("passed", passed)
            span.set_attribute("action", action.value)

            logger.info(
                "guardrails_completed",
                passed=passed,
                violations=len(all_violations),
                action=action.value,
            )

            return GuardrailResult(
                passed=passed,
                violations=all_violations,
                filtered_content=filtered_content if filtered_content != content else None,
                action_taken=action,
                metadata={
                    "guardrails_run": [g.name for g in self.guardrails],
                    "context": context,
                },
            )

    def _determine_action(self, violations: list[GuardrailViolation]) -> GuardrailAction:
        """Determine action based on violations."""
        if not violations:
            return GuardrailAction.ALLOW

        # Actions are prioritized: BLOCK highest, then REDACT, WARN, ALLOW
        actions = [v.suggested_action for v in violations]

        if GuardrailAction.BLOCK in actions:
            return GuardrailAction.BLOCK
        if GuardrailAction.REDACT in actions:
            return GuardrailAction.REDACT
        if GuardrailAction.WARN in actions:
            return GuardrailAction.WARN

        return GuardrailAction.ALLOW

    def add_guardrail(self, guardrail: Guardrail) -> None:
        """Add a guardrail to the pipeline."""
        self.guardrails.append(guardrail)

    def remove_guardrail(self, name: str) -> bool:
        """Remove a guardrail by name."""
        for i, g in enumerate(self.guardrails):
            if g.name == name:
                self.guardrails.pop(i)
                return True
        return False


# Convenience function for quick validation
def validate_output(
    content: str,
    context: dict[str, Any] | None = None,
    guardrails: list[Guardrail] | None = None,
) -> GuardrailResult:
    """
    Validate LLM output with guardrails.

    Args:
        content: LLM output to validate
        context: Optional context
        guardrails: Optional custom guardrails (uses defaults if None)

    Returns:
        GuardrailResult
    """
    pipeline = GuardrailPipeline(guardrails=guardrails)
    return pipeline.run(content, context)
