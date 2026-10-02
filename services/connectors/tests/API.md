# `tilo_connectors` — public API these tests pin

Ticket ST-2. Package `services/connectors`, import name `tilo_connectors`, dist name
`tilo-connectors`. The outbox is the only path to a side effect (SEC-03, PRD 12.1); this file
is the contract the builder implements exactly — the tests in this directory import only what
is listed here. Nothing here is business logic, it is the shape tests hold the builder to
(mirrors `packages/policy/tests/API.md`'s own framing).

The package does not exist yet (`services/connectors/src/` is not created by this ticket), so
every test here fails today with `ModuleNotFoundError` (a subclass of `ImportError`) — that is
the expected failure until a builder ships P6.

## Errors

```python
class OutboxRefused(Exception):
    """Raised by Outbox.enqueue when `entry` fails contracts/outbox.schema.json validation,
    fails the OB-02 state/scheduled_at consistency check below (neither the schema nor
    tilo_policy.check_entry cover the correlation between undo_window_s, scheduled_at and
    state — see "OB-02, resolved" below), or tilo_policy.check_entry({**evidence, "entry":
    entry, "transfer": None, "rule": None}) returns a broken-rule string instead of None.
    Also raised by Outbox.cancel when the named entry is not currently in state "scheduled"
    (already sent, failed, queued with no undo window, cancelled already, or unknown id)."""


class MissingGrant(Exception):
    """Raised by a connector adapter's side-effect method (e.g. FakeGmail.send_reply) when
    `grant` is not a valid Grant minted by an Outbox instance's own dispatch_due() call for
    this exact send (SEC-03 runtime check). A caller outside tilo_connectors.outbox has no
    supported way to construct a valid Grant, so calling an adapter's side-effect method
    directly always raises this."""
```

## Store

```python
class InMemoryOutboxStore:
    """The package's ready-made store (a Firestore-backed one ships later, per the ticket).
    No public methods are part of this pinned surface: tests only construct it
    (`InMemoryOutboxStore()`) and hand it to Outbox; every assertion goes through Outbox's own
    methods, FakeGmail.sent and the emitted parts list, never through store internals."""

    def __init__(self) -> None: ...
```

## Outbox

```python
class Outbox:
    def __init__(
        self,
        store: InMemoryOutboxStore,
        connectors: dict[str, Any],  # connector id -> adapter instance, e.g. {"gmail": FakeGmail()}
        emit: Callable[[dict], None],  # receives one event part {"type", "authz", "data"} per call;
        # the outbox never stamps id/seq (PI-18, harness does that)
        clock: Callable[[], str],  # returns RFC 3339 now (common.schema.json#/$defs/timestamp);
        # tests drive it, e.g. with a small ManualClock test double
    ) -> None: ...

    def enqueue(self, entry: dict, evidence: dict) -> dict:
        """entry: an outbox.schema.json record (dict), already carrying id, idempotency_key,
        world_id, action_type, connector, recipients, attachments, item, destination, modifiers,
        risk_tier, authz, undo_window_s, scheduled_at, state, created_at (OB-02: state is
        "queued" when undo_window_s == 0 and scheduled_at == created_at, else "scheduled" with
        scheduled_at == created_at + undo_window_s seconds — Outbox itself checks this
        correlation at enqueue time and raises OutboxRefused when it does not hold, since
        neither outbox.schema.json nor tilo_policy.check_entry cover it; see "OB-02, resolved"
        below).

        evidence: a contracts/fixtures/outbox/crossref/{valid,invalid} case dict minus its
        "rule", "note", "entry" and "transfer" keys — i.e. reserved_by, authorised_by, policy,
        team_lead, world_owner, instruction, earlier_applied.

        1. Validates `entry` against contracts/outbox.schema.json (and its cross-file $refs);
           an invalid entry raises OutboxRefused (nothing unauthorised, and nothing malformed,
           is ever written — OB-01/OB-05 read together).
        2. Checks the OB-02 state/scheduled_at correlation above; a mismatch raises
           OutboxRefused.
        3. If `entry["world_id"]` + `entry["idempotency_key"]` already names a stored entry,
           returns that stored entry unchanged and writes nothing new (OB-03) — this is what
           makes retrying an enqueue call (a "retry storm" one level up, at the step that
           calls enqueue) safe.
        4. Otherwise calls
           `tilo_policy.check_entry({**evidence, "entry": entry, "transfer": None, "rule": None})`;
           a non-None return (the broken OB-01/OB-05 rule) raises OutboxRefused; None stores the
           entry unchanged and returns it.
        """

    def cancel(self, outbox_id: str) -> dict:
        """Moves the named entry from "scheduled" to "cancelled" (OB-02); a cancelled entry is
        never sent by dispatch_due(). Raises OutboxRefused for any other current state (no
        undo window to cancel, already sending/sent/failed/cancelled) or an unknown id — "only
        until sending starts" (ticket text) is read here as "only while state == scheduled"."""

    def dispatch_due(self) -> list[dict]:
        """Sends every entry currently due: state "queued", or state "scheduled" with
        scheduled_at <= clock(); each moves to "sending" then "sent" or "failed". No field but
        `state` ever changes (OB-05/PI-14). On "sent", emits exactly one event part
        `{"type": "data.transfer", "authz": entry["authz"], "data": {"connector":
        entry["connector"], "action_type": entry["action_type"], "direction": "out",
        "artifact": entry["item"], "outbox_id": entry["id"], "risk_tier": entry["risk_tier"]}}`
        (PI-16/PI-17); this "data" validates against
        contracts/events/data/data.transfer.schema.json. Nothing is emitted for an entry that
        ends "failed" or that stays "cancelled".

        Calls the adapter named by `entry["connector"]` from `connectors`, passing a Grant this
        call mints, so the adapter's exactly-once behaviour (OB-03, `entry["idempotency_key"]`)
        is what makes a crash between the adapter call and this method recording "sent", or
        many repeated/concurrent dispatch_due() calls (a retry storm), still produce exactly
        one underlying send per idempotency key: dispatch_due() may call an adapter's
        side-effect method again on retry, but the adapter itself runs a given
        idempotency_key's side effect at most once (see FakeGmail below) — this is FR-AGT-11 /
        FR-CHN-13's exactly-once guarantee.

        Returns the entries this call moved to "sent" or "failed", in whatever order; an entry
        not yet due is untouched and not included.
        """
```

## Fakes

```python
# tilo_connectors.fakes
class FakeGmail:
    """In-process, no network, no real Google API. Threads every reply into the given
    thread_id (destination) — a thread reply never becomes a new email (FR-CHN-13)."""

    def __init__(self) -> None: ...

    def send_reply(
        self,
        thread_id: str,
        item: dict | None,
        recipients: list[str],
        idempotency_key: str,
        grant,  # a tilo_connectors.outbox.Grant; anything else raises MissingGrant
    ) -> dict:
        """Records one send keyed by idempotency_key; a second call with an idempotency_key
        already recorded returns the first call's record unchanged and appends nothing new to
        `.sent` (OB-03: "the connector runs a key at most once") — this is what protects a
        crashed-then-retried dispatch_due() from sending the reply twice, even though
        dispatch_due() itself may call this method again on retry."""

    sent: list[dict]  # one dict per unique idempotency_key, insertion order, each
    # {"thread_id": ..., "item": ..., "recipients": [...], "idempotency_key": ...}
```

## Side-effect registry and static check

```python
# tilo_connectors.side_effects
SIDE_EFFECT_METHOD_NAMES: frozenset[str]  # method names callable only from the outbox
# (SEC-03); currently {"send_reply"} — the one
# adapter method this ticket ships. A builder adding
# a new adapter side-effect method adds its name
# here, the one declared place (ticket text).


@dataclass(frozen=True)
class Violation:
    path: Path  # resolved path of the offending file
    lineno: int  # 1-based line of the call
    method_name: str  # the SIDE_EFFECT_METHOD_NAMES member that was called


def scan_for_side_effect_calls(paths: Iterable[Path], *, allowed_path: Path) -> list[Violation]:
    """AST-parses each file in `paths` (skipping any that fail to parse — a syntax-broken repo
    file is not this scan's concern); for every `ast.Call` whose callee is a plain name or an
    attribute access ending in a name in SIDE_EFFECT_METHOD_NAMES (`send_reply(...)` or
    `x.send_reply(...)`), records a Violation unless that file, resolved, equals `allowed_path`
    resolved. This is the function under test; a caller decides which paths to pass (the real,
    whole-repo SEC-03 test below resolves `git ls-files` under services/ and packages/ itself
    and excludes test paths — see "SEC-03 static check, resolved" below — rather than this
    function knowing about tests/ or git).
    """
```

## OB-02, resolved (ambiguity)

`docs/security/p4-policy-invariants.md` PI-12 and `contracts/outbox.rules.md` OB-02 attribute
"scheduled_at equals created_at plus undo_window_s" and "queued has no undo window, scheduled
waits one out" to "the validator", without naming which validator. `outbox.schema.json` itself
has no cross-field check for it (confirmed by reading the schema: no `if`/`then` ties
`scheduled_at` to `undo_window_s`), and `tilo_policy.check_entry`'s documented job (API.md in
`packages/policy/tests/`) is OB-01/OB-05 authorisation, not this state/time arithmetic. Since
OB-02 is listed among this ticket's own requirement IDs, this ticket reads "the validator" as
`Outbox.enqueue` itself for the connectors half of the system (the harness's P0-09 validator
covers the same rule again on the write side; both checking it is not a conflict). Logged for
`docs/open-questions.md` by whichever builder ships this.

