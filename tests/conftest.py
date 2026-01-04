"""
Pytest configuration and fixtures.

This module provides common fixtures and configuration for all tests.
"""

import pytest

from src.core.security import SecurityContext, Roles


@pytest.fixture
def support_agent_context() -> SecurityContext:
    """Create a security context for a support agent."""
    return SecurityContext(
        user_id="test-agent-001",
        tenant_id="test-tenant",
        roles=(Roles.SUPPORT_AGENT,),
    )


@pytest.fixture
def support_lead_context() -> SecurityContext:
    """Create a security context for a support lead."""
    return SecurityContext(
        user_id="test-lead-001",
        tenant_id="test-tenant",
        roles=(Roles.SUPPORT_LEAD,),
    )


@pytest.fixture
def admin_context() -> SecurityContext:
    """Create a security context for an admin."""
    return SecurityContext(
        user_id="test-admin-001",
        tenant_id="test-tenant",
        roles=(Roles.ADMIN,),
    )


@pytest.fixture
def security_context() -> SecurityContext:
    """Create a security context for a security role."""
    return SecurityContext(
        user_id="test-security-001",
        tenant_id="test-tenant",
        roles=(Roles.SECURITY,),
    )


@pytest.fixture
def no_role_context() -> SecurityContext:
    """Create a security context with no roles."""
    return SecurityContext(
        user_id="test-norole-001",
        tenant_id="test-tenant",
        roles=(),
    )
