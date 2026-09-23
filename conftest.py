"""Shared pytest fixtures for SVC-C2-072.

Tests exercise the installed AgentCore framework rather than replacing its
security and lifecycle boundaries with local stubs.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def mock_secrets():
    """Bind deterministic schedule-source credentials for node tests."""
    from framework.secrets.context import bound_secrets
    from shared.secrets.inmemory_provider import InMemoryProvider

    provider = InMemoryProvider({"SCHEDULE_SOURCE_MOCK_API_KEY": "mock-schedule-key"})
    with bound_secrets(provider):
        yield provider