## SEC-03 static check, resolved (ambiguity)

The ticket text says the static scan covers "every tracked .py file under services/ and
packages/". Read literally that would also flag this test suite's own direct calls to
`FakeGmail.send_reply(..., grant=None)` (`test_SEC_03_*` below), which must call it directly,
outside the outbox, to prove `MissingGrant` — the one legitimate exception a real SEC-03 lint
would also need. This ticket's "real, whole-repo" static test therefore excludes paths under
any `tests/` directory and files named `test_*.py` before calling
`scan_for_side_effect_calls`; `scan_for_side_effect_calls` itself stays general (it has no
opinion about tests/ or git — see above), so a future non-test lint entry point can reuse it
unchanged. Logged for `docs/open-questions.md` by whichever builder ships this.

## Failures (review round 1)

An adapter that raises is ambiguous: the side effect may or may not have happened. The entry stays
due (it may sit in `sending`) and the next `dispatch_due()` retries it; the adapter's
(world_id, idempotency_key) dedupe keeps it to one send, and the one `data.transfer` is emitted
once the send is confirmed. Only a connector with no adapter lands the entry in `failed`, a final
state. `dispatch_due()` never stops a batch on one entry's error. A `data.transfer` whose `emit`
raised is retried by the next `dispatch_due()`, and exactly one is ever emitted per entry.

