"""The bot's half of the Live voice meter (ADR-0042, BQ-M2-4, MV-07, MV-10, MV-12, MV-16; FR-MTG-11, SEC-16).

`RemoteLiveVoiceMeter` is the `LiveVoiceMeter` hook (`reserve`, `settle(hold, usage)`, `release`) of the Gemini Live
voice, answered by tilo-api's two routes instead of a ledger: the bot holds no ledger credential and imports no ledger
code. It names only the meeting it was sent to attend, the claim nonce tilo-api put in the attend call's header and a
key of its own for each spoken reply (closed bodies, `contracts/meeting_voice_meter.schema.json`); whose spend it is is
tilo-api's to derive. It is deliberately dumb and fail-closed:

- Only a 200 answer that is valid against the contract's JSON Schema itself (not the generated models: they drop the
  if/then/else pairs, so `live` with a `reason` or `replay` with none would pass them) and says `live` returns a hold.
  Anything else (a non-200, a timeout, a redirect, a body that is off-contract or over 1 KiB, an unreachable API, no
  token) returns None, which the adapter turns into the local voice. The bot never speaks Live on its own word.
- A settle or a release that fails is retried once with the same key and then dropped, never raised into the voice;
  tilo-api's sweep settles the unit it never saw closed.
- Nothing here is logged but a class name or a fixed reason word. The claim, the token, a key and `usage` are never in a
  log line, an error text, `repr` or a file (MV-10, MV-16).

`meter_from_env` builds it only for `LIVE=1`, a valid `TILO_API_URL` and a claim; otherwise there is no meter and the
adapter stays unbuilt (the PR #945 gate: a Live adapter with no meter is Chirp)."""

from __future__ import annotations

import base64
import functools
import json
import logging
import re
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx
import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

log = logging.getLogger("bot.voice_meter")
CLAIM_HEADER = "X-Tilo-Meeting-Claim"
CLAIM_RE = re.compile(r"[A-Za-z0-9_-]{32,64}")  # `$defs.claim` of the contract (fullmatch: no trailing newline)
_API_URL = re.compile(r"https://[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::[0-9]{1,5})?")  # the service, no path
RESERVE, CLOSE = "/internal/meeting-voice/reserve", "/internal/meeting-voice/close"
TIMEOUT_S, MAX_ANSWER = 2.0, 1024
MAX_COUNT = 16384  # the contract's bound on one count of usage
_USAGE_FIELDS = ("prompt_token_count", "response_token_count", "total_token_count")
_CONTRACTS = "https://contracts.tilo.example/"
_SCHEMAS = ("meeting_voice_meter", "common")  # the contract and the file its meeting id points at
_IDENTITY_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity"
_REFRESH_MARGIN_S = 120
_NO_HOLD = frozenset({"refused", "no_token"})  # reasons after which tilo-api cannot have opened a hold


class _Failed(Exception):
    """One call did not give a usable 200 answer. Carries a fixed reason word, never a value."""


