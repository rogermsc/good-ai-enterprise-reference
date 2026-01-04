# Security Policy

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability in this project, please report it responsibly.

### How to Report

**Email:** security@wearegoodai.com

**Subject:** [SECURITY] Brief description of the issue

**Include:**
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### What to Expect

| Timeline | Action |
|----------|--------|
| 24 hours | Acknowledgment of report |
| 72 hours | Initial assessment |
| 7 days | Status update |
| 90 days | Target fix timeline |

We will work with you to understand and address the issue. We ask that you:
- Give us reasonable time to respond before public disclosure
- Make a good faith effort to avoid privacy violations and data destruction
- Do not access or modify data that does not belong to you

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.x.x | Yes |
| < 1.0 | No |

## Security Best Practices

When deploying this reference implementation, follow these security practices:

### Secrets Management

- **Never** commit secrets to version control
- Use environment variables or secrets managers
- Rotate API keys regularly
- Use separate keys for development and production

```bash
# Good: Environment variable
export OPENAI_API_KEY="sk-..."

# Bad: Hardcoded in code
api_key = "sk-..."  # NEVER DO THIS
```

### Authentication

The reference implementation uses header-based authentication for simplicity. In production:

- Implement OAuth 2.0 / OIDC
- Use JWT with proper validation
- Implement rate limiting
- Enable multi-factor authentication

### Network Security

- Deploy behind a WAF
- Use TLS 1.3 for all connections
- Restrict egress to known endpoints
- Implement network segmentation

### Database Security

- Use strong passwords
- Enable SSL connections
- Implement row-level security
- Regular backup and recovery testing
- Audit database access

### Container Security

- Use minimal base images
- Run as non-root user
- Scan images for vulnerabilities
- Keep base images updated
- Use read-only filesystems where possible

### LLM Security

- Treat all LLM outputs as untrusted
- Validate and sanitize LLM responses
- Implement output filtering
- Monitor for prompt injection attempts
- Use the Trust Layer for all LLM interactions

### Audit Logging

- Log all security-relevant events
- Protect log integrity
- Implement log retention policies
- Monitor logs for anomalies
- Ensure logs don't contain secrets

## Security Features

This implementation includes:

| Feature | Location | Description |
|---------|----------|-------------|
| PII Redaction | `src/core/pii_redaction.py` | Tokenizes sensitive data |
| Policy Engine | `src/core/policy_engine.py` | RBAC and approval gating |
| Audit Logging | `src/core/audit_log.py` | Immutable operation records |
| Trust Layer | `src/core/` | Gateway for all LLM calls |

## Known Limitations

This is a reference implementation with known limitations:

1. **Header-based auth**: Not suitable for production without additional security
2. **Token map storage**: Not encrypted in this implementation
3. **PII patterns**: May not cover all regional formats
4. **Rate limiting**: Not implemented in reference code

Address these limitations before production deployment.

## Dependency Security

We monitor dependencies for vulnerabilities:

```bash
# Run security audit
pip-audit

# Check for outdated packages
pip list --outdated
```

CI/CD includes automated security scanning.

## Incident Response

If you believe your deployment has been compromised:

1. **Contain**: Isolate affected systems
2. **Preserve**: Capture logs and evidence
3. **Analyze**: Determine scope and impact
4. **Remediate**: Patch vulnerabilities, rotate credentials
5. **Report**: Notify affected parties as required

## Security Updates

Security updates are released as patch versions. Subscribe to releases for notifications:

1. Watch this repository on GitHub
2. Enable security advisories
3. Monitor the CHANGELOG

## Acknowledgments

We thank the security researchers who help keep this project secure through responsible disclosure.
