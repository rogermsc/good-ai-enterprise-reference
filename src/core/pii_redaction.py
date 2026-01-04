"""
PII Redaction and Tokenization.

This module provides pattern-based detection and tokenization of personally
identifiable information (PII) including:
- Brazilian CPF (Cadastro de Pessoas Físicas)
- Brazilian CNPJ (Cadastro Nacional da Pessoa Jurídica)
- Ecuadorian Cédula de Identidad
- Email addresses
- Phone numbers

Tokenization replaces PII with reversible tokens, enabling:
1. LLM processing without PII exposure
2. Response restoration with original values
3. Audit logging without storing raw PII
"""

import re
from dataclasses import dataclass, field
from typing import Pattern


@dataclass
class PIIPattern:
    """Definition of a PII pattern for detection."""

    name: str
    pattern: Pattern[str]
    token_prefix: str


# Pattern definitions
PII_PATTERNS: list[PIIPattern] = [
    # Brazilian CPF: XXX.XXX.XXX-XX or XXXXXXXXXXX
    PIIPattern(
        name="cpf",
        pattern=re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
        token_prefix="PII_CPF",
    ),
    # Brazilian CNPJ: XX.XXX.XXX/XXXX-XX or XXXXXXXXXXXXXX
    PIIPattern(
        name="cnpj",
        pattern=re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"),
        token_prefix="PII_CNPJ",
    ),
    # Ecuadorian Cédula: 10 digits
    PIIPattern(
        name="cedula",
        pattern=re.compile(r"\b\d{10}\b"),
        token_prefix="PII_CEDULA",
    ),
    # Email addresses
    PIIPattern(
        name="email",
        pattern=re.compile(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
        ),
        token_prefix="PII_EMAIL",
    ),
    # Phone numbers (various formats)
    PIIPattern(
        name="phone",
        pattern=re.compile(
            r"\b(?:\+\d{1,3}[-.\s]?)?\(?\d{2,3}\)?[-.\s]?\d{4,5}[-.\s]?\d{4}\b"
        ),
        token_prefix="PII_PHONE",
    ),
]


@dataclass
class RedactionResult:
    """Result of PII redaction operation."""

    redacted_text: str
    token_map: dict[str, str]
    patterns_found: dict[str, int] = field(default_factory=dict)


class PIIRedactor:
    """
    PII detection and tokenization service.

    Scans text for PII patterns and replaces them with tokens.
    Maintains a token map for later restoration.

    Example:
        redactor = PIIRedactor()
        result = redactor.redact("Contact: user@example.com, CPF: 123.456.789-00")
        # result.redacted_text = "Contact: [PII_EMAIL_1], CPF: [PII_CPF_2]"
        # result.token_map = {"[PII_EMAIL_1]": "user@example.com", "[PII_CPF_2]": "123.456.789-00"}

        restored = redactor.restore(result.redacted_text, result.token_map)
        # restored = "Contact: user@example.com, CPF: 123.456.789-00"
    """

    def __init__(self, patterns: list[PIIPattern] | None = None):
        """Initialize with optional custom patterns."""
        self.patterns = patterns or PII_PATTERNS

    def redact(self, text: str) -> RedactionResult:
        """
        Detect and tokenize PII in text.

        Args:
            text: Input text potentially containing PII

        Returns:
            RedactionResult with tokenized text and token map
        """
        token_map: dict[str, str] = {}
        patterns_found: dict[str, int] = {}
        token_counter = 0
        redacted_text = text

        for pii_pattern in self.patterns:
            matches = list(pii_pattern.pattern.finditer(redacted_text))

            if matches:
                patterns_found[pii_pattern.name] = len(matches)

            # Process matches in reverse order to preserve positions
            for match in reversed(matches):
                token_counter += 1
                original_value = match.group()
                token = f"[{pii_pattern.token_prefix}_{token_counter}]"

                token_map[token] = original_value
                redacted_text = (
                    redacted_text[: match.start()]
                    + token
                    + redacted_text[match.end():]
                )

        return RedactionResult(
            redacted_text=redacted_text,
            token_map=token_map,
            patterns_found=patterns_found,
        )

    def restore(self, text: str, token_map: dict[str, str]) -> str:
        """
        Restore original PII values from tokens.

        Args:
            text: Text containing PII tokens
            token_map: Mapping of tokens to original values

        Returns:
            Text with tokens replaced by original values
        """
        restored_text = text

        for token, original_value in token_map.items():
            restored_text = restored_text.replace(token, original_value)

        return restored_text

    def has_pii(self, text: str) -> bool:
        """Check if text contains any PII patterns."""
        for pii_pattern in self.patterns:
            if pii_pattern.pattern.search(text):
                return True
        return False

    def get_pii_summary(self, text: str) -> dict[str, int]:
        """Get count of each PII type found in text."""
        summary: dict[str, int] = {}

        for pii_pattern in self.patterns:
            matches = pii_pattern.pattern.findall(text)
            if matches:
                summary[pii_pattern.name] = len(matches)

        return summary


# Module-level convenience functions
_default_redactor = PIIRedactor()


def redact(text: str) -> tuple[str, dict[str, str]]:
    """
    Convenience function for PII redaction.

    Returns:
        Tuple of (redacted_text, token_map)
    """
    result = _default_redactor.redact(text)
    return result.redacted_text, result.token_map


def restore(text: str, token_map: dict[str, str]) -> str:
    """Convenience function for PII restoration."""
    return _default_redactor.restore(text, token_map)
