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