## Several instances, restarts (review round 2)

Many tilo-connectors instances share one store. Claiming an entry for sending is a compare-and-set
that also records a lease (holder and expiry); another instance may take over a `sending` entry
only after its lease expires, so an in-flight send is never claimed twice. A `data.transfer` not
yet emitted is kept in the store, not in one instance's memory, so any instance emits it later,
exactly once, in send order. An emit error never stops a batch. Two enqueues racing on one
(world_id, idempotency_key) store one entry. enqueue stores its own copy of the entry, so the
caller changing its dict afterwards changes nothing. A schedule out of range is `OutboxRefused`.

## One transfer per entry (review round 3)

Marking an entry `sent` and recording its pending `data.transfer` are one atomic store write, so a
crash between them cannot leave a sent entry without its transfer. Emitting is a single path: an
instance claims the oldest pending transfer in the store (compare-and-set with a lease) before it
calls `emit`, and removes it after; only one instance ever emits a given transfer, and transfers
are emitted in send order (a later one waits while an earlier one is pending).

## Delivery (review round 4)

The outbox delivers each `data.transfer` at least once; the event writer (the harness, PI-18)
keeps exactly one per `outbox_id` (PI-17), so the stream holds exactly one. An instance whose
emit returned always removes that pending transfer, even if its lease expired and another
instance holds it now. Send order is kept per `world_id`: a transfer the writer keeps rejecting
holds back only later transfers of its own world, never another world's.

