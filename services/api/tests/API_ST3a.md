# `tilo_api` — public shape ticket ST-3a pins (round 4, post code/security/qa review)

Ticket ST-3a (session ST). Requirements FR-HIL-07 (kill switches), FR-HIL-09 and SEC-07 (roles
and redaction). Invariants PI-13 and PI-18 of `docs/security/p4-policy-invariants.md` apply. This
file is the contract the builder implements exactly; the tests in this directory import only what
is listed here. Nothing here is business logic — it is the shape tests hold the builder to, the
same convention `packages/policy/tests/API.md` uses for P4-01. `tilo_policy` (package
`packages/policy`, built in parallel by ticket P4-01) is used read-only for one integration test
below; it is not a workspace member yet, so importing it fails until P4-01 lands — that failure
is expected and correct for this ticket.

Real sign-in, Firestore, and the harness's own internals are out of scope: this ticket adds route
handlers over an **injected, in-memory store** (no Firestore, no network, PRD 15.3's document
layout is the shape to keep in mind for a later ticket, not implemented here), an **injected
principal** (no real auth; "Auth is a test double" per the ticket brief) and an **injected event
writer** standing in for the harness (PRD 15.3: "The harness is the only writer of events and
writes each redacted view itself" — new in this round; round 1's builder had `tilo-api` stamp and
append events itself, which review round 1 rejected).

## What changed since round 1 (why every section below moved)

1. **One writer (PI-18).** Round 1 had `tilo-api` invent `run_id = "r_<world_id>"` and compute
   `seq` by rescanning `store.events[world_id]` on every event (also O(n²) over a Stop-all of n
   policies). `tilo-api` now never stamps `id`, `seq`, `ts` or `run_id`: it builds an event *part*
   and hands it to an injected `deps.EventWriter`.
2. **World membership.** Round 1 told an owner of a *different* world "403 Forbidden" for a world
   they do not own — telling them the world exists. `Principal` now carries the one `world_id` the
   sign-in layer resolved for it; a mismatch is treated exactly like an unknown world (404, same
   body), on every world route. Revoking a policy that exists but is not yours now also returns
   404, identical to revoking an unknown policy id (no oracle).
3. **Half-apply.** Round 1's Stop-all loop mutated `store.policies` and appended events as it
   iterated a plain `dict.items()`; a policy with no entry in `policy_worlds` raised `KeyError`
   partway through, a 500 with some policies already flipped to L1 and others not. Stop-all, Pause
   all and revoke now validate every policy's plan first (working from `.get()` reads and safe
   fallbacks, never a bare index into `policy_worlds` or `history`) and only then apply it, so a
   request never raises and never leaves policies split between old and new level.
4. **Pause channel.** Round 1's `PauseRequest.channel: str | None` accepted any string. It is now
   typed to the schema's own enum, so an out-of-enum value is a 422 before the handler runs.
5. **Redacted views.** Round 1 returned the store's own `seq` in a scoped response (letting a
   viewer count the gaps where hidden events were dropped) and passed `cause` through unchanged
   (letting a viewer read the id of an event it can never fetch). A scoped response now carries
   its own dense `seq` (PRD 15.3 `views/{scope}/events/{seq}` is a separate sequence per view) and
   nulls a `cause` that names a hidden event. A malformed or missing district record is treated as
   hidden, never raises.
6. **`policy.changed` visibility.** Round 1 always emitted `policy.changed` with `vis: "all"`. A
   policy whose `scope.districts` is non-empty now gets `vis` equal to those districts (EV-13), so
   Stop-all does not announce a district-scoped policy's change to a viewer who cannot see that
   district.

## What changed since round 2 (why the sections below moved again)

Round 2's own fixes above are unchanged and still pinned. Round 2 itself then failed code,
security and qa review on:

1. **Silent history repair (code, biggest).** Round 2's Stop-all skipped *every* policy read as
   `level == "L1"` as an idempotent repeat (`already_l1`, no history entry, no event) — including
   one whose own `history` disagreed (ended at another level, or was empty). That is not a repeat
   Stop-all, it is an inconsistent record, and skipping it silently "repairs" the read without ever
   writing an audit trail for the repair. Stop-all now only skips a policy at L1 whose own
   `history[-1]["level"] == "L1"` too; anything else at L1 goes through the exact same normal path
   as any other policy (`policy["history"]` and `policy["changed_by"]` are plain dict fields tilo-api
   itself owns; there is no separate "repair" write — it is the one the kill switch is defined to
   make anyway).
2. **The writer being down must not stop the kill switch (qa/security, biggest).** Round 2 let a
   raising `EventWriter.append` propagate out of the route (or otherwise block on it), so a Stop-all
   or Pause-all against an unreachable harness never actually lowered autonomy — the opposite of
   what a kill switch is for (PRD 10.4 "sets every policy to L1 instantly"). The level change,
   `changed_by` and history entry are now applied to `store.policies` regardless of whether the
   writer accepts the part; a part that fails to write is kept in `Store.pending_events` (new field,
   below) instead of lost, and is retried — exactly once each — the next time a mutating route
   touches that world. See "Pending writes and flush" under the routes below.
3. **Concurrency (qa).** Round 2 never proved that two concurrent Stop-alls (or Pause-alls) against
   a slow writer leave exactly one `policy.changed`/`world.paused` and one `stop_all` history entry
   per policy. `test_FR_HIL_07_concurrent_stop_alls_produce_exactly_one_change_per_policy` and its
   Pause-all counterpart now pin this directly with real threads and a slow writer double.
4. **Redacted views leak nothing (security, biggest).** Round 2's redaction filtered events by
   `vis` but otherwise passed a kept event through unchanged except for `seq` and a dangling
   `cause`. That is copying-then-patching, not allowlisting, and it still leaked: the event's own
   real `id` (whose ULID ordering hints at how much else happened in the run), `trace.archive_ref`
   and any `data` field like `message_ref` (both name a position in the run-wide raw archive, a
   counter unrelated to district visibility), any other ULID-shaped `data` value naming another
   event (for example `policy.applied.data.instruction_id`), and an event's own `district` field
   when it names a hidden district even though the event itself is `vis: "all"`. Both GET routes
   now build the scoped response by allowlisting: only the fields API_ST3a.md names below are
   copied forward, everything else is re-keyed, nulled or dropped. See "Redaction rules" under
   `GET /worlds/{world_id}/events` below.
5. **EV-13 vis intersection (security).** Round 2 set a scoped `policy.changed`'s `vis` to the
   policy's own `scope.districts` unchanged. A policy's scope can name a district that is not part
   of the world Stop-all was run against at all (policies live at org level, PRD 15.3, with no
   `world_id` of their own); `event.rules.md` EV-13 requires "every district `vis` lists exists in
   the world's layout." `vis` is now the *intersection* of `scope.districts` with
   `store.worlds[world_id].districts`' own keys; an empty intersection (or an empty
   `scope.districts` to start with) falls back to `"all"`, same as round 2.

