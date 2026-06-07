"""Fixtures pour les tests unitaires API — sans dépendance HA."""

from __future__ import annotations

import asyncio
import sys

import pytest


@pytest.fixture(scope="session")
def event_loop_policy():
    """Sur Windows, forcer SelectorEventLoop pour les tests purs."""
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()
