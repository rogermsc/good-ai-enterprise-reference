# Contributing to Enterprise AI Platform Reference

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing.

## Code of Conduct

This project adheres to a [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## How to Contribute

### Reporting Issues

- **Security vulnerabilities**: See [SECURITY.md](SECURITY.md) for responsible disclosure
- **Bugs**: Open an issue with a clear description, steps to reproduce, and expected behavior
- **Feature requests**: Open an issue describing the use case and proposed solution

### Pull Requests

1. **Fork the repository** and create your branch from `main`
2. **Install dependencies**: `make setup`
3. **Make your changes** following the code style guidelines below
4. **Add tests** for any new functionality
5. **Run the test suite**: `make test`
6. **Run linting**: `make lint`
7. **Update documentation** if needed
8. **Submit a pull request**

### Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/good-ai-enterprise-reference.git
cd good-ai-enterprise-reference

# Install dependencies
make setup

# Copy environment file
cp .env.example .env

# Run tests
make test

# Run linting
make lint
```

## Code Style

### Python

- **Python 3.11+** with type hints
- **Pydantic v2** for data validation (use `ConfigDict`, not class-based `Config`)
- **Ruff** for linting and formatting
- Use `datetime.now(UTC)` instead of deprecated `datetime.utcnow()`
- Iterable unpacking preferred: `[*list, item]` over `list + [item]`

### Commits

- Use clear, descriptive commit messages
- Reference issues when applicable: `Fix #123: Description`
- Keep commits focused on a single change

### Testing

- Write tests for all new functionality
- Tests should be deterministic (no random values, no external API calls)
- Use `pytest` with `pytest-asyncio` for async tests
- Mock external dependencies (LLM providers, databases)

## Architecture Guidelines

### Trust Layer Principles

1. **LLM output is untrusted** - Always validate before use
2. **No direct tool execution** - Agents propose; policy engine approves
3. **PII never reaches LLM** - Tokenization before, restoration after
4. **Immutable audit trail** - Every decision is logged

### Adding New Features

When adding features that involve LLM interaction:

1. Ensure PII redaction is applied before LLM calls
2. Route through the Policy Engine for approval
3. Log all operations to the Audit Logger
4. Add appropriate tests

## Questions?

Open an issue or reach out to the maintainers.

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