## What changed since round 3 (why the sections above moved again)

Round 3's own fixes above are unchanged and still pinned. Round 3 itself then failed code,
security and qa review on:

1. **Pause's dedupe was keyed on the wrong thing (security, biggest).** Round 3's Pause route
   built a `world.paused` part only when this call's own Stop-all step actually lowered a policy
   (`stopped > 0`) — meant as an idempotency guard for two concurrent or repeated Pause-alls, but
   it silently dropped the event for two *legitimate, first-time* pauses instead: a Pause-all
   pressed right after a Stop-all (every owned policy already `L1`, so `stopped == 0` even though
   the world itself was never paused before) and a Pause-all on a world with no `L2`/`L3` policies
   to begin with (`stopped == 0` on its very first call). `WorldRecord` now carries its own
   `paused: bool` flag (new field, above); Pause-all's dedupe reads and sets *that* flag, under the
   same lock that serializes the route's own mutation, and never infers "already paused" from
   whether any policy changed this call. A world reaches "paused" the moment the flag flips
   `False -> True`; every subsequent Pause-all before it is ever un-paused (no route this ticket
   adds clears it) is the one case that still correctly builds no second `world.paused`.
2. **A slow, failing writer for one world could stall a kill switch against a different world (qa,
   biggest).** Round 3's single process-wide lock serialized Stop-all/Pause-all's *entire*
   mutating section, including every writer call it made while holding that lock — so a Stop-all
   against a world with 200 policies and a writer that sleeps before raising held the lock for the
   full `200 * delay` duration, and a concurrently-issued Stop-all against an entirely different,
   healthy world blocked behind it the whole time. A kill switch's own 5 s budget (PI-13/FR-HIL-07)
   was never about the audit trail landing instantly — only about autonomy actually lowering — so
   the level-change section (fast, no I/O) and the writer-call section (potentially slow) are now
   separated: every targeted policy reaches `L1` in `store.policies` before any writer call for it
   is attempted, and whatever serializes concurrent mutation against the *same* world does not
   extend across writer I/O for *any* world, so one world's writer latency is never another
   world's problem. See "Locking" under the stop route above.
3. **`policy.changed`'s `vis` used the wrong world's layout (code, biggest).** Round 3 fixed EV-13
   for a policy mapped to the *same* world Stop-all was pressed in, but for a policy mapped (via
   `policy_worlds`) to a *different* world B, it still intersected `scope.districts` against the
   *request* world A's own layout — so a policy scoped to a district that exists only in B, when
   stopped from A, got `vis: "all"` (A's layout has nothing to intersect against) instead of the
   correct district list computed against B, where the event is actually filed. `vis` is now
   always computed against the *target* world's own districts — the same world
   `store.policy_worlds.get(policy_id, world_id)` names — never the request world's, unless they
   happen to be the same world.
4. **Redacted views still leaked a caller's own visibility scope, and hid too little (security).**
   Round 3's allowlist copied `vis`, `target` and `actor` through unchanged, and only walked the
   top level of `data`: (a) a kept event's full `vis` district list could name a district beyond
   the caller's own scope even though the event itself was visible via a *partial* intersection —
   telling a scoped caller "this is also shown to someone else, and here is exactly which other
   district," a leak through a field previously assumed safe because "it is never itself
   sensitive"; (b) `target`/`actor` can themselves be a district id per `event.schema.json`'s own
   `target` `anyOf`, and neither was ever checked against the caller's visible districts, unlike
   the dedicated `district` field; (c) a ULID or district id nested *inside* `data` — inside a
   sub-object or a list item, not just a top-level `data` key — passed through unfiltered, and
   `data.district` specifically was never redacted at all (it is not ULID-shaped, so round 3's
   top-level ULID-only pass never touched it). All four are now allowlisted per the updated table
   above: `vis` is filtered to its intersection with `principal.districts`; `target`/`actor` are
   nulled when district-shaped and hidden; `data` is walked recursively, at any depth, applying the
   `message_ref`/ULID/district-id rules to every string leaf, `data.district` included.
5. **`pending` only ever counted the request's own world (security).** A Stop-all or Pause-all
   against world A that routes a part to a mapped world B, and whose writer then fails for that
   part, left it correctly in `store.pending_events[B]` — but the response's `"pending"` summed
   only `store.pending_events.get(world_id, [])` (`world_id` being A), so the caller's own response
   never reported it, and a later call only ever flushed `world_id`'s own queue, never touching B's
   at all — a world's stuck pending parts could survive indefinitely with no mutating call against
   *that* world ever being made, since nothing routes a request to B on B's own path in this
   scenario. "Which worlds a call touches" (above) is the resolved rule: `pending` sums every
   touched world's queue, and flush attempts every touched world's queue, not only the request's
   own `world_id`.
6. **Revoke had no writer-failure handling at all (qa/security follow-up).** Round 3 explicitly put
   revoke's own writer handling out of scope ("revoke does not participate in flushing this
   round"); the round-3 implementation called `writer.append` directly, unguarded, so a down writer
   made `POST /policies/{policy_id}/revoke` raise straight out of the route — a 500, even though
   the policy's own level change had already been applied to `store.policies` and was never rolled
   back. Revoke now uses the exact same pending-on-failure handling stop-all and pause use (see the
   revoke route above): the level change always lands, the event never raises past the route, and a
   writer failure leaves the part pending in the policy's mapped world, to be flushed by a later
   mutating call that touches that world.

## `tilo_api.deps` (new module; does not exist yet — every test here fails on this import until
the builder adds it)

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Protocol

Role = Literal["owner", "team_lead", "approver", "viewer"]


@dataclass(frozen=True)
class Principal:
    """The test double for auth (real sign-in is a later ticket). One instance per request,
    supplied by overriding get_current_principal in tests via app.dependency_overrides."""

    user_id: str  # common.schema.json#/$defs/user_id
    role: Role
    world_id: str | None = None  # The one world this principal is a member of (the sign-in layer
    # resolves it from the world's own membership record, PRD 15.3
    # orgs/{org}/users/{uid}); None means no membership anywhere.
    # Every world route checks principal.world_id == the path's
    # world_id before it does anything else with store.worlds --
    # a mismatch (wrong world, or no membership) gets exactly the
    # same 404 as an unknown world_id, so a caller cannot tell
    # "that world does not exist" from "you are not in it" (ST-3a
    # round 1 security finding).
    domain: str | None = None  # team_lead's PRD 8.3 expert domain; None otherwise
    districts: tuple[str, ...] = ()  # districts this principal may see beyond "vis": "all":
    # a team_lead's domain districts, or a viewer's shared
    # scope. Ignored when role == "owner" (owner sees
    # everything, PRD 10.1). An approver's visibility is their
    # assigned cards' context (PRD 10.1); the two read routes
    # below treat "approver" the same as "viewer" (districts
    # only) since neither route is card-scoped -- noted as an
    # open question below, not required by FR-HIL-09/SEC-07's
    # own acceptance text (which names Viewer and Team Lead).