---

# Token broker and consent (FR-CON-02, FR-CON-03, lane CL-REACH)

Two new modules, `tilo_connectors.tokens` and `tilo_connectors.consent`. The Outbox, adapters and
stores above are unchanged. Tests: `test_FR_CON_02_*.py` and `test_FR_CON_03_*.py`; helpers and the
Google, store and KMS doubles are in `_oauth_lib.py`. Nothing here reads the environment or the
network: settings, the HTTP client, the KMS, the store, the clock and `emit` are all injected. The
builder adds whatever crypto library it needs (an AES-GCM one) to `services/connectors/pyproject.toml`
and records its licence in `docs/licences.md`.

## `tilo_connectors.tokens`

```python
class TokenError(Exception): ...  # base of everything below


class KmsError(Exception): ...  # a Kms could not decrypt (wrong context, tampering)


class NotConnected(TokenError): ...  # no connection for this user and connector


class ConnectionExpired(TokenError): ...  # the provider rejected the refresh (invalid_grant)


class TokenRefreshFailed(TokenError): ...  # a refresh did not get through (5xx, network); retry later


class InsufficientScope(TokenError):
    missing: list[str]  # scope ids not granted; never a token


class Kms(Protocol):
    def encrypt(self, plaintext: bytes, *, aad: bytes) -> bytes: ...  # keyword-only aad = context
    def decrypt(self, ciphertext: bytes, *, aad: bytes) -> bytes: ...  # KmsError on a wrong aad or a changed ciphertext


class FakeKms:  # dev/CI: envelope of a key generated at runtime per instance; fresh nonce per call
    def __init__(self) -> None: ...


class CloudKms:  # thin Cloud KMS adapter, not exercised (no billing, ADR-0003); only encrypt/decrypt exist
    def __init__(self, key_name: str, client: Any = None) -> None: ...


@dataclass(frozen=True)
class OAuthSettings:
    client_id: str
    client_secret: str  # repr=False: never shown by repr or str
    redirect_base_url: str = "http://localhost:8080"
    redirect_uri: str  # property: base (trailing "/" ignored) + "/oauth/google/callback"

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> "OAuthSettings":
        ...
        # GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET from the mapping it is given; a missing
        # one raises ValueError naming the variable (never its value)


class TokenStore(Protocol):  # records are plain JSON (str/int/float/bool/None/list/dict), no bytes
    def put(self, user_id: str, connector: str, record: dict) -> None: ...
    def get(self, user_id: str, connector: str) -> dict | None: ...  # a copy
    def delete(self, user_id: str, connector: str) -> None: ...
    def connectors_of(self, user_id: str) -> list[str]: ...


class InMemoryTokenStore: ...  # the dev default, same protocol


class HttpClient(Protocol):  # injected; tests pass FakeGoogle
    def post(self, url: str, *, data: Mapping[str, str]) -> HttpResponse:
        ...
        # HttpResponse: .status_code: int and .json() -> dict are the only parts the code may use.
        # May raise (a network error). Endpoints are Google's: token https://oauth2.googleapis.com/token,
        # revoke https://oauth2.googleapis.com/revoke (form field `token`).


@dataclass(frozen=True)
class DisconnectResult:
    revoked_at_provider: bool
    provider_error: str | None  # a short reason, never a token or a provider body


class TokenBroker:
    def __init__(
        self,
        *,
        store: TokenStore,
        kms: Kms,
        http: HttpClient,
        settings: OAuthSettings,
        clock: Callable[[], str],
        emit: Callable[[dict], None],
        refresh_skew_s: int = 60,
    ) -> None: ...
    def store_tokens(self, user_id: str, connector: str, token_response: Mapping[str, Any]) -> None: ...
    def access_token_for_adapter(self, user_id: str, connector: str, *, required_scopes: Iterable[str]) -> str: ...
    def granted_scopes(self, user_id: str, connector: str) -> frozenset[str]: ...
    def connection_state(self, user_id: str, connector: str) -> str | None: ...  # "connected" | "expired" | None
    def disconnect(self, user_id: str, connector: str) -> DisconnectResult: ...
    def delete_user(self, user_id: str) -> None: ...
```

