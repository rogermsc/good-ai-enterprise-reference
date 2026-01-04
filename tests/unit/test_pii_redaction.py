"""
Tests for PII Redaction.

Tests:
- CPF pattern detection and redaction
- CNPJ pattern detection and redaction
- Email pattern detection and redaction
- Phone pattern detection and redaction
- Token restoration
- Multiple PII in same text
"""


from src.core.pii_redaction import PIIRedactor, redact, restore


class TestPIIRedaction:
    """Test suite for PII redaction."""

    def setup_method(self):
        """Set up test fixtures."""
        self.redactor = PIIRedactor()

    # CPF Tests

    def test_cpf_with_formatting(self):
        """Should redact CPF with dots and dash."""
        text = "Customer CPF: 123.456.789-00"

        result = self.redactor.redact(text)

        assert "123.456.789-00" not in result.redacted_text
        assert "[PII_CPF_" in result.redacted_text
        assert "cpf" in result.patterns_found
        assert result.patterns_found["cpf"] == 1

    def test_cpf_without_formatting(self):
        """Should redact CPF without formatting."""
        text = "CPF: 12345678900"

        result = self.redactor.redact(text)

        assert "12345678900" not in result.redacted_text
        assert "[PII_CPF_" in result.redacted_text

    def test_cpf_restoration(self):
        """Should restore CPF from token."""
        original = "Customer CPF: 123.456.789-00"

        result = self.redactor.redact(original)
        restored = self.redactor.restore(result.redacted_text, result.token_map)

        assert restored == original

    # CNPJ Tests

    def test_cnpj_with_formatting(self):
        """Should redact CNPJ with formatting."""
        text = "Company CNPJ: 12.345.678/0001-00"

        result = self.redactor.redact(text)

        assert "12.345.678/0001-00" not in result.redacted_text
        assert "[PII_CNPJ_" in result.redacted_text
        assert "cnpj" in result.patterns_found

    def test_cnpj_without_formatting(self):
        """Should redact CNPJ without formatting."""
        text = "CNPJ: 12345678000100"

        result = self.redactor.redact(text)

        assert "12345678000100" not in result.redacted_text

    def test_cnpj_restoration(self):
        """Should restore CNPJ from token."""
        original = "CNPJ: 12.345.678/0001-00"

        result = self.redactor.redact(original)
        restored = self.redactor.restore(result.redacted_text, result.token_map)

        assert restored == original

    # Email Tests

    def test_email_simple(self):
        """Should redact simple email address."""
        text = "Contact: user@example.com"

        result = self.redactor.redact(text)

        assert "user@example.com" not in result.redacted_text
        assert "[PII_EMAIL_" in result.redacted_text
        assert "email" in result.patterns_found

    def test_email_complex(self):
        """Should redact complex email address."""
        text = "Email: john.doe+tag@sub.example.co.uk"

        result = self.redactor.redact(text)

        assert "john.doe+tag@sub.example.co.uk" not in result.redacted_text
        assert "[PII_EMAIL_" in result.redacted_text

    def test_email_restoration(self):
        """Should restore email from token."""
        original = "Contact: user@example.com"

        result = self.redactor.redact(original)
        restored = self.redactor.restore(result.redacted_text, result.token_map)

        assert restored == original

    # Phone Tests

    def test_phone_brazilian_format(self):
        """Should redact Brazilian phone number."""
        text = "Phone: (11) 98765-4321"

        result = self.redactor.redact(text)

        # Check phone was detected
        assert "phone" in result.patterns_found

    def test_phone_international_format(self):
        """Should redact international phone number."""
        text = "Call +55 11 98765-4321"

        result = self.redactor.redact(text)

        assert "phone" in result.patterns_found

    # Multiple PII Tests

    def test_multiple_pii_types(self):
        """Should redact multiple PII types in same text."""
        text = "Customer: user@example.com, CPF: 123.456.789-00, Phone: (11) 98765-4321"

        result = self.redactor.redact(text)

        assert "user@example.com" not in result.redacted_text
        assert "123.456.789-00" not in result.redacted_text
        assert "email" in result.patterns_found
        assert "cpf" in result.patterns_found

    def test_multiple_same_type(self):
        """Should redact multiple instances of same PII type."""
        text = "Emails: first@example.com and second@example.com"

        result = self.redactor.redact(text)

        assert "first@example.com" not in result.redacted_text
        assert "second@example.com" not in result.redacted_text
        assert result.patterns_found["email"] == 2
        assert len(result.token_map) == 2

    def test_multiple_restoration(self):
        """Should restore all PII from tokens."""
        original = "Email: user@example.com, CPF: 123.456.789-00"

        result = self.redactor.redact(original)
        restored = self.redactor.restore(result.redacted_text, result.token_map)

        assert restored == original

    # Edge Cases

    def test_no_pii(self):
        """Should handle text with no PII."""
        text = "This is a regular support message with no PII."

        result = self.redactor.redact(text)

        assert result.redacted_text == text
        assert len(result.token_map) == 0
        assert len(result.patterns_found) == 0

    def test_empty_text(self):
        """Should handle empty text."""
        text = ""

        result = self.redactor.redact(text)

        assert result.redacted_text == ""
        assert len(result.token_map) == 0

    def test_has_pii_true(self):
        """has_pii should return True when PII present."""
        text = "Email: user@example.com"

        assert self.redactor.has_pii(text) is True

    def test_has_pii_false(self):
        """has_pii should return False when no PII present."""
        text = "No PII here"

        assert self.redactor.has_pii(text) is False

    def test_get_pii_summary(self):
        """Should return summary of PII types found."""
        text = "Email: a@b.com, CPF: 123.456.789-00, another@email.com"

        summary = self.redactor.get_pii_summary(text)

        assert "email" in summary
        assert summary["email"] == 2
        assert "cpf" in summary
        assert summary["cpf"] == 1


class TestModuleFunctions:
    """Test module-level convenience functions."""

    def test_redact_function(self):
        """redact function should work correctly."""
        text = "Email: user@example.com"

        redacted_text, token_map = redact(text)

        assert "user@example.com" not in redacted_text
        assert len(token_map) == 1

    def test_restore_function(self):
        """restore function should work correctly."""
        original = "Email: user@example.com"
        redacted_text, token_map = redact(original)

        restored = restore(redacted_text, token_map)

        assert restored == original