@dataclass
class DistrictRecord:
    name: str
    summary: str


@dataclass
class WorldRecord:
    owner: str  # common.schema.json#/$defs/user_id
    owner_channels: tuple[
        str, ...
    ]  # common.schema.json#/$defs/channel values; the owner's enabled channels for kill-switch confirmations
    districts: dict[
        str, "DistrictRecord | None"
    ]  # district_id -> DistrictRecord, this world's full layout (owner's-eye view). A test may
    # store None or another malformed value under a key to prove the read routes fail closed
    # (treat it as hidden) rather than raising.
    run_id: str  # common.schema.json#/$defs/run_id: the world's current run, the harness's own
    # record. tilo-api reads this to know which run an event belongs to; it never
    # invents one (PI-18 round-1 finding: run_id = f"r_{world_id}" was tilo-api's own
    # guess, not the harness's actual run).
    paused: bool = False  # round-4 addition (security finding, biggest): true once a Pause-all
    # against this world has actually paused it. This -- and only this -- is what
    # dedupes world.paused: the round-3 builder instead skipped building a
    # world.paused part whenever this call's own "stopped" count was 0, which
    # silently dropped the event on a Pause-all that follows a Stop-all (every
    # policy already L1, so stopped == 0) and on a world with no L2/L3 policies
    # to begin with (stopped == 0 on the very first call too). Both are real
    # pauses that must leave a durable record. The pause route sets this field
    # True, under the same lock that serializes its own mutation (see "Locking"
    # below), the moment it decides to build a world.paused part; a call that
    # finds it already True builds no new part (the world is already paused --
    # a true idempotent repeat, the same shape as Stop-all's already_l1 skip for
    # a policy already provably at L1). No route this ticket adds ever reads
    # this field back out to a caller (it is not in any GET response body) --
    # it exists purely to make the dedupe decision an atomic flag check instead
    # of an inference from "did anything else change this call."


@dataclass
class Store:
    """In-memory injected state (no Firestore this ticket). One instance built fresh per test
    and supplied by overriding get_store; a route handler mutates it in place, the same object
    the test holds, so a test can inspect the result without a second GET."""

    worlds: dict[str, WorldRecord] = field(default_factory=dict)
    policies: dict[str, dict] = field(
        default_factory=dict
    )  # policy_id -> policy.schema.json record (mutated in place: level, changed_by, history).
    # A test may store a record missing "history", with "history" not a list, or with
    # "level" absent or not one of L0..L3, to prove a kill switch fails safe (round-1
    # qa/security finding: such a record must still end at L1 with exactly one new
    # event, never a 500, never left half-changed against its siblings).
    policy_worlds: dict[str, str] = field(
        default_factory=dict
    )  # policy_id -> world_id whose event stream receives that policy's policy.changed events
    # (policy.schema.json itself carries no world_id, PRD 15.3 keeps policies at the org
    # level; this map is this ticket's own bookkeeping, not a new contract field). A
    # policy_id absent from this map has "no world mapping" (round-1 finding: Stop-all
    # must not KeyError on it -- it still lowers to L1 and its policy.changed goes into
    # the stream of the world Stop-all was pressed in, not dropped).
    events: dict[str, list[dict]] = field(
        default_factory=dict
    )  # world_id -> event.schema.json records, append-only, oldest first (seq strictly increasing,
    # EV-10). Only EventWriter.append appends here; a route handler never does.
    pending_events: dict[str, list[dict]] = field(
        default_factory=dict
    )  # world_id -> event parts a mutating route built but EventWriter.append raised on
    # (round-3 qa/security finding: the writer being unreachable must not stop the kill switch
    # from lowering autonomy). A part lands here, in the order it was built, when the writer
    # rejects it; tilo-api removes it from here and appends the writer's stamped result to
    # Store.events on a later successful flush. Round-4 addition: a part can land under a
    # world_id *other than* the one the request path named (a policy Stop-all lowers can be
    # mapped, via policy_worlds, to a different world than the one Stop-all was pressed in) --
    # revoke's own part (round-4: revoke now participates in this mechanism too, see "Pending
    # writes and flush" below) can equally land under a world other than the request's, since
    # revoke's route carries no world_id of its own at all. See "Pending writes and flush" under
    # the stop, pause and revoke routes for exactly which worlds a given call flushes and counts.


class EventWriter(Protocol):
    """The single writer of events (PRD 15.3). tilo-api builds an event *part* -- every
    event.schema.json field except v, id, seq, ts, world_id, run_id and trace (trace defaults to
    all-null; neither event type this ticket emits makes a model or tool call) -- and hands it
    here. A production implementation talks to the harness process; this ticket only pins the
    call shape. Every test supplies its own in-memory stand-in (`_api_lib.FakeEventWriter`) that
    stamps id/seq/ts/run_id itself (from Store.worlds[world_id].run_id and a per-world counter,
    O(1) per call -- PI-18's "one writer" also fixes round 1's O(n) rescan-per-event) and appends
    to Store.events, and that records every call so a test can assert the *un*stamped part
    tilo-api handed over carried none of those four fields."""

    def append(self, world_id: str, part: dict) -> dict:
        """part keys: type, actor, target, level, district, item, severity, credits, summary,
        cause, vis, authz, data (any key the caller has no value for is set to that field's
        schema-honest default: null, "info", 0, or "all" for vis). Returns the fully stamped
        event.schema.json record that was appended to store.events[world_id]."""
        ...


def get_current_principal() -> Principal:
    """Raises NotImplementedError in production until real sign-in lands; every test overrides
    this via app.dependency_overrides[get_current_principal]."""
    raise NotImplementedError


def get_store() -> Store:
    """Raises NotImplementedError in production until Firestore wiring lands; every test
    overrides this via app.dependency_overrides[get_store]."""
    raise NotImplementedError


def get_event_writer() -> EventWriter:
    """Raises NotImplementedError in production until the harness wiring lands; every test
    overrides this via app.dependency_overrides[get_event_writer]."""
    raise NotImplementedError
