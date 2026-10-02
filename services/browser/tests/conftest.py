"""Fixtures for services/browser acceptance tests (FR-CON-07, FR-CON-08). Test wiring only.

`make_rig` builds the unit under test the way the harness would: a fake engine over a fake web,
an `EgressPolicy`, a card sink, and a `BrowserWorker`. It imports `tilo_browser` lazily, so a
missing package fails each test with ModuleNotFoundError (the expected pre-implementation
failure) instead of failing collection of the whole directory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from _browser_lib import CARD_ID, HEADER, NOW, RUN, WORLD, FakeEngine, FakeWeb


@dataclass
class Rig:
    web: FakeWeb
    engine: FakeEngine
    policy: Any
    worker: Any
    cards: list[dict] = field(default_factory=list)

    @property
    def driver(self):
        """The (single) browser context the worker opened."""
        assert len(self.engine.contexts) == 1, f"expected one context, got {len(self.engine.contexts)}"
        return self.engine.contexts[0]


@pytest.fixture()
def make_rig():
    from tilo_browser.egress import EgressPolicy
    from tilo_browser.login import CardContext
    from tilo_browser.worker import BrowserWorker

    def _make(web: FakeWeb | None = None, *, allow=("example.com",), engine: FakeEngine | None = None, **policy_kw):
        web = web if web is not None else FakeWeb()
        engine = engine if engine is not None else FakeEngine(web)
        policy = EgressPolicy(allow=list(allow), **policy_kw)
        cards: list[dict] = []
        ctx = CardContext(
            world_id=WORLD,
            run_id=RUN,
            header=dict(HEADER),
            new_card_id=lambda: CARD_ID,
            now=lambda: NOW,
            timeout=3600,
        )
        worker = BrowserWorker(engine, policy, card_sink=cards.append, card_context=ctx)
        return Rig(web=web, engine=engine, policy=policy, worker=worker, cards=cards)

    return _make