@functools.lru_cache(maxsize=1)
def _registry() -> Registry:
    """The contract files the bot's image carries (`<repo root>/contracts`; the Dockerfile copies the two)."""
    from .providers import repo_root  # noqa: PLC0415  (a late import keeps the attend route light to load)

    resources = []
    for name in _SCHEMAS:
        data = json.loads((Path(repo_root()) / "contracts" / f"{name}.schema.json").read_text(encoding="utf-8"))
        resources.append((data["$id"], Resource.from_contents(data, default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


@functools.lru_cache(maxsize=8)
def _validator(name: str) -> jsonschema.protocols.Validator:
    """One `$defs` entry of meeting_voice_meter.schema.json: reserve_request, reserve_answer, close_request, ..."""
    ref = {"$ref": f"{_CONTRACTS}meeting_voice_meter.schema.json#/$defs/{name}"}
    return jsonschema.Draft202012Validator(ref, registry=_registry())


def _check(name: str, body: Any) -> Any:
    """`body` if it is valid against the contract's schema, else `_Failed` (no error text kept: it names values)."""
    if not _validator(name).is_valid(body):
        raise _Failed("off_contract")
    return body


class _Hold:
    """The opaque hold of one reply. Its key is never in `repr` (and so never in a log line by accident)."""

    __slots__ = ("done", "key")

    def __init__(self, key: str) -> None:
        self.key, self.done = key, False

    def __repr__(self) -> str:
        return "_Hold()"


class IdentityToken:
    """The runtime account's Google-signed ID token for one audience, from the metadata server of the instance (the
    way tilo-api's own Cloud Run callers mint theirs; `format=full` carries the account's email). Cached in memory until
    shortly before its own expiry. Raises on any failure: the meter turns that into the local voice."""

    def __init__(self, *, transport: httpx.BaseTransport | None = None, clock: Callable[[], float] = time.time) -> None:
        self._transport, self._clock = transport, clock
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[str, float]] = {}

    def __repr__(self) -> str:
        return "IdentityToken()"

    def __call__(self, audience: str) -> str:
        with self._lock:
            cached = self._cache.get(audience)
            if cached and self._clock() < cached[1]:
                return cached[0]
            with httpx.Client(
                transport=self._transport, timeout=TIMEOUT_S, follow_redirects=False, trust_env=False
            ) as client:
                reply = client.get(
                    _IDENTITY_URL,
                    params={"audience": audience, "format": "full"},
                    headers={"Metadata-Flavor": "Google"},
                )
            token = reply.text.strip()
            if reply.status_code != 200 or not 20 < len(token) < 8192 or token.count(".") != 2:
                raise _Failed("no_token")
            self._cache[audience] = (token, self._expiry(token))
            return token

    def _expiry(self, token: str) -> float:
        """Local cache time only (the API verifies the token): the `exp` claim less a margin, else do not cache."""
        try:
            payload = token.split(".")[1]
            exp = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["exp"]
            return float(exp) - _REFRESH_MARGIN_S
        except (ValueError, KeyError, TypeError, IndexError):
            return 0.0


class RemoteLiveVoiceMeter:
    """`tilo_providers.voice.LiveVoiceMeter` over tilo-api's meeting voice routes. Thread-safe: the voice calls it from
    the thread that drives one reply, and a call holds no state but that reply's `_Hold`."""

    def __init__(
        self,
        base_url: str,
        meeting_id: str,
        claim: str,
        *,
        token_for: Callable[[str], str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if _API_URL.fullmatch(base_url) is None or CLAIM_RE.fullmatch(claim) is None:
            raise ValueError("RemoteLiveVoiceMeter: not a valid API url or claim")
        self._base, self._meeting, self._claim = base_url, meeting_id, claim
        self._token_for = token_for or IdentityToken()
        self._transport = transport
        self.last_free: threading.Thread | None = None  # the best-effort release of a lost reserve (tests join it)
        _check("reserve_request", self._body(secrets.token_urlsafe(24)))  # a bad meeting id (or no schema) is no meter

    def __repr__(self) -> str:
        return "RemoteLiveVoiceMeter()"

    # -- the LiveVoiceMeter hook ------------------------------------------------------------------------------------
    def reserve(self) -> object | None:
        key = secrets.token_urlsafe(24)  # fresh for every reply: a key is never reused (MV-05)
        try:
            request = _check("reserve_request", self._body(key))
            answer = _check("reserve_answer", self._post(RESERVE, request))
        except Exception as error:  # a refusal, an outage, a bad answer: all the local voice (MV-07)
            self._note("reserve", error)
            if not (isinstance(error, _Failed) and error.args[0] in _NO_HOLD):
                # the API may have opened a hold whose answer was lost: one best-effort release, off the voice's path
                self.last_free = threading.Thread(target=self._free, args=(key,), daemon=True)
                self.last_free.start()
            return None
        return _Hold(key) if answer["decision"] == "live" else None  # `replay` and its reason: the local voice

    def settle(self, hold: object, usage: Mapping[str, int]) -> None:
        if isinstance(hold, _Hold) and not hold.done:
            hold.done = True
            self._close(hold.key, "settled", self._counts(usage))

    def release(self, hold: object) -> None:
        if isinstance(hold, _Hold) and not hold.done:
            hold.done = True
            self._close(hold.key, "released", None)

    # -- internals --------------------------------------------------------------------------------------------------
    def _body(self, key: str) -> dict[str, Any]:
        return {"meeting_id": self._meeting, "claim": self._claim, "key": key}

    @staticmethod
    def _counts(usage: Mapping[str, Any]) -> dict[str, int]:
        """Only the contract's three counts. A count out of the contract's range is not sent as it is (a 422 and the
        sweep would book the same unit): empty usage books the whole unit at once (MV-09, MV-15)."""
        counts = {name: usage[name] for name in _USAGE_FIELDS if name in usage}
        if any(type(n) is not int or not 0 <= n <= MAX_COUNT for n in counts.values()):
            return {}
        return counts

    def _close(self, key: str, outcome: str, usage: dict[str, int] | None) -> None:
        body = self._body(key) | {"outcome": outcome} | ({} if usage is None else {"usage": usage})
        for _ in range(2):  # once more with the same key: a close is idempotent on tilo-api (MV-05)
            try:
                answer = _check("close_answer", self._post(CLOSE, _check("close_request", body)))
                if answer["outcome"] == outcome:
                    return
                raise _Failed("mismatch")
            except Exception as error:
                self._note("close", error)
        # dropped: tilo-api's sweep settles the unit at the whole unit (fail closed, a count that can only be too high)

    def _free(self, key: str) -> None:
        try:
            self._post(CLOSE, _check("close_request", self._body(key) | {"outcome": "released"}))
        except Exception as error:
            self._note("free", error)

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        """One bounded POST, no redirect, answer under 1 KiB; the parsed JSON of a 200, else `_Failed`."""
        token = self._token_for(self._base)
        with (
            httpx.Client(
                transport=self._transport, timeout=TIMEOUT_S, follow_redirects=False, trust_env=False
            ) as client,
            client.stream(
                "POST",
                self._base + path,
                content=json.dumps(body, separators=(",", ":")).encode(),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            ) as response,
        ):
            if response.status_code != 200:
                raise _Failed("refused")
            data, deadline = bytearray(), time.monotonic() + 2 * TIMEOUT_S
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > MAX_ANSWER:
                    raise _Failed("oversize")
                if time.monotonic() > deadline:  # a slow drip is bounded too
                    raise _Failed("timeout")
        try:
            return json.loads(bytes(data))
        except ValueError:
            raise _Failed("malformed") from None

    @staticmethod
    def _note(step: str, error: BaseException) -> None:
        # The class (and a fixed reason word) only: an exception's text can carry a url, a header or a body.
        reason = error.args[0] if isinstance(error, _Failed) and error.args else type(error).__name__
        log.warning("live voice meter %s: no live answer (%s)", step, reason)


def meter_from_env(
    meeting_id: str, claim: str | None, env: Mapping[str, str], **kwargs: Any
) -> RemoteLiveVoiceMeter | None:
    """The meter, or None (so the Live voice is never built and the local voice speaks): only under `LIVE=1`, with
    `TILO_API_URL` set to the service's `https://host`, the claim the attend call carried (ADR-0042 decision 11) and
    the contract's schema files readable. It never raises into the attend."""
    if env.get("LIVE") != "1" or not claim:
        return None
    try:
        return RemoteLiveVoiceMeter(env.get("TILO_API_URL", ""), meeting_id, claim, **kwargs)
    except Exception:  # a bad url, claim or meeting id, or a missing schema file: no meter, the local voice
        return None