Behaviour the tests hold the builder to (PRD 12.1, 16.1):

- **Envelope encryption.** `store_tokens` takes a Google token endpoint response (`access_token`,
  optional `refresh_token`, `expires_in`, `scope`). Each stored record has its own random data key;
  the tokens are encrypted with that key and the data key is wrapped by `kms.encrypt(key, aad=...)`
  with the user and connector as context. The KMS only ever sees a data key (16, 24 or 32 bytes),
  never a token. A record copied into another user's slot, or changed, raises `TokenError` and never
  yields a token. The store holds ciphertext only, at every moment (the tests keep a history of every
  `put`); the plaintext is not in a log, an error, an event, a repr or any return value, whatever
  the provider's error body says. A response without `refresh_token` keeps the stored one.
- **Granted scopes** are `token_response["scope"].split()`. `granted_scopes` returns them; empty when
  there is no connection or it expired.
- **Hand-off.** `access_token_for_adapter` is the only call that returns a plaintext token. It
  requires `required_scopes` (omitting it is a `TypeError`), raises `InsufficientScope` (before any
  provider call) when one is not granted, `NotConnected`, or `ConnectionExpired`, and refreshes first
  when the token has `refresh_skew_s` seconds or less left. Only `tokens.py` and modules under
  `tilo_connectors/adapters/` may reference it, and no module outside `services/connectors` may import
  `tilo_connectors.tokens` (SEC-02; both checked by `test_FR_CON_02_secrecy.py`).
- **Refresh.** One POST to the token endpoint (`grant_type=refresh_token`, `refresh_token`,
  `client_id`, `client_secret`); one call however many threads ask at once (a lock per user and
  connector, re-checked after taking it). `invalid_grant` sets the state to `expired`, emits
  `connection.expired` once, and every later call raises `ConnectionExpired` with no provider call.
  A 5xx or a network error raises `TokenRefreshFailed`, keeps the state `connected`, emits nothing,
  and the next call tries again. A rotated `refresh_token` replaces the old one. `store_tokens` on an
  expired connection makes it `connected` again.
- **Disconnect** posts the refresh token (the access token when there is none) to the revoke endpoint,
  deletes the record whatever the provider answered (fail toward deletion), logs a `WARNING` naming the
  connector when the revoke failed, emits `connection.revoked`, and keeps no decrypted copy in memory.
  A second `disconnect` is a no-op (no call, no event). `delete_user` disconnects every connection of
  that user, one failing revoke never stopping the rest, and touches no other user.

Events are parts `{"type", "authz", "data", "user_id"}`: the same three keys the Outbox's parts have,
plus `user_id`, the owner of the connection, so the harness can pick the actor and the world. The
broker emits `connection.established` (after `store_tokens`; `authz` null), `connection.expired` and
`connection.revoked` (`authz` null; `data` is `{"connector"}`). Each validates against
`contracts/events/data/<type>.schema.json` and obeys EV-03 to EV-05.

## `tilo_connectors.consent`