```

## Routes (new; `tilo_api.app` currently has only `GET /healthz`)

All routes take `principal: Principal = Depends(get_current_principal)` and
`store: Store = Depends(get_store)`; the three that emit events also take
`writer: EventWriter = Depends(get_event_writer)`. `now()` is read internally by the handler
(`datetime.now` wrapped as an RFC 3339 string, `common.schema.json#/$defs/timestamp` shape) only
for `policy["history"]` and `policy["changed_by"]` entries (plain dict fields tilo-api itself
owns) — never to stamp an event's own `ts`, which is `EventWriter`'s job now; no clock is
injected, "the injected clock or wall time, whichever is honest" resolved toward wall time since
a fake clock would not prove the ≤ 5 s requirement about anything real.

### World membership check (applies first, on every route below that takes a `world_id` path
parameter: stop, pause, the two GETs)

Before anything else: if `principal.world_id != world_id`, respond exactly as for
`world_id not in store.worlds` — same status (404), same body, so a caller cannot distinguish "no
such world" from "you are not a member of it". Only once `principal.world_id == world_id` does
the handler read `store.worlds.get(world_id)` and 404 if that lookup itself misses (a member
whose own world record is missing is an inconsistent store, treated the same way — still 404, no
new status code invented for it).

### `POST /worlds/{world_id}/autopilot/stop` — FR-HIL-07, PI-13, PI-18

- 404 per the membership check above.
- 403 when `principal.world_id == world_id` but (`principal.role != "owner"` or
  `principal.user_id != store.worlds[world_id].owner`); the store is unchanged.
