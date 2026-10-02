"""tilo_connectors.mock — a connector built from a registry declaration, with no network (FR-CON-01).

The mock exists so the first thin slice can run a gated send end to end without a real account.
It sends nothing anywhere: it records. Its one side-effect method is the outbox's `send_reply`
(inherited from the in-process fake: grant check, dedupe on (world, key)); it exposes no method
named after any declared action, so there is no direct send path (SEC-03). Like any connector, it
is declared in config; the shipped config never declares it, only tests do.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .fakes import FakeGmail


class MockConnector(FakeGmail):
    def __init__(self, declaration: Mapping[str, Any]) -> None:
        super().__init__()
        self._declaration = copy.deepcopy(dict(declaration))

    @property
    def id(self) -> str:
        return str(self._declaration["id"])