```python
class ConsentRefused(Exception): ...  # anything the consent service will not do (see below)


@dataclass(frozen=True)
class ConsentResult:
    connector: str
    card_id: str
    granted_scopes: frozenset[str]  # from the token response


class ConsentService:
    def __init__(
        self,
        *,
        connectors: Mapping[str, Mapping],
        broker: TokenBroker,
        http: HttpClient,
        settings: OAuthSettings,
        clock: Callable[[], str],
        emit: Callable[[dict], None],
        state_ttl_s: int = 600,
    ) -> None:
        ...
        # connectors: connector id -> a connector.schema.json declaration (FR-CON-01's registry hands these over)

    def scopes_needed(self, *, user_id: str, connector: str, capabilities: Sequence[str]) -> list[str]: ...
    def build_consent_card(
        self,
        *,
        user_id: str,
        connector: str,
        capabilities: Sequence[str],
        card_id: str,
        world_id: str,
        run_id: str,
        building: str,
        agent: str,
        what_happened: str,
        why_it_matters: str,
        timeout: int = 3600,
    ) -> dict | None: ...
    def authorization_url(
        self, *, user_id: str, connector: str, capabilities: Sequence[str], card_id: str
    ) -> str | None: ...
    def handle_callback(
        self, *, user_id: str, state: str, code: str | None = None, error: str | None = None
    ) -> ConsentResult: ...
```

- **`scopes_needed`**: the declared `scopes` of the given capabilities, each once, in capability order
  then declaration order, minus `broker.granted_scopes(user_id, connector)`. A capability the connector
  does not declare, an unknown connector, or a connector whose `auth` is not `oauth2` raises
  `ConsentRefused`. No provider call, no event, no store write.
- **`build_consent_card`**: `None` when nothing is needed. Otherwise a `card.schema.json` consent card
  that passes CR-01 to CR-06 and CR-13: options `connect` ("Connect", suggested, with a reason) and
  `hold` ("Hold"), `safe_default` `hold`, no `delegate`, channels within web and mobile web,
  `created_at` from the clock, `consent.connector` and `consent.scopes` = one plain-language line per
  scope needed (never a URL). The line for a scope is the `description` of the declared action(s) of the
  requested capability(ies) that need it. The caller supplies ids, header and the two sentences (a model
  may write those; it writes no option). Building a card grants nothing; it may emit
  `connection.requested` `{connector, card_id}` (not pinned either way).
- **`authorization_url`**: `None` when nothing is needed. Otherwise
  `https://accounts.google.com/o/oauth2/v2/auth?...` with `client_id`, `redirect_uri`
  (`settings.redirect_uri`), `response_type=code`, `scope` = the needed scopes joined by a space,
  `access_type=offline`, `include_granted_scopes=true`, `code_challenge` (base64url SHA-256 of the
  verifier, unpadded) with `code_challenge_method=S256`, and `state`. The URL carries no client secret
  and no user id. The verifier (43 to 128 RFC 7636 characters, new per flow) never leaves the service
  except in the code exchange.
- **`state`**: unguessable (at least 128 bits, never repeats), bound to the user, the connector (and
  card id) and a nonce, valid for `state_ttl_s` seconds from the clock at `authorization_url`, usable
  once.
- **`handle_callback`**: refuses (`ConsentRefused`, before any provider call, with nothing stored and
  nothing emitted) a state that is unknown, forged, spent, expired or minted for another user; an
  `error` (denied consent, the state is spent); no `code`; and a code Google rejects (the exception
  never carries the code, verifier or secret). Otherwise it POSTs `grant_type=authorization_code`,
  `code`, `redirect_uri`, `client_id`, `client_secret`, `code_verifier` to the token endpoint, emits
  `connection.consented` (`authz` `{by: person, ref: user_id, at: clock()}`, `data.scopes` = the
  plain-language lines of the requested scopes that the response granted), then calls
  `broker.store_tokens` (which emits `connection.established`). `granted_scopes` are the response's
  `scope`, never the request's: a scope the person unticked is not recorded and is asked for again.
  Two callbacks racing on one state connect once.
