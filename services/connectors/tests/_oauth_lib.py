"""Test doubles and helpers for the token broker and consent tests (FR-CON-02, FR-CON-03).

Kept apart from conftest.py and _connectors_lib.py under a package-unique module name, for the
same reason _connectors_lib.py is. No production code lives here. What is here:

- FakeGoogle: an in-process stand-in for Google's token and revoke endpoints, behind the
  injected HTTP client seam (`post(url, *, data, ...)`). It records every call, checks the
  client id and secret, PKCE and the redirect URI on a code exchange, and can fail on demand.
  Its error bodies deliberately echo the secret they were sent, like a careless provider, so a
  broker that copies a provider body into a log, an error or an event is caught.
- RecordingTokenStore: a TokenStore (API.md) that keeps every record ever written, so a test
  can prove no plaintext token was at any time handed to a store.
- SpyKms: wraps FakeKms and records what is sent to the KMS, so a test can prove the data key
  (not the token) is what the KMS wraps.
- make_env(): the broker and consent service wired to those doubles.
- Declarations, event/card validation and a leak scanner.

Every token, secret and key is assembled at runtime from random bytes; no token-shaped literal
is ever written down (root CLAUDE.md, no secrets in fixtures).
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import logging
import pathlib
import secrets
import threading
import time
import types
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import jsonschema
import yaml
from _connectors_lib import ManualClock
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CONTRACTS = REPO_ROOT / "contracts"

# Google's documented endpoints. The broker and the consent service must use exactly these.
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DEV_REDIRECT_URI = "http://localhost:8080/oauth/google/callback"

START = "2026-10-02T09:00:00.000Z"
OWNER = "u_owner"
OTHER = "u_other"
WORLD = "w_village_basic"
RUN = "r_village_basic_1"
CARD_ID = "01JB5VQ0000000000000009005"
EXPIRES_IN = 3599

GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_COMPOSE = "https://www.googleapis.com/auth/gmail.compose"
GMAIL_SEND = "https://www.googleapis.com/auth/gmail.send"
DRIVE_READONLY = "https://www.googleapis.com/auth/drive.readonly"
DRIVE_METADATA = "https://www.googleapis.com/auth/drive.metadata.readonly"
DRIVE_FILE = "https://www.googleapis.com/auth/drive.file"


def fake_secret(label: str) -> str:
    """A unique random stand-in for a token or secret; never resembles a real provider's shape."""
    return f"{label}-{secrets.token_hex(16)}"


# ---------------------------------------------------------------------------
# Connector declarations (contracts/connector.schema.json). config/connectors.yaml is FR-CON-01's;
# these tests inject declarations, so they do not depend on it.


def gmail_decl() -> dict:
    return json.loads((CONTRACTS / "fixtures" / "connector" / "valid" / "gmail.json").read_text(encoding="utf-8"))


def web_search_decl() -> dict:
    return json.loads((CONTRACTS / "fixtures" / "connector" / "valid" / "web_search.json").read_text(encoding="utf-8"))


def drive_decl() -> dict:
    """Read, list and write each have their own scope, so a write-only ask is visible."""

    def action(action_id: str, capability: str, description: str, tier: str, gate: str) -> dict:
        return {
            "id": action_id,
            "capability": capability,
            "description": description,
            "risk_tier": tier,
            "gate_type": gate,
            "irreversible": False,
        }

    return {
        "id": "google_drive",
        "name": "Google Drive",
        "icon": "folder",
        "auth": "oauth2",
        "scopes": {"read": [DRIVE_READONLY], "list": [DRIVE_METADATA], "write": [DRIVE_FILE]},
        "capabilities": ["read", "list", "write"],
        "actions": [
            action("read_file", "read", "Read the files you pick in Drive.", "T1", "none"),
            action("list_files", "list", "See the names of the files in the folder you pick.", "T1", "none"),
            action("save_file", "write", "Save finished reports in a Tilo folder in your Drive.", "T2", "approval"),
        ],
        "limits": {"per_minute": 60, "batch_size": 50},
        "data_class": {"returns": ["personal", "business"], "redact": []},
    }


def declarations() -> dict[str, dict]:
    return {d["id"]: d for d in (gmail_decl(), drive_decl(), web_search_decl())}


def action_description(decl: dict, capability: str) -> str:
    return next(a["description"] for a in decl["actions"] if a["capability"] == capability)


# ---------------------------------------------------------------------------
# JSON Schema helpers