- 200 or 202 otherwise (202 exactly when this call's response `"pending"` count is nonzero — see
  "Pending writes and flush" below; 200 whenever it is 0). **Flush this world's pending parts
  first** (below), **then validate the rest of the request, then apply (no half-apply):** build
  the full list of `(policy_id, policy)` pairs in `store.policies` whose
  `policy.get("owner") == store.worlds[world_id].owner` before mutating anything; skip a policy
  whose `policy.get("level") == "L0"` (already below L1, left untouched, not counted) or a policy
  that is **consistently** at L1 — `policy.get("level") == "L1"` **and**
  `isinstance(policy.get("history"), list)` **and** its non-empty history's `[-1].get("level") ==
  "L1"` — as an idempotent repeat (`already_l1` += 1, no history entry, no event, the record is
  left exactly as it was, round-3 code-review finding "no silent history repair": a policy that
  merely *reads* L1 while its own history disagrees, or has no readable history at all, is an
  *inconsistent* record, not a proven-idempotent repeat). Every other policy — whatever its
  `level` reads as, including missing or not one of `L0`..`L3`, and including an L1 whose history
  disagrees or is unreadable — gets exactly one history entry
  `{"by": owner, "at": now, "change": "stop_all", "level": "L1"}` appended to `policy["history"]`
  (a missing or non-list `history` is replaced with a fresh one-entry list, never raises), or, for
  the inconsistent-L1 case, simply appended to the disagreeing-but-list-shaped history that is
  already there — never rewritten or "repaired" in place, so the earlier (wrong) entry stays in
  the audit trail exactly as it was — `policy["level"] = "L1"`,
  `policy["changed_by"] = {"by": owner, "at": now}`, and exactly one `policy.changed` part built
  for the target world `store.policy_worlds.get(policy_id, world_id)` (a policy with no entry in
  `policy_worlds` still gets an event, routed to the world Stop-all was pressed in, never a
  `KeyError`) and handed to the writer, per "Pending writes and flush" below (so a writer failure
  on this part does not stop the level change or block its siblings). The part's `data` is
  `{"policy_id": policy_id, "change": "stop_all", "level": "L1"}`, `authz` is
  `{"by": "person", "ref": owner, "at": now}`, and `vis` is the intersection of the policy's own
  `scope.districts` with **the target world's own districts** — `store.worlds[target_world_id]
  .districts`' own keys, where `target_world_id` is that same `store.policy_worlds.get(policy_id,
  world_id)` the event is routed to, *not* `store.worlds[world_id]` (the world Stop-all was
  pressed in) — in the policy's own list order, when that intersection is non-empty (missing or
  malformed `scope`/`scope.districts`, or `target_world_id` missing from `store.worlds` entirely,
  treated as empty, i.e. no intersection to compute), else `"all"` (EV-13; see "`policy.changed`
  visibility" below — round-4 code-review finding, biggest: round 3 computed this intersection
  against `store.worlds[world_id]`, the *request* world, even for a policy mapped to a different
  world B — so a policy scoped to districts that exist only in B, stopped from world A, got `vis:
  "all"` instead of the correct district list, because the intersection against A's own layout
  came out empty. `vis` must reflect where the event is actually filed, not where the button was
  pressed). No request ever returns 500, whatever shape the matched policies are in or however the
  writer behaves, and every policy actually changed this call is reflected — none are skipped
  because another one in the same call was malformed or because the writer rejected its part.
- Response body:
  `{"stopped": <int>, "already_l1": <int>, "confirmations": [{"channel": c} for c in store.worlds[world_id].owner_channels], "pending": <int>}`.
  `"stopped"` counts only policies actually changed this call (including malformed ones and
  inconsistent-L1 ones that were still lowered) — a policy's level change and `"stopped"`/
  `"already_l1"` classification never depend on whether its `policy.changed` part was
  successfully written (round-3 finding: the kill switch is the level change; the event is the
  audit trail of it, and the two are not allowed to fail together). `"pending"` is the count of
  parts (this call's own, plus any this call flushed but that failed again) still sitting in
  `store.pending_events`, **summed across every world this call touched** (round-4 security
  finding: see "Pending writes and flush" below — a Stop-all against world A that routes a part to
  a mapped world B is just as responsible for B's pending count as for A's own, since this call is
  what built that part); it is `0` whenever the writer is healthy for every part this call built or
  flushed. Channel list assumed: `("web", "whatsapp", "email")` (PRD 10.2's "all enabled
  channels", `mobile_web` treated as the same surface as `web` for this ticket's confirmation
  purposes — logged as an ambiguity below, unchanged from round 1).
- Performance: 200 policies owned by the world's owner complete within 5 s wall-clock whether the
  writer is healthy, entirely down, or slow-then-failing (PI-18's per-world O(1) counter, not
  round 1's O(n) rescan per event, is what makes this hold at n=200 without the budget being a
  coincidence of hardware; round-3 finding: catching a raising writer per part must not itself
  become an O(n) source of latency that blows the budget either). This holds on a **retry** too: a
  second Stop-all issued while the writer is still down (nothing left to lower, but still
  attempting to flush up to 200 pending parts) also completes within 5 s — round-3's own fix
  already required this per-call, but round-4 makes explicit that "flush what's pending" is itself
  bounded by the same budget, not an unbounded per-part retry loop that could itself take
  `n * writer_latency`.
- Locking (round-4 finding, qa biggest): every targeted policy's level, history and `changed_by`
  are updated to L1 in `store.policies` **before** this call attempts any writer call for that
  policy's part — the level change is what "instant" means for a kill switch (PRD 10.4), the event
  is only its audit trail. Whatever serializes two concurrent calls against the *same* world (so
  they do not each independently read the pre-change state and double-apply, round-3's concurrency
  finding) must not also serialize calls against *different* worlds behind writer I/O: writer calls
  happen outside that serialization, or through a flush bounded well under the 5 s budget
  regardless of how many parts are pending or how slow the writer is per call, so that a kill
  switch pressed against world A never waits on world B's writer latency, and vice versa. A
  one-policy Stop-all against a different, otherwise-idle world, issued while a 200-policy Stop-all
  against a slow-and-failing writer is still in flight for another world, finishes in under 1 s.

### Pending writes and flush (round-3 qa/security finding, applies to stop and pause)

`EventWriter.append` can raise (the harness is unreachable). When it does for a given part,
tilo-api does **not** let that exception propagate, and does **not** skip or re-attempt the level
change the part records: the part (exactly what would have been handed to `append`) is appended to
`store.pending_events.setdefault(world_id, [])` instead, in the order it was built, and counted in
that call's `"pending"` response field. The level change, history entry and `changed_by` already
applied to `store.policies` are not rolled back — the kill switch already took effect.

**Flush trigger (resolved ambiguity, round 1-3, extended round 4):** before doing any of its own
new work, every mutating route (`stop`, `pause`, and, as of round 4, `revoke`) first attempts to
flush pending parts through the writer, oldest first per world: on success a part is handed to
`writer.append` and, once it returns, removed from `pending_events` (the stamped record the writer
returns is already in `store.events` by then, since `FakeEventWriter.append` appends it itself); on
failure it is left in `pending_events`, still counted toward `"pending"` in *that* call's response.
This makes "the next mutating call that touches a world" — not a background retry, not a separate
flush endpoint — the one resolved trigger; a world nobody ever calls a mutating route against again
simply keeps its parts pending (acceptable: nothing in FR-HIL-07 requires a background job this
round). Because a part is removed from `pending_events` only after a successful `append`, and
`append` is only ever called once per part per attempt, no part is ever written twice, and a part
that keeps failing stays pending indefinitely rather than being dropped.

**Which worlds a call touches (round-4 resolved ambiguity, security finding: "pending must count
every world this call reaches"):** `stop` and `pause` can route a `policy.changed` part to a world
*other than* the one named in the request path, via `store.policy_worlds` (see "Policy-to-world
routing" below) — a part that fails to write there is exactly as pending as one that fails for the
request's own `world_id`, and must be flushed and counted the same way, or an owner who only ever
calls Stop-all against world A could never learn that A's Stop-all left something pending in B, nor
ever get it flushed. "Touches" is defined as: the request's own `world_id`, plus
`store.policy_worlds.get(policy_id, world_id)` for **every** policy owned by
`store.worlds[world_id].owner` — the same set the route's own plan-building step already reads,
whether that policy ends up skipped (`L0`, or a provably-consistent `already_l1`) or actually
lowered this call, so a later call that changes nothing new for an already-fully-stopped world
still flushes what an earlier failed call left pending in a mapped world. `revoke` touches only
`store.policy_worlds.get(policy_id)` for its own one policy (or nothing, if unmapped — see the
revoke route below). Before doing any of its own new work, a route flushes
`store.pending_events.get(w, [])` for every world `w` it touches this call (the request's own
`world_id` first, then each other touched world, deduplicated, in no particular further order —
this ticket's tests do not depend on flush order across *different* worlds, only on per-world
ordering, which stays oldest-part-first per the paragraph above). The response's `"pending"` is the
sum, across every touched world, of `len(store.pending_events.get(w, []))` once that flush attempt
finishes — not only the request's own `world_id`'s queue (round-3's own text implied this by
omission; round-4 makes it explicit after the round-3 implementation summed only `world_id`'s own
queue and so under-reported, and under-flushed, a world a Stop-all's own policies mapped to).
Picking "every world this call touches" over "every world in the store" keeps a Stop-all against a
world with nothing mapped elsewhere from ever having to scan unrelated worlds' pending queues, and
keeps the per-call cost proportional to the same owned-policy scan PI-18 already requires, not to
the size of the whole store.

### `POST /worlds/{world_id}/pause` — FR-HIL-07 ("Pause all stops the agents too", PRD 10.4)

- Same membership and 404/403 as stop-all above.
- Request body: `{"channel": <common.schema.json#/$defs/channel> | null}`
  (`web` | `mobile_web` | `whatsapp` | `email` | `null`; **typed to the schema's own enum**, so a
  value outside it is a 422 from request validation, before the handler runs — nothing in the
  store changes and nothing is emitted. Default `null` when the field is omitted; tests always
  pass one explicitly for the 200 paths to keep that default's own edge case out of scope, per
  the ambiguity logged below).
- 200 or 202 (same rule as stop-all): runs the same "flush every touched world's pending parts
  first, then every owner policy to L1, validate first" step as stop-all (same fail-safe,
  no-half-apply and no-silent-repair rules, same `policy.changed` parts including the per-policy
  `vis` rule computed against each part's own target world, and the same per-part
  pending-on-failure handling), **plus**, under the same lock that serializes this route's own
  mutation, checks `store.worlds[world_id].paused`: when it is **not already `True`**, sets it
  `True` and builds and hands the writer exactly one `world.paused` part for `world_id` itself
  (never `policy_worlds`) with `data == {"reason": "pause_all", "channel": <body.channel>}`,
  `authz: null` (`world.paused` is `side_effect: false`, registry `events/registry.yaml`),
  `vis: "all"` — subject to the same pending-on-failure handling as every other part this call
  builds. When `store.worlds[world_id].paused` is **already `True`** when this call reaches that
  check, no new `world.paused` part is built at all this call — the world is already durably
  paused, a true idempotent repeat.

  **This dedupe is keyed on the `paused` flag alone, checked under the lock, never on whether this
  call's own Stop-all step actually lowered any policies** (round-4 security finding, biggest: the
  round-3 implementation instead built a `world.paused` part only when `stopped > 0`, which is
  *not* the same thing — a Stop-all pressed right before Pause-all leaves every owned policy
  already at L1, so a following Pause-all's own `stopped` reads `0` even though the world was never
  actually paused before; a world with zero `L2`/`L3` policies to begin with reads `stopped == 0`
  on its very first-ever Pause-all call too. Both are real, first-time pauses that a
  `stopped`-keyed dedupe silently drops — leaving Pause all with *no* durable record at all, the
  opposite of PRD 10.4's "Pause all stops the agents too" being something a viewer or auditor can
  later see happened). `"paused"` is `true` whenever the request reaches this point at all (the
  level changes and the pause intent both took effect, PRD 10.4 "Pause all stops the agents too"),
  regardless of whether the `world.paused` part itself is still pending, and regardless of whether
  this call built a new one or found the flag already set.
