"""Shared pytest fixtures for services/channels acceptance tests (FR-CHN-02, FR-CHN-06).

No business logic lives here (root CLAUDE.md test-writer rule): every fixture returns a test
double from `_channels_lib.py`, which is kept under a package-unique module name because every
test directory has its own conftest.py and `from conftest import ...` would resolve to whichever
one pytest imported first. This directory has no __init__.py, so pytest's default "prepend" import
mode puts it on sys.path (the same pattern services/api/tests uses).
"""

from __future__ import annotations

import pytest
from _channels_lib import (
    FakeBindings,
    FakeClock,
    FakeControls,
    FakeSender,
    MemoryDedupeStore,
    Recorder,
    make_app_secret,
)


@pytest.fixture()
def app_secret() -> bytes:
    return make_app_secret()


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
def store(clock: FakeClock) -> MemoryDedupeStore:
    return MemoryDedupeStore(clock)


@pytest.fixture()
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture()
def bindings() -> FakeBindings:
    return FakeBindings()


@pytest.fixture()
def controls(clock: FakeClock) -> FakeControls:
    return FakeControls(clock)


@pytest.fixture()
def sender(clock: FakeClock) -> FakeSender:
    return FakeSender(clock)
