"""Shared pytest configuration for the ai-swe-engine test suite."""

import pytest


def pytest_configure(config):
    """Register custom markers so `-m live` and `-W error` behave predictably."""
    config.addinivalue_line(
        "markers",
        "live: tests that require the running API + Postgres stack "
        "(docker compose up)",
    )