- Response body:
  `{"stopped": <int>, "already_l1": <int>, "paused": true, "pending": <int>}` (`"pending"` defined
  exactly as in stop-all's response — every touched world's pending queue, summed, after this
  call's own flush and new work, counting the `policy.changed` parts and the `world.paused` part
  alike when one was built this call).

### `POST /policies/{policy_id}/revoke` — FR-HIL-07, PI-13

- 404 when `policy_id` is not in `store.policies`, **or** when
  `principal.user_id != store.policies[policy_id]["owner"]` (whatever `principal.role` is) —
  exactly the same status and body either way, so a non-owner cannot tell "no such policy" from
  "not yours" (round-1 security finding; this collapses what round 1 answered with 403 for a
  known policy into the same 404 an unknown policy id gets). The store is unchanged in both
  cases.
- 200 otherwise, **never 500 even when the writer is down** (round-4 qa/security finding, follow-up
  to round 3's stop/pause fix: revoke must fail exactly as safe as the bulk kill switches do).
  Appends one history entry `{"by": owner, "at": now, "change": "revoked", "level": "L1"}` (always
  appended, even if already L1 — revoke is a distinct, explicit act unlike the bulk Stop-all, so no
  idempotency skip here; a missing or non-list `history` is replaced the same fail-safe way
  stop-all does), sets `level = "L1"`, `changed_by = {"by": owner, "at": now}` — **this part never
  depends on the writer and is never rolled back, whatever the writer does next** — and builds one
  `policy.changed` part (`data.change == "revoked"`, `data.level == "L1"`, `vis` by the same
  target-world-scope-intersection rule as stop-all, computed against the policy's mapped world's
  own districts) for the policy's mapped world, `store.policy_worlds[policy_id]`, handed to the
  writer per the same "Pending writes and flush" rule stop-all and pause use: a writer failure
  keeps the part in `store.pending_events.setdefault(mapped_world_id, [])` instead of raising or
  being lost, to be flushed by a later mutating call that touches that world (revoke's own flush
  duty is limited to its own one part before doing its own new work — see "Which worlds a call
  touches" above; revoke does not proactively flush a *different* policy's pending parts, only its
  own policy's, since revoking policy X has no reason to also attempt policy Y's stuck write). A
  policy with no world mapping (policies live at org level, PRD 15.3) is still revoked (history
  entry, L1), but no event (pending or otherwise) is handed to any world: revoke has no world of
  its own, and an event is never filed under a world that does not exist (PRD 9.4 honesty). The
  history entry is the audit record either way.
- Response 200 body: `{"policy_id": policy_id, "level": "L1"}` (unchanged from round 2 and round 3
  — revoke is a single-policy, single-event act, not a bulk operation, so its response carries no
  `"pending"` field of its own; a caller that needs to know whether revoke's own event is still
  pending reads it the same way any other pending part is observed in this ticket's tests, via the
  store, not a dedicated response field — round-4 resolved ambiguity, see below).

### `GET /worlds/{world_id}/events` — FR-HIL-09, SEC-07

- 404 per the membership check above.
- 200: `{"events": [...]}`. `store.events.get(world_id, [])` is filtered to the events `principal`
  may see, in original order, then each kept event is rebuilt by **allowlisting**, never by
  copying the stored event forward and patching a few fields (round-3 security finding, biggest:
  copy-then-patch is how round 2 missed `id`, `trace.archive_ref`, `data.message_ref` and a
  hidden `district` on a `vis: "all"` event). A malformed event (see below) never reaches either
  step — it is dropped before filtering, for every principal, owner included.

  **Visibility filter** (unchanged from round 2):
  - kept when `event["vis"] == "all"`;
  - kept when `principal.role == "owner"` and `principal.user_id == store.worlds[world_id].owner`
    (the owner sees everything regardless of `vis`, PRD 10.1);
  - kept when `event["vis"]` is a list and it intersects `principal.districts` — **only when
    `principal.districts` is actually a `tuple`/`list`/`set` of strings**; a `principal.districts`
    that reads as a bare `str` (round-3 security finding: a caller supplying one by mistake) is
    never iterated character-by-character or matched by Python's `in` substring operator against
    it — treated as `()`, no districts, same as an empty tuple;
  - dropped otherwise — removed from the list entirely, so nothing about a hidden event (its
    `summary`, `data`, or any other field) appears in the response.

  **Owner vs. everyone else, at the top level:** PRD 15.3 gives the owner the **full stream**
  (`orgs/{org}/worlds/{world}/events/{seq}`) and gives every other role a **redacted view**
  (`orgs/{org}/worlds/{world}/views/{scope}/events/{seq}`) — two different collections, not one
  filtered read of the same collection. This route stands in for both reads from the one
  in-memory `store.events`: for the owner it returns the surviving events with their **real,
  unchanged** `seq` and `id` (filtering keeps everything for the owner, so the real `seq` is
  already dense and this is not a special case); for everyone else it returns the **view-local**
  `seq`/`id` scheme below. This is why the owner-sees-everything property test asserts real ids
  and the scoped-view tests assert view-local ones — they are reading two different kinds of
  stream, per PRD 15.3, not the same stream with different amounts of blanking.

  **Allowlisted fields of a kept event, and how each is rebuilt** (everything not named here is
  dropped, never merely omitted-if-falsy — the response only ever contains keys this list names):

  | Response field | Owner (full stream) | Everyone else (redacted view) |
  | --- | --- | --- |
  | `seq` | the stored event's real `seq`, unchanged | the view's own dense position, `1, 2, 3, ...` in survival order (round-1/round-2 fix: the store's real `seq` is never returned to a scoped principal, so it cannot count the gaps where hidden events were dropped) |
  | `id` | the stored event's real `id`, unchanged | the view-local id `f"v{seq}"`, built from *this event's own view `seq`* above (round-3 finding: the real store `id`'s ULID ordering would itself hint at how much else happened in the run, so a scoped principal never receives it, even for an event it can see) |
  | `ts`, `type`, `level`, `severity`, `credits`, `summary`, `authz` | unchanged from the stored event | unchanged from the stored event |
  | `target`, `actor` | unchanged from the stored event | the stored value when it does **not** match `common.schema.json#/$defs/district_id`'s pattern (`^D[0-9]{1,4}$`), or when it does and that district is visible to this principal (one of `principal.districts`); **`null` when it matches the district_id pattern and names a district outside `principal.districts`** (round-4 security finding: `target`/`actor` may legally be a district id per `event.schema.json#/$defs/target`'s own `anyOf`, so either field can leak a hidden district's id exactly like the dedicated `district` field below, and must fail closed the same way) |
  | `district` | the stored event's real `district` | the stored `district` when it is `None`, or is one of `principal.districts`; **`null` when it names a district outside `principal.districts`**, even if the event itself is kept via `vis: "all"` (round-3 finding: an event's own visibility does not make every field on it safe to show) |
  | `cause` | unchanged | the *view-local id* (same `f"v{seq}"` scheme, using the **causing event's own view `seq` in this same response**) of the causing event, when that event survived filtering; `null` when it names an event that was dropped or never existed (round-1 rule, now expressed via the view-local id instead of the real one, since the real one is never returned to a scoped principal) |
  | `vis` | unchanged | `"all"` stays `"all"` (nothing to filter); **a district list is filtered to its intersection with `principal.districts`** before being returned — never the stored event's full, unfiltered list (round-4 security finding: the event is kept whenever `vis` intersects `principal.districts` at all, but the *full* stored list can name additional districts the caller cannot see at all, and returning it unfiltered tells that caller "someone else can see this too, and here is exactly which other district" — a leak of a hidden district's *id* through a field that was previously assumed safe because "it is never itself sensitive." The kept intersection is always non-empty, since the event would not have survived filtering otherwise, so this never turns a visible event invisible) |
  | `data` | unchanged | rebuilt by walking the stored `data` value **recursively** (round-4 finding, extending round 3's top-level-only pass: a dict's values, and every item of a list, at any depth) applying, to every string leaf found: (1) if the key it is stored under is `"message_ref"` (at any depth, not only top-level), always `null` for a non-owner, regardless of shape, per the `trace.archive_ref` rule below; (2) else if it matches the ULID pattern, the same cause-style remap — the view-local id of the event it names, if that event survived filtering, else `null` (for example `policy.applied.data.instruction_id`, or the same value nested inside a list or a sub-object); (3) else if it matches the district_id pattern (`^D[0-9]{1,4}$`) — including but not limited to a value stored under the key `"district"` (`data.district` gets exactly the same treatment as the event's own top-level `district` field above, since a data payload can carry its own district reference independent of the event's) — the value unchanged when that district is visible to this principal, else `null`; every other value (a non-string, or a string matching none of the above) is left exactly as stored. The dict/list *shape* of `data` is always preserved; only leaf string values are ever rewritten. |
  | `trace` | unchanged | every field unchanged **except `archive_ref`, which is always `null`** (round-3 finding: `archive_ref`/`message_ref` name a position in the run-wide raw archive — PRD 13.2 — a counter unrelated to district visibility that would let a scoped viewer infer how many raw records exist between two events it can see, so it is stripped outright rather than filtered by visibility) |

  A kept event's real store `id` and `trace.archive_ref` therefore never appear anywhere in a
  non-owner response — not as that event's own `id`/`archive_ref`, not inside another event's
  `cause` or a ULID-shaped `data` field, not inside `data.message_ref`. The owner's response
  never contains a view-local id at all.

### Malformed events (round-3 finding, code/qa/security)

An event in `store.events[world_id]` may itself be malformed — missing `id` (or `id` not a
string), a `cause` that is not a string or `None` (for example a list), or missing any other key
this schema requires. Such an event is dropped before the visibility filter runs, for **every**
principal including the owner (resolved default, this ticket may only write
`services/api/tests`: the same "cannot be safely read, cannot be honestly shown to anyone" rule
round 2 already applies to a malformed `WorldRecord.districts` entry). It never raises (never a
500) and never blocks its well-formed siblings in the same response.

### `GET /worlds/{world_id}` — FR-HIL-09, SEC-07 (layout/summary)

- 404 per the membership check above.
- 200: `{"world_id": world_id, "districts": [...], "has_hidden_districts": bool}`.
  `districts` lists only the districts `principal` may see (same visibility rule as above, using
  `store.worlds[world_id].districts`' keys as the district ids): each visible entry is
  `{"id": did, "name": ..., "summary": ...}`. A **hidden district is left out of the list
  entirely** — not included with its name blanked or its id kept — because no hidden district's
  id or name may appear anywhere in the response JSON; `has_hidden_districts` is the only trace
  that fog exists (a bare boolean, no id, no name, no count, matching PRD 10.1 "hidden districts
  show fog with no names or counts"). **Fail closed on a malformed record:** a district entry
  that is `None` or otherwise missing a usable `.name`/`.summary` is treated as hidden — left out
  of `districts` and counted toward `has_hidden_districts` — never a 500, whoever is asking
  (even the owner, who otherwise sees everything: a malformed record cannot be shown, honestly,
  to anyone).

## `policy.changed` visibility (EV-13; security review round-1 and round-3 findings)

Every `policy.changed` part this ticket's three routes build (stop-all, pause, revoke) sets `vis`
from the **intersection** of the policy's own `scope.districts` with the target world's own
layout, `store.worlds[world_id].districts`' keys, at the moment of change (round-3 finding,
security b): `scope.districts` non-empty and that intersection non-empty → the intersection, in
the policy's own list order (so only viewers who can see every one of those districts — in
practice, viewers whose `principal.districts` intersects the list, plus the owner — receive the
event, and `event.rules.md` EV-13's "every district `vis` lists exists in the world's layout" is
satisfied even though a policy's own `scope.districts` may name a district outside this world
entirely, since `policy.schema.json` carries no `world_id` of its own, PRD 15.3); empty, missing,
or malformed `scope`/`scope.districts`, **or** an intersection that comes out empty (every scoped
district is foreign to this world) → `"all"` (unrestricted event — **open question**, logged
here since `docs/open-questions.md` is out of reach for this ticket: the contract
(`event.schema.json#/$defs/vis`) has no "owner-only" `vis` value to fall back to instead, only
`"all"` or a non-empty district list per EV-13's own `district_list` schema, `minItems: 1`; `"all"`
is the closest honest value available, even though it technically broadcasts wider than the
policy's own scope intended). Revoke — whose route carries no `world_id` of its own — computes
this intersection against the synthetic world its event is routed to (ambiguity 3 below), which
has no real layout, so a revoked policy's `vis` is `"all"` whenever it has no `policy_worlds`
mapping to a real world; when it does have a mapping, the same intersection rule applies. The
event's own `district` field stays `null` either way — nothing in this ticket ties a policy
change to a single rendered district — so EV-13's "a list includes the event's own district"
clause does not constrain it (that clause only fires when `district` is set).

## Role resolution this ticket assumes (not itself a new route)

No `/auth` or `/whoami` route exists yet; the builder's real role and world-membership resolver
(reading `orgs/{org}/users/{uid}`, team assignments, and per-world membership, PRD 15.3) is later
work. This ticket only pins the `Principal` shape (now including `world_id`) the routes above
consume once resolved, and every test constructs `Principal` directly and installs it with
`app.dependency_overrides[get_current_principal] = lambda: principal`.

## Ambiguities resolved (kept out of `docs/open-questions.md`: this ticket may only touch
`services/api/tests/`; logged here and in the test-writer's report instead)

1. **Idempotency of Stop-all** (revised round 3): a policy is skipped as an idempotent repeat
   (`already_l1`, no duplicate history entry or event) only when it is *provably* already
   consistent — `level == "L1"` **and** its own `history[-1]["level"] == "L1"` too. A policy
   whose `level` cannot be read as one of `L0`..`L3` (missing or malformed) is treated as *not*
   proven to be at L1 already, so it is lowered and counted as `stopped`, not `already_l1` — the
   fail-safe reading PI-13 needs ("the level reaches L1 and stays covered by nothing") over the
   alternative of leaving an unreadable record untouched. Round 3 extends this same fail-safe
   reading to a `level` that *does* read as `"L1"` but whose `history` disagrees or is unreadable:
   round 2 treated a bare `level == "L1"` read as sufficient proof of idempotency and silently
   left such a record alone (never emitting the audit event a "real" Stop-all always emits for
   every policy it actually touches); round 3 no longer trusts `level` alone once `history` exists
   and disagrees with it — that combination reads as an inconsistent record, not a proven repeat,
   and goes through the normal lowering path instead ("no silent history repair").
2. **Confirmation channel list** (unchanged from round 1): `("web", "whatsapp", "email")`, taking
   the ticket's own example; `mobile_web` folded into `web` for this ticket's confirmation-count
   purposes.
3. **Policy-to-world routing for `policy.changed` events** (unchanged from round 1; corrected
   wording this round — the "synthetic world" phrasing below contradicted item 7 and the revoke
   route's own text above it, which is the one every test in this directory actually pins):
   `policy.schema.json` carries no `world_id`; `Store.policy_worlds` is this ticket's own
   bookkeeping. A policy absent from that map is not an error: stop-all and pause route its event
   to the world the request was made against (never a `KeyError`); revoke (no `world_id` in its
   own path at all) instead emits no event for such a policy — see item 7.
4. **Hidden districts on `GET /worlds/{world_id}`** (unchanged from round 1): left out of the
   list entirely rather than included with blanked fields. New this round: a malformed district
   record is folded into the same "hidden" treatment, for the same no-leak reason, and additionally
   because a value tilo-api cannot safely read cannot be honestly shown to anyone, owner included.
5. **Pause-all's `channel` when the caller does not say** (unchanged from round 1): defaults to
   `null`; tests always pass an explicit channel to keep this untested edge out of scope. New this
   round: the field is enum-typed, so a caller that says an out-of-enum channel gets 422, not a
   silently-accepted junk value.
6. **World membership source** (new): `Principal.world_id` is a single value (one world per
   principal) because nothing in scope for ST-3a needs a principal bound to more than one world
   at a time; a person who owns or belongs to several worlds in the product's real data model is
   later work (the real sign-in/session resolver, PRD 15.3), out of scope for this in-memory test
   double.
7. **Revoke of a policy with no world mapping** (new): revoked (history entry, L1), no event
   handed to the writer; never a made-up world id.

## Ambiguities resolved this round (round 3)

8. **View-local id scheme.** A scoped (non-owner) response's event `id` is `f"v{seq}"`, where
   `seq` is that same event's own dense position in *this response* (ambiguity 1's "matches_level"
   business aside, this is a fresh pick, not implied by round 1 or round 2 text): simple,
   deterministic given the store's contents and the caller's own visibility, trivially distinct
   from a real ULID (which never starts with `"v"`), and derivable from data the route already
   computes for `seq` itself rather than needing a second id-minting scheme. A `cause` naming a
   visible event is remapped the same way, using that *other* event's own view `seq`. The owner's
   response never uses this scheme — see "Owner vs. everyone else" under
   `GET /worlds/{world_id}/events` above.
9. **Pending-write flush trigger.** Resolved as "the next mutating call (`stop` or `pause`)
   against the same `world_id`," not a background job or a dedicated flush endpoint — see
   "Pending writes and flush" above. ~~`revoke` does not participate in flushing this round~~
   **superseded, round 4: revoke now participates too — see ambiguity 12 below.**
10. **200 vs. 202 on stop/pause.** A response carries `202 Accepted` exactly when its own
    `"pending"` count is nonzero (something this call could not fully durably record), `200 OK`
    otherwise — PRD 10.4 and FR-HIL-07 only require "not a 500"; 202 was chosen over always-200
    so a caller (the web app, a WhatsApp confirmation flow) has a machine-readable signal that the
    kill switch worked but its audit trail is still catching up, without having to inspect the
    body to find out.
11. **Malformed-event ownership.** A malformed event is dropped from *every* principal's response,
    owner included (not only scoped ones) — see "Malformed events" above; this mirrors round 2's
    own resolution for a malformed `WorldRecord.districts` entry (ambiguity 4) rather than
    introducing a second rule for events.

## Ambiguities resolved this round (round 4)

12. **Revoke's own flush scope.** Revoke now uses pending-on-failure for its own one part
    (ambiguity 9, superseded), but does not proactively flush any *other* policy's pending part for
    the same world when it runs — only its own. Flushing a whole world's backlog on a
    single-policy revoke would make one policy's revoke responsible for clearing another,
    unrelated policy's stuck write, which is a `stop`/`pause`-shaped bulk responsibility, not a
    revoke-shaped one; a world's other pending parts are still flushed the next time `stop` or
    `pause` touches that world, per "Which worlds a call touches" above.
13. **`paused`'s scope.** `WorldRecord.paused` is write-only from every route this ticket adds — no
    GET response exposes it, and no route ever clears it back to `False` (nothing in FR-HIL-07 asks
    for an "unpause" or "resume" route yet; PRD 10.4 only requires the pause to happen and be
    recorded). A later ticket that adds `world.resumed` (already registered, `contracts/events/
    registry.yaml`, unused by this ticket) would be the one to clear it.
14. **"Touches" for flush/pending purposes counts every *owned* policy's mapping, not just the
   ones a call actually lowers.** An alternative reading would have counted only worlds a call
   *changed something in* this time; rejected because that is exactly the same "did anything
   change" inference that caused finding 1 above (Pause's dedupe bug) — a call that changes nothing
   new (everything already `L1`) must still flush whatever an earlier failed call left pending in
   every world its owned policies map to, not just the worlds it happens to write to this time.