def _registry() -> Registry:
    resources = []
    for path in sorted(CONTRACTS.glob("**/*.schema.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        resources.append((data.get("$id") or path.resolve().as_uri(), Resource.from_contents(data, DRAFT202012)))
    return Registry().with_resources(resources)


_REGISTRY = _registry()


def _validator(schema: dict) -> Any:
    cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    return cls(schema, registry=_REGISTRY)


def schema_errors(schema_file: str, instance: Any) -> list[str]:
    schema = json.loads((CONTRACTS / schema_file).read_text(encoding="utf-8"))
    return [e.message for e in _validator(schema).iter_errors(instance)]


def authz_errors(authz: Any) -> list[str]:
    schema = {"$ref": "https://contracts.tilo.example/common.schema.json#/$defs/authz"}
    return [e.message for e in _validator(schema).iter_errors(authz)]


_EVENT_REGISTRY: dict[str, Any] = yaml.safe_load((CONTRACTS / "events" / "registry.yaml").read_text(encoding="utf-8"))


def _registry_entry(event_type: str) -> dict:
    events = _EVENT_REGISTRY["types"]
    assert event_type in events, f"{event_type} is not in contracts/events/registry.yaml"
    return events[event_type]


def validate_part(part: dict) -> None:
    """An emitted event part is a registered type, its data matches the type's schema, and its
    authz is present exactly when the registry says the type is a side effect (EV-02..EV-05)."""
    assert {"type", "authz", "data", "user_id"} <= set(part), f"event part is missing keys: {sorted(part)}"
    entry = _registry_entry(part["type"])
    assert schema_errors(f"events/data/{part['type']}.schema.json", part["data"]) == []
    if entry["side_effect"]:
        assert authz_errors(part["authz"]) == [], f"{part['type']} needs a valid authz"
        assert part["authz"]["by"] in entry["authz_by"]
    else:
        assert part["authz"] is None, f"{part['type']} is not a side effect, so authz is null"


def types_of(parts: list[dict]) -> list[str]:
    return [p["type"] for p in parts]


def check_consent_card_rules(card: dict) -> list[str]:
    """CR-01 to CR-06 and CR-13 of contracts/card.rules.md for a consent card, beyond the schema."""
    broken: list[str] = []
    options = card["options"]
    ids = [o["id"] for o in options]
    by_id = {o["id"]: o for o in options}
    if card["safe_default"] not in ids:
        broken.append("CR-01")
    if len(set(ids)) != len(ids):
        broken.append("CR-02")
    if card["safe_default"] in by_id and by_id[card["safe_default"]]["irreversible"]:
        broken.append("CR-03")
    if card["safe_default"] != "hold":
        broken.append("CR-04")
    suggested = [o for o in options if o["suggested"]]
    if not (2 <= len(options) <= 3) or len(suggested) != 1 or not suggested[0].get("reason"):
        broken.append("CR-05")
    if suggested and suggested[0]["irreversible"]:
        broken.append("CR-05")
    if "delegate" in card["actions"]:
        broken.append("CR-06")
    if sorted(ids) != ["connect", "hold"] or by_id.get("connect", {}).get("label") != "Connect":
        broken.append("CR-13")
    if by_id.get("hold", {}).get("label") != "Hold":
        broken.append("CR-13")
    return broken


# ---------------------------------------------------------------------------
# The Google double


@dataclass(frozen=True)
class Call:
    url: str
    data: dict[str, str]


class FakeResponse:
    """The slice of an HTTP response the broker may use: `status_code` and `json()`."""

    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict[str, Any]:
        return copy.deepcopy(self._body)

    @property
    def text(self) -> str:
        return json.dumps(self._body)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


def s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class FakeGoogle:
    """Google's token and revoke endpoints. `post` is the whole HTTP client surface."""

    def __init__(self, *, client_id: str, client_secret: str, latency_s: float = 0.0) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self.latency_s = latency_s
        self.refresh_mode = "ok"  # ok | invalid_grant | unavailable | network
        self.revoke_mode = "ok"  # ok | unavailable | network | rejected
        self.rotate_refresh_token = False
        self.calls: list[Call] = []
        self.live_refresh: dict[str, list[str]] = {}  # refresh token -> scopes it still carries
        self.issued_access: list[str] = []
        self.revoked: list[str] = []
        self._codes: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    # -- provisioning (test side) -------------------------------------------------------------
    def token_response(self, scopes: list[str], *, refresh: bool = True, expires_in: int = EXPIRES_IN) -> dict:
        """A token endpoint response for a grant of `scopes`, with the grant registered as live."""
        body: dict[str, Any] = {
            "access_token": fake_secret("at"),
            "expires_in": expires_in,
            "scope": " ".join(scopes),
            "token_type": "Bearer",
        }
        with self._lock:
            self.issued_access.append(body["access_token"])
            if refresh:
                body["refresh_token"] = fake_secret("rt")
                self.live_refresh[body["refresh_token"]] = list(scopes)
        return body

    def issue_code(
        self,
        scopes: list[str],
        *,
        challenge: str | None = None,
        redirect_uri: str | None = None,
        refresh: bool = True,
    ) -> str:
        """An authorisation code the user's consent produced, for `scopes` (what they granted). `refresh` False is
        Google's incremental answer without `prompt=consent`: no refresh token in the exchange."""
        code = fake_secret("code")
        with self._lock:
            self._codes[code] = {
                "scopes": list(scopes), "challenge": challenge, "redirect_uri": redirect_uri, "refresh": refresh,
            }  # fmt: skip
        return code

    # -- the HTTP client seam -----------------------------------------------------------------
    def post(self, url: str, *, data: Any, headers: Any = None, timeout: Any = None) -> FakeResponse:
        sent = {k: str(v) for k, v in dict(data).items()}
        with self._lock:
            self.calls.append(Call(url, sent))
        if self.latency_s:
            time.sleep(self.latency_s)  # outside the lock: concurrent callers really overlap
        if url == TOKEN_URL:
            return self._token(sent)
        if url == REVOKE_URL:
            return self._revoke(sent)
        raise AssertionError(f"the fake provider has no endpoint {url!r}")

    def _token(self, d: dict[str, str]) -> FakeResponse:
        if d.get("client_id") != self._client_id or d.get("client_secret") != self._client_secret:
            return FakeResponse(401, {"error": "invalid_client", "error_description": f"bad client {d}"})
        if d.get("grant_type") == "authorization_code":
            return self._exchange(d)
        if d.get("grant_type") != "refresh_token":
            return FakeResponse(400, {"error": "unsupported_grant_type"})
        if self.refresh_mode == "network":
            raise ConnectionError(f"connection reset while sending {d}")
        if self.refresh_mode == "unavailable":
            return FakeResponse(503, {"error": "backend_error", "error_description": f"retry later {d}"})
        with self._lock:
            scopes = self.live_refresh.get(d.get("refresh_token", ""))
        if self.refresh_mode == "invalid_grant" or scopes is None:
            description = f"Token has been expired or revoked: {d.get('refresh_token')}"
            return FakeResponse(400, {"error": "invalid_grant", "error_description": description})
        body: dict[str, Any] = {
            "access_token": fake_secret("at"),
            "expires_in": EXPIRES_IN,
            "scope": " ".join(scopes),
            "token_type": "Bearer",
        }
        with self._lock:
            self.issued_access.append(body["access_token"])
            if self.rotate_refresh_token:
                body["refresh_token"] = fake_secret("rt")
                self.live_refresh[body["refresh_token"]] = self.live_refresh.pop(d["refresh_token"])
        return FakeResponse(200, body)

    def _exchange(self, d: dict[str, str]) -> FakeResponse:
        with self._lock:
            grant = self._codes.pop(d.get("code", ""), None)  # a code works once
        reason = None
        if grant is None:
            reason = "unknown or used code"
        elif grant["redirect_uri"] is not None and d.get("redirect_uri") != grant["redirect_uri"]:
            reason = "redirect_uri mismatch"
        elif grant["challenge"] is not None and s256(d.get("code_verifier", "")) != grant["challenge"]:
            reason = "PKCE verification failed"
        if reason:
            return FakeResponse(400, {"error": "invalid_grant", "error_description": f"{reason}: {d.get('code')}"})
        return FakeResponse(200, self.token_response(grant["scopes"], refresh=grant.get("refresh", True)))

    def _revoke(self, d: dict[str, str]) -> FakeResponse:
        token = d.get("token", "")
        if self.revoke_mode == "network":
            raise ConnectionError(f"connection reset while revoking {token}")
        if self.revoke_mode == "unavailable":
            return FakeResponse(503, {"error": "backend_error", "error_description": f"retry later {token}"})
        if self.revoke_mode == "rejected":
            return FakeResponse(400, {"error": "invalid_request", "error_description": f"cannot revoke {token}"})
        with self._lock:
            self.revoked.append(token)
            self.live_refresh.pop(token, None)
        return FakeResponse(200, {})

    # -- inspection ---------------------------------------------------------------------------
    def calls_to(self, url: str) -> list[dict[str, str]]:
        return [c.data for c in self.calls if c.url == url]

    def refresh_calls(self) -> list[dict[str, str]]:
        return [d for d in self.calls_to(TOKEN_URL) if d.get("grant_type") == "refresh_token"]

    def exchange_calls(self) -> list[dict[str, str]]:
        return [d for d in self.calls_to(TOKEN_URL) if d.get("grant_type") == "authorization_code"]

    def revoke_calls(self) -> list[dict[str, str]]:
        return self.calls_to(REVOKE_URL)


# ---------------------------------------------------------------------------
# Store and KMS doubles


class RecordingTokenStore:
    """A TokenStore (API.md) that remembers every record ever put, as the JSON a real store holds."""

    def __init__(self) -> None:
        self._live: dict[tuple[str, str], str] = {}
        self.history: list[str] = []
        self._lock = threading.RLock()

    def put(self, user_id: str, connector: str, record: dict) -> None:
        blob = json.dumps(record, sort_keys=True)  # a record must be plain JSON, as a document store needs
        with self._lock:
            self._live[(user_id, connector)] = blob
            self.history.append(f"{user_id}/{connector}: {blob}")

    def get(self, user_id: str, connector: str) -> dict | None:
        with self._lock:
            blob = self._live.get((user_id, connector))
        return None if blob is None else json.loads(blob)

    def delete(self, user_id: str, connector: str) -> None:
        with self._lock:
            self._live.pop((user_id, connector), None)

    def connectors_of(self, user_id: str) -> list[str]:
        with self._lock:
            return sorted(c for (u, c) in self._live if u == user_id)

    def live_text(self) -> str:
        with self._lock:
            return "\n".join(f"{u}/{c}: {b}" for (u, c), b in sorted(self._live.items()))

    def ever_text(self) -> str:
        with self._lock:
            return "\n".join(self.history) + "\n" + self.live_text()

    def live_keys(self) -> list[tuple[str, str]]:
        with self._lock:
            return sorted(self._live)


class SpyKms:
    """Delegates to a real Kms and records what it was asked to wrap."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.encrypted: list[bytes] = []
        self.decrypt_calls = 0
        self._lock = threading.Lock()

    def encrypt(self, plaintext: bytes, *, aad: bytes = b"") -> bytes:
        with self._lock:
            self.encrypted.append(bytes(plaintext))
        return self.inner.encrypt(plaintext, aad=aad)

    def decrypt(self, ciphertext: bytes, *, aad: bytes = b"") -> bytes:
        with self._lock:
            self.decrypt_calls += 1
        return self.inner.decrypt(ciphertext, aad=aad)


# ---------------------------------------------------------------------------
# Leak scanning


def secret_forms(secret: str) -> list[str]:
    raw = secret.encode("utf-8")
    return [
        secret,
        base64.b64encode(raw).decode("ascii"),
        base64.b64encode(raw).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(raw).decode("ascii"),
        base64.urlsafe_b64encode(raw).decode("ascii").rstrip("="),
        raw.hex(),
    ]


def base64_forms_of_bytes(raw: bytes) -> list[str]:
    """Hex and base64 spellings of a binary key (its raw bytes cannot be searched in text)."""
    b64 = base64.b64encode(raw).decode("ascii")
    return [raw.hex(), b64, b64.rstrip("="), base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")]


def leaks(blob: str, secrets_: list[str]) -> list[str]:
    """The secrets that appear in `blob` in the clear, base64 or hex."""
    return [s for s in secrets_ if any(form in blob for form in secret_forms(s))]


def graph_contains(root: Any, needles: list[str], *, skip: tuple[Any, ...] = (), max_depth: int = 10) -> bool:
    """True when a str or bytes reachable from `root`'s attributes holds any needle (plain, base64
    or hex). Objects in `skip` (the injected doubles) are not entered."""
    seen = {id(o) for o in skip}
    forms = [f for n in needles for f in secret_forms(n)]

    def holds(text: str) -> bool:
        return any(f in text for f in forms)

    def walk(obj: Any, depth: int) -> bool:
        if id(obj) in seen or depth > max_depth:
            return False
        seen.add(id(obj))
        if isinstance(obj, str):
            return holds(obj)
        if isinstance(obj, (bytes, bytearray)):
            return holds(bytes(obj).decode("latin-1")) or holds(base64.b64encode(bytes(obj)).decode("ascii"))
        if isinstance(obj, dict):
            return any(walk(k, depth + 1) or walk(v, depth + 1) for k, v in list(obj.items()))
        if isinstance(obj, (list, tuple, set, frozenset)):
            return any(walk(v, depth + 1) for v in list(obj))
        if isinstance(obj, (type, types.ModuleType, types.FunctionType, types.MethodType, logging.Logger)):
            return False
        if callable(obj) and not hasattr(obj, "__dict__"):
            return False
        attrs = dict(getattr(obj, "__dict__", {}))
        for cls in type(obj).__mro__:
            for slot in getattr(cls, "__slots__", ()):
                if hasattr(obj, slot):
                    attrs[slot] = getattr(obj, slot)
        return any(walk(v, depth + 1) for v in attrs.values())

    return walk(root, 0)


# ---------------------------------------------------------------------------
# Wiring


@dataclass
class Env:
    clock: ManualClock
    emitted: list[dict]
    store: RecordingTokenStore
    kms: SpyKms
    google: FakeGoogle
    settings: Any
    broker: Any
    service: Any
    secrets: dict[str, str] = field(default_factory=dict)  # client secret etc., for leak scans

    def parts_of(self, event_type: str) -> list[dict]:
        return [p for p in self.emitted if p["type"] == event_type]

    def connect(self, user_id: str, connector: str, scopes: list[str], **kwargs: Any) -> dict:
        """Give the user a live grant directly (no consent flow): what a finished flow leaves behind."""
        response = self.google.token_response(scopes, **kwargs)
        self.broker.store_tokens(user_id, connector, response)
        return response


def make_env(*, state_ttl_s: int | None = None, latency_s: float = 0.0, base_url: str | None = None) -> Env:
    from tilo_connectors.consent import ConsentService
    from tilo_connectors.tokens import FakeKms, OAuthSettings, TokenBroker

    client_id = fake_secret("client") + ".apps.example"
    client_secret = fake_secret("cs")
    settings_kwargs: dict[str, Any] = {"client_id": client_id, "client_secret": client_secret}
    if base_url is not None:
        settings_kwargs["redirect_base_url"] = base_url
    settings = OAuthSettings(**settings_kwargs)
    clock = ManualClock(START)
    emitted: list[dict] = []
    store = RecordingTokenStore()
    kms = SpyKms(FakeKms())
    google = FakeGoogle(client_id=client_id, client_secret=client_secret, latency_s=latency_s)
    broker = TokenBroker(store=store, kms=kms, http=google, settings=settings, clock=clock, emit=emitted.append)
    service_kwargs: dict[str, Any] = {}
    if state_ttl_s is not None:
        service_kwargs["state_ttl_s"] = state_ttl_s
    service = ConsentService(
        connectors=declarations(),
        broker=broker,
        http=google,
        settings=settings,
        clock=clock,
        emit=emitted.append,
        **service_kwargs,
    )
    return Env(clock, emitted, store, kms, google, settings, broker, service, {"client_secret": client_secret})


# ---------------------------------------------------------------------------
# Consent flow helpers


@dataclass
class Flow:
    url: str
    base: str
    query: dict[str, str]

    @property
    def state(self) -> str:
        return self.query["state"]

    @property
    def scopes(self) -> list[str]:
        return self.query["scope"].split(" ")


def parse_auth_url(url: str) -> Flow:
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    assert all(len(v) == 1 for v in query.values()), f"a parameter appears twice in {url}"
    return Flow(url, f"{parts.scheme}://{parts.netloc}{parts.path}", {k: v[0] for k, v in query.items()})


def start_flow(env: Env, user_id: str, connector: str, capabilities: list[str], *, card_id: str = CARD_ID) -> Flow:
    url = env.service.authorization_url(
        user_id=user_id, connector=connector, capabilities=capabilities, card_id=card_id
    )
    assert url is not None
    return parse_auth_url(url)


def finish_flow(
    env: Env,
    flow: Flow,
    user_id: str,
    *,
    granted: list[str] | None = None,
    state: str | None = None,
) -> Any:
    """The user approves at Google (granting `granted`, by default everything asked), Google
    redirects back with a code, and Tilo handles the callback."""
    code = env.google.issue_code(
        flow.scopes if granted is None else granted,
        challenge=flow.query["code_challenge"],
        redirect_uri=flow.query["redirect_uri"],
    )
    return env.service.handle_callback(user_id=user_id, state=state or flow.state, code=code)
