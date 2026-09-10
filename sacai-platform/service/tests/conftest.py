"""Shared environment setup for isolated SACAI service tests."""

import os


def pytest_configure() -> None:
    """Provide the required service token before application modules import."""

    os.environ.setdefault("SACAI_INTERNAL_TOKEN", "test-token-at-least-16-characters")

