"""Helpers for the ADR-0042 acceptance tests (BQ-M2-4, BQ-M2-5, rules MV-01 to MV-17): the bot's two meter routes on
tilo-api, the attend claim and the hold TTL.

Package-unique name, like `_sec16_lib.py`. Nothing here is business logic: a fake Google verifier that knows only the
tokens a test registered, the real in-memory SEC-16 ledger behind a spy, a fake clock for the claim registry, and a
test-number `MeterConfig` (never the shipped caps). No network, no paid call, no secret: tokens, nonces and keys are
assembled at runtime.
"""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from typing import Any

import pytest
from _sec16_lib import FakeClock, SpyLedger, make_caps, make_ledger
from fastapi.testclient import TestClient
from tilo_metering.flags import InMemoryFlagStore

PROJECT = "demo-tilo"
AUDIENCE = "https://tilo-api-abc123-as.a.run.app"
BOT_SA = f"tilo-meet-bot@{PROJECT}.iam.gserviceaccount.com"
TICK_SA = f"tilo-schedule-scheduler@{PROJECT}.iam.gserviceaccount.com"
TASKS_SA = f"tilo-tasks-invoker@{PROJECT}.iam.gserviceaccount.com"
ISSUER = "https://accounts.google.com"
MEETING = "mt_demo0001"
OTHER_MEETING = "mt_demo0002"
OWNER, OWNER_2, ORG = "u_owner_a", "u_owner_b", "org_tilo"
RESERVE, CLOSE = "/internal/meeting-voice/reserve", "/internal/meeting-voice/close"
UNIT = 100  # `unit_reserve_minor` of these tests' caps: a test number
CEILING = 2048  # max(8 x 256, 4 x 400), the shipped config's ceiling


class FakeVerifier:
    """`verify(token, audience) -> claims`: knows only what a test registered; anything else raises, as google-auth
    does for a bad signature, expiry or audience."""

    def __init__(self) -> None:
        self._claims: dict[str, Mapping[str, Any]] = {}
        self.calls: list[tuple[str, str]] = []

    def register(self, email: str, *, aud: str = AUDIENCE, email_verified: Any = True) -> str:
        token = "tok-" + secrets.token_urlsafe(24)
        self._claims[token] = {"aud": aud, "iss": ISSUER, "email": email, "email_verified": email_verified}
        return token

    def verify(self, token: str, audience: str) -> Mapping[str, Any]:
        self.calls.append((token, audience))
        if token not in self._claims or self._claims[token]["aud"] != audience:
            raise ValueError("token not accepted")
        return self._claims[token]


def cost_usd(tokens_in: int, tokens_out: int) -> float:
    """A fake price: 0.30 USD per 1M input tokens and 1.20 per 1M output tokens (a test number, not a price list)."""
    return (tokens_in * 0.30 + tokens_out * 1.20) / 1e6


class Rig:
    """The real app with the meter seams installed: fake verifier, the in-memory ledger behind a spy, an in-memory flag
    store, a registry on a fake clock and a `MeterConfig` of test numbers."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, **caps: Any) -> None:
        from tilo_api import app, deps, meeting_voice_claims, meeting_voice_meter, schedules  # noqa: PLC0415

        self.app, self.deps, self.meter = app, deps, meeting_voice_meter
        self.caps = make_caps(**{"uid_lifetime_minor": 1_000, "run_minor": 1_000, **caps})
        self.ledger, self.flags = SpyLedger(make_ledger(self.caps)), InMemoryFlagStore()
        self.verifier, self.clock = FakeVerifier(), FakeClock(1_000.0)
        self.claims = meeting_voice_claims.AttendClaims(clock=self.clock)
        self.config = meeting_voice_meter.MeterConfig(
            caps=self.caps, ceiling=CEILING, hold_ttl_s=60.0, max_reserves=400, cost_usd=cost_usd
        )
        overrides = app.dependency_overrides
        overrides[schedules.get_oidc_verifier] = lambda: self.verifier
        overrides[deps.get_spend_cap_ledger] = lambda: self.ledger
        overrides[deps.get_flag_store] = lambda: self.flags
        overrides[meeting_voice_claims.get_attend_claims] = lambda: self.claims
        overrides[meeting_voice_meter.get_meter_config] = lambda: self.config
        monkeypatch.setenv("TILO_VOICE_METER", "1")
        monkeypatch.setenv("TILO_VOICE_METER_AUDIENCE", AUDIENCE)
        monkeypatch.setenv("TILO_VOICE_METER_CALLER", BOT_SA)
        monkeypatch.setenv("TILO_SCHEDULE_TICK_CALLER", TICK_SA)
        monkeypatch.setenv("TILO_TASKS_CALLER", TASKS_SA)
        for name in ("K_SERVICE", "CLOUD_RUN_JOB", "TILO_APPCHECK_ENFORCE"):
            monkeypatch.delenv(name, raising=False)
        self.client = TestClient(app)
        self.token = self.verifier.register(BOT_SA)

    # --- the claim the attend route would have made ------------------------------------------------------------

    def attend(self, meeting_id: str = MEETING, *, uid: str = OWNER, org: str = ORG) -> str:
        return self.claims.open(meeting_id, uid=uid, org_id=org)

    # --- the two routes ----------------------------------------------------------------------------------------

    def post(self, path: str, body: Any, *, token: str | None = "", raw: bytes | None = None) -> Any:
        headers = {} if token is None else {"Authorization": f"Bearer {self.token if token == '' else token}"}
        if raw is not None:
            return self.client.post(path, content=raw, headers={**headers, "Content-Type": "application/json"})
        return self.client.post(path, json=body, headers=headers)

    def reserve(self, nonce: str, key: str, *, meeting_id: str = MEETING, **kw: Any) -> Any:
        return self.post(RESERVE, {"meeting_id": meeting_id, "claim": nonce, "key": key}, **kw)

    def close(
        self, nonce: str, key: str, outcome: str = "settled", usage: Any = ..., *, meeting_id: str = MEETING, **kw: Any
    ) -> Any:
        body: dict[str, Any] = {"meeting_id": meeting_id, "claim": nonce, "key": key, "outcome": outcome}
        if outcome == "settled":
            body["usage"] = {"prompt_token_count": 100, "response_token_count": 100} if usage is ... else usage
        return self.post(CLOSE, body, **kw)

    def spent(self, uid: str = OWNER) -> int:
        return self.ledger.spent_minor(uid)

    def settled(self, uid: str = OWNER) -> int:
        return self.ledger.settled_minor(uid)


def new_key() -> str:
    return secrets.token_urlsafe(24)
