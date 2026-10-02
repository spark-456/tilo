"""Test helpers for FR-CHN-07 (signed single-use email links, PRD 10.3, 11.6, 16.2, 16.4 SEC-08).

Package-unique module name on purpose: services/channels/tests has no __init__.py (pytest's default
"prepend" import mode puts this directory on sys.path), and other test directories in the repo have
their own conftest.py, so `from conftest import ...` would resolve to whichever conftest was imported
first. Same reason services/api/tests uses `_api_lib.py`.

Nothing here is production logic. It holds fakes (clock, nonce store, card lookup, key material) and
contract-fixture loaders. The code under test is `tilo_channels.links`, imported lazily through
`links()` so that, before the package exists, every test fails with ModuleNotFoundError on its own
instead of the whole file failing at collection.

No real secrets: keys come from `secrets.token_bytes` at runtime; there is no key-shaped literal in
this repo.

API under test (defined by these tests, see test_FR_CHN_07_signed_links.py module docstring):

    LinkRefused(Exception)            .reason: str
    KeyRing(keys, active)             .active_kid, .add(kid, key, activate=False), .retire(kid)
    CardState(card, answered)
    LinkService(keys=, nonces=, clock=, cards=, base_url=)
        .issue(card_id=, user_id=, action=, option=None) -> IssuedLink
        .redeem(token, card_id=, action=, viewer=None, option=None) -> Redemption
"""

from __future__ import annotations

import copy
import importlib
import json
import pathlib
import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CARD_FIXTURES = REPO_ROOT / "contracts" / "fixtures" / "card" / "valid"

BASE_URL = "https://app.tilo.test"
T0 = datetime(2026, 10, 2, 9, 0, 0, tzinfo=UTC)
TTL = timedelta(hours=24)  # PRD 10.3 "valid 24 h", PRD 16.2, services/channels/CLAUDE.md

ALICE = "u_alice"
BOB = "u_bob"

# Card ids. Contract fixtures reuse ids across kinds (and use unregistered ones in places), so each
# fixture is loaded and given its own ULID here; everything else on the card is the contract fixture.
Q1 = "01J8Z3K4M5N6P7Q8R9S0T1V2W4"  # needs_you, options per_kwh / per_pack, answerable by email
Q2 = "01J8Z3K4M5N6P7Q8R9S0T1V2W6"  # a second needs_you card
GATE = "01J8Z3K4M5N6P7Q8R9S0T1V2W3"  # gate, T3, irreversible send_email, options approve / edit / hold
GATE_REV = "01J8Z3K4M5N6P7Q8R9S0T1V2W7"  # gate, reversible save, options approve / hold
CONSENT = "01J8Z3K4M5N6P7Q8R9S0T1V2W5"  # consent, options connect / hold
MEETING = "01J8Z3K4M5N6P7Q8R9S0T1V2W8"  # meeting, options research / even

ANSWERABLE_BY_EMAIL = (Q1, Q2)
NOT_ANSWERABLE_BY_EMAIL = (GATE, GATE_REV, CONSENT, MEETING)


def links() -> Any:
    """The module under test, imported at call time."""
    return importlib.import_module("tilo_channels.links")


def fresh_key() -> bytes:
    return secrets.token_bytes(32)


def _load(name: str, card_id: str) -> dict[str, Any]:
    card = json.loads((CARD_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    card["id"] = card_id
    return card


def make_cards() -> dict[str, dict[str, Any]]:
    return {
        Q1: _load("needs_you_compare_basis", Q1),
        Q2: _load("needs_you_compare_basis", Q2),
        GATE: _load("gate_send_reply", GATE),
        GATE_REV: _load("gate_save_file_reversible", GATE_REV),
        CONSENT: _load("consent_drive_folder", CONSENT),
        MEETING: _load("meeting_budget_split", MEETING),
    }


class FakeClock:
    """Injected clock: a zero-argument callable returning an aware UTC datetime."""

    def __init__(self, start: datetime = T0) -> None:
        self.t = start

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw: float) -> None:
        self.t = self.t + timedelta(**kw)


class FakeNonceStore:
    """The injected nonce store: ONE atomic operation, `consume(nonce, expires_at) -> bool`, True only
    for the first consumption of a nonce. It has no separate 'seen' or 'add', so a service cannot
    implement single-use as check-then-set against it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.consumed: dict[str, datetime] = {}
        self.calls: list[tuple[str, datetime]] = []

    def consume(self, nonce: str, expires_at: datetime) -> bool:
        with self._lock:
            self.calls.append((nonce, expires_at))
            if nonce in self.consumed:
                return False
            self.consumed[nonce] = expires_at
            return True


class CardBook:
    """The injected card lookup: `book(card_id) -> CardState | None`. `answered` models a card already
    answered on any channel, or closed by its timeout (safe default applied)."""

    def __init__(self, cards: dict[str, dict[str, Any]]) -> None:
        self.cards = cards
        self.answered: set[str] = set()

    def __call__(self, card_id: str) -> Any:
        card = self.cards.get(card_id)
        if card is None:
            return None
        return links().CardState(card=copy.deepcopy(card), answered=card_id in self.answered)


@dataclass
class Rig:
    ring: Any
    clock: FakeClock
    store: FakeNonceStore
    book: CardBook
    service: Any
    kid: str = "k1"
    key: bytes = field(default_factory=fresh_key)

    def new_service(self, nonces: Any = None, keys: Any = None) -> Any:
        """Another service instance over the same ring, clock and cards (another Cloud Run instance),
        with the same or a different nonce store."""
        return links().LinkService(
            keys=keys if keys is not None else self.ring,
            nonces=nonces if nonces is not None else self.store,
            clock=self.clock,
            cards=self.book,
            base_url=BASE_URL,
        )

    def issue(
        self,
        card_id: str = Q1,
        user_id: str = ALICE,
        action: str = "answer",
        option: str | None = "per_kwh",
        service: Any = None,
    ) -> Any:
        return (service or self.service).issue(card_id=card_id, user_id=user_id, action=action, option=option)

    def redeem(self, link: Any, service: Any = None, token: str | None = None, **over: Any) -> Any:
        """Redeem `link` with the facts it was issued for, unless overridden. `option` is only passed
        when overridden (the token carries the option; the request normally does not repeat it)."""
        facts: dict[str, Any] = {"card_id": link.card_id, "action": link.action}
        facts.update(over)
        return (service or self.service).redeem(token if token is not None else link.token, **facts)


def make_rig(kid: str = "k1") -> Rig:
    L = links()
    key = fresh_key()
    ring = L.KeyRing(keys={kid: key}, active=kid)
    clock = FakeClock()
    store = FakeNonceStore()
    book = CardBook(make_cards())
    service = L.LinkService(keys=ring, nonces=store, clock=clock, cards=book, base_url=BASE_URL)
    return Rig(ring=ring, clock=clock, store=store, book=book, service=service, kid=kid, key=key)
