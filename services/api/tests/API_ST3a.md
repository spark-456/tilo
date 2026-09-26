# `tilo_api` — public shape ticket ST-3a pins (kill switches + roles/redaction)

Requirements FR-HIL-07 (kill switches, PI-13, PI-18), FR-HIL-09 and SEC-07 (roles and redaction).
This file is the contract the builder implements exactly; the tests in this directory import only
what is listed here. Nothing here is business logic — it is the shape tests hold the builder to,
the same convention `packages/policy/tests/API.md` uses for P4-01.

Real sign-in, Firestore, and the harness's own internals are out of scope: this ticket adds route
handlers over an **injected, in-memory store** (no Firestore, no network; PRD 15.3's document
layout is the shape to keep in mind for a later ticket, not implemented here), an **injected
principal** (no real auth), and an **injected event writer** standing in for the harness (PRD
15.3: the harness is the only writer of events; tilo-api never stamps `id`, `seq`, `ts` or
`run_id`, and after issue #46 it never stamps `id` either past enqueue time — see below).

**History.** PR #39 (session ST-3a) covered both halves on one shared `Store`/`Principal` shape
across seven review rounds; PR #54 split it, shipping only the roles/redaction half (this same
file, trimmed) so the kill-switch half could be redone from a clean review slate. Issue #46 is
S0's binding decision that replaced round 7/ST-3a-3's writer-*instance*-identity retry design
(rejected in review a second time) with an id-based one — this redo. Round numbers below refer to
that same shared review history; only what still holds is kept.

## `tilo_api.deps` (module)

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Protocol

Role = Literal["owner", "team_lead", "approver", "viewer"]
Channel = Literal["web", "mobile_web", "whatsapp", "email"]


@dataclass(frozen=True)
class Principal:
    """The test double for auth (real sign-in is a later ticket). One instance per request,
    supplied by overriding get_current_principal in tests via app.dependency_overrides."""

    user_id: str  # common.schema.json#/$defs/user_id
    role: Role
    world_id: str | None = None  # The one world this principal is a member of. Every world route
    # checks principal.world_id == the path's world_id before it does anything else with
    # store.worlds -- a mismatch (wrong world, or no membership) gets exactly the same 404 as an
    # unknown world_id, so a caller cannot tell "that world does not exist" from "you are not in
    # it" (round-1 security finding).
    channel: Channel = "web"  # the session channel sign-in resolved for this request (round-6/
    # ST-3a-2, issue #38 item 5): the pause route's world.paused.data.channel comes from here,
    # never from the request body, so a caller cannot claim a confirmation channel it is not on.
    districts: tuple[str, ...] = ()  # districts this principal may see beyond "vis": "all":
    # a team_lead's domain districts, or a viewer's shared scope. Ignored when role == "owner"
    # (owner sees everything, PRD 10.1). `Principal` carries no `domain` field: PRD 10.1's role
    # table scopes a team lead's view by *districts*, not by domain, and domain only routes
    # questions to a team lead (FR-AGT-06), a capability no route here implements.


@dataclass
class DistrictRecord:
    name: str
    summary: str


@dataclass
class WorldRecord:
    owner: str  # common.schema.json#/$defs/user_id
    districts: dict[str, "DistrictRecord | None"]  # district_id -> DistrictRecord, this world's
    # full layout. A test may store None or another malformed value under a key to prove the read
    # routes (and the kill-switch vis computation) fail closed rather than raising.
    owner_channels: tuple[str, ...] = ("web", "whatsapp", "email")  # the owner's enabled channels
    # for kill-switch confirmations (PRD 10.2's "all enabled channels"; mobile_web treated as the
    # same surface as web for this purpose).
    run_id: str = "r_village_basic_1"  # the world's current run, the harness's own record; the
    # event writer reads this to stamp an event's run_id, never invents one.
    paused: bool = False  # true once Pause all has actually paused this world. This -- and only
    # this, checked under the world's own lock -- is what dedupes world.paused (round-4 security
    # finding, biggest: dedupe on "did this call's own Stop-all step lower anything" silently
    # drops two real, first-time-pause cases: a Pause-all right after a Stop-all, and a world with
    # no L2/L3 policies at all). PRD 9.4 honesty extends to this durable flag itself: it is never
    # observed True without a world.paused event existing somewhere in the store, pending or
    # committed.


@dataclass
class Store:
    """In-memory injected state (no Firestore this ticket). One instance built fresh per test and
    supplied by overriding get_store; a route handler mutates it in place, the same object the
    test holds."""

    worlds: dict[str, WorldRecord] = field(default_factory=dict)
    events: dict[str, list[dict]] = field(default_factory=dict)  # world_id -> event.schema.json
    # records, append-only (EV-10), oldest first. Only EventWriter.append writes here.
    policies: dict[str, dict] = field(default_factory=dict)  # policy_id -> policy.schema.json
    # record (mutated in place: level, changed_by, history). A test may store a record missing
    # "history", with "history" not a list, or with "level" absent or not one of L0..L3, to prove
    # a kill switch fails safe -- ends at L1 with exactly one new event, never a 500, never left
    # half-changed against its siblings.
    policy_worlds: dict[str, str] = field(default_factory=dict)  # policy_id -> the world whose
    # event stream receives that policy's policy.changed (policy.schema.json carries no world_id
    # of its own, PRD 15.3 keeps policies at the org level). A policy_id absent from this map
    # still gets an event, routed to the world a kill switch was pressed in, never a KeyError.
    pending_events: dict[str, list[dict]] = field(default_factory=dict)  # world_id -> event parts
    # a mutating route built but EventWriter.append has not yet confirmed committed -- this list
    # *is* that world's write queue, oldest first, deduped by each part's own `id` (issue #46),
    # never by content and never by which writer object attempts it. A part sits here both before
    # and during an attempt, and is removed only once `append` actually confirms it committed.


class EventRejected(Exception):
    """Raised by EventWriter.append when a caller resends an `id` already committed for that
    world_id with genuinely different content than what was committed under that id. Same id,
    same content -> idempotent success (the already-committed record is returned, nothing new is
    appended, EV-10). Same id, different content -> this exception: a genuine conflict must
    surface, never a silent overwrite and never a silently dropped new one."""


class EventWriter(Protocol):
    """The single writer of events (PRD 15.3). tilo-api builds every event.schema.json field
    except `seq`, `ts`, `run_id` and `trace` (trace defaults to all-null) -- **including its own
    `id`, a ULID, built once when the part is enqueued and resent unchanged on every retry**
    (issue #46) -- and hands the whole thing here. `append` dedupes on that `id` alone, never on
    raw content-equality and never on whether this call happens to be handed the same writer
    *object* as an earlier, still-outstanding attempt. A production implementation talks to the
    harness process (services/harness/writer.py implements the identical idempotent-by-id
    contract there, a small SH ticket under this same requirement); every test here supplies its
    own in-memory stand-in (`_api_lib.FakeEventWriter`), which stamps `seq`/`ts`/`run_id` itself
    (from `Store.worlds[world_id].run_id` and a per-world counter) on first commit only, returns
    the already-committed record unchanged on an idempotent-by-id retry, and raises
    `EventRejected` on a same-id/different-content conflict."""

    def append(self, world_id: str, event: dict) -> dict:
        """event keys: id (a ULID, the sole idempotency key, always present), type, actor,
        target, level, district, item, severity, credits, summary, cause, vis, authz, data (any
        key the caller has no value for is set to that field's schema-honest default). Returns
        the fully stamped event.schema.json record that is (or already was) appended to
        store.events[world_id]; raises EventRejected on a same-id/different-content conflict."""
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


def get_part_write_deadline_s() -> float:
    """Issue #46, S0's decision point 1: "Read the part deadline from config, not a constant
    tuned to the tests." Resolved through this same Depends() seam as get_store/get_event_writer/
    get_current_principal so a test can prove a route reads it fresh on every call rather than
    capturing a constant once at import time -- every test overrides this via
    app.dependency_overrides[get_part_write_deadline_s] (`_api_lib.as_part_write_deadline`), and a
    test may re-install a different value mid-test. Unlike the three functions above, this one
    has a real, working production default (reads `config/dispatch.yaml`'s
    `dispatch.part_write_deadline_s`, falling back to a hard-coded default if the file or key is
    missing) since it needs no per-request test double for a plain config value -- most tests
    never override it at all."""
    ...
```

## Routes (new; `tilo_api.app` currently has only `GET /healthz`)

Every route below takes `principal: Principal = Depends(get_current_principal)` and
`store: Store = Depends(get_store)`; the three that emit events (`stop`, `pause`, `revoke`) also
take `writer: EventWriter = Depends(get_event_writer)` and
`part_deadline_s: float = Depends(get_part_write_deadline_s)`. `now()` (`tilo_api.events`) is
used only for `policy["history"]`/`policy["changed_by"]` entries (plain dict fields tilo-api
itself owns) — never to stamp an event's own `ts`, which is `EventWriter`'s job.

### World membership check (applies first, on every route below that takes a `world_id` path
parameter)

Before anything else: if `principal.world_id != world_id`, respond exactly as for
`world_id not in store.worlds` — same status (404), same body, so a caller cannot distinguish "no
such world" from "you are not a member of it". Only once `principal.world_id == world_id` does
the handler read `store.worlds.get(world_id)` and 404 if that lookup itself misses.

### `POST /worlds/{world_id}/autopilot/stop` — FR-HIL-07, PI-13, PI-18

- 404 per the membership check above.
- 403 when `principal.world_id == world_id` but (`principal.role != "owner"` or
  `principal.user_id != store.worlds[world_id].owner`); the store is unchanged.
- 200 or 202 otherwise (202 exactly when this call's response `"pending"` count is nonzero).
  **Plans, then applies, in one pass under a lock — never half-applies:** every policy in
  `store.policies` owned by `store.worlds[world_id].owner` is considered; a policy at `"L0"` is
  skipped untouched (already below L1); a policy that is **provably** consistent at L1 —
  `level == "L1"` **and** its own non-empty `history`'s last entry also reads `"L1"` — is skipped
  as `already_l1` (a true idempotent repeat, no history entry, no event, the record left exactly
  as it was; round-3 finding "no silent history repair": a policy that merely *reads* L1 while its
  history disagrees, or has no readable history at all, is an *inconsistent* record, not a proven
  repeat, and goes through the normal path below). Every other policy — whatever its `level` reads
  as, including missing or not one of `L0`..`L3` — gets exactly one history entry
  `{"by": owner, "at": now, "change": "stop_all", "level": "L1"}` appended (a missing or non-list
  `history` is replaced with a fresh one-entry list, never raises; an inconsistent-L1 record's
  disagreeing history is never rewritten, only appended to), `level = "L1"`,
  `changed_by = {"by": owner, "at": now}`, and exactly one `policy.changed` part built for the
  target world `store.policy_worlds.get(policy_id, world_id)` (a policy with no entry in
  `policy_worlds` still gets an event, routed to the world Stop-all was pressed in, never a
  `KeyError`) and enqueued for that world, per "Pending writes and flush" below. The part's `data`
  is `{"policy_id": policy_id, "change": "stop_all", "level": "L1"}`, `authz` is
  `{"by": "person", "ref": owner, "at": now}`, and `vis` is computed by `events.policy_vis`
  against **the target world's own districts** (`store.worlds[target_world_id].districts`, not
  `store.worlds[world_id]`, the request world — round-4 finding, biggest: `vis` must reflect where
  the event is actually filed, not where the button was pressed) — see "`policy.changed`
  visibility" below. No request ever returns 500, whatever shape the matched policies are in or
  however the writer behaves.
- Response body:
  `{"stopped": <int>, "already_l1": <int>, "confirmations": [{"channel": c} for c in store.worlds[world_id].owner_channels], "pending": <int>}`.
  `"stopped"` counts only policies actually changed this call — a policy's level change never
  depends on whether its `policy.changed` part was successfully written (the kill switch *is* the
  level change; the event is its audit trail, and the two never fail together). `"pending"` is the
  count of parts still sitting in `store.pending_events`, **summed across every world this call
  touches** (the request's own `world_id`, plus every world an owned policy is mapped to via
  `policy_worlds` — round-4 security finding: a Stop-all that routes a part to a mapped world B is
  just as responsible for B's pending count as for A's own).
- Performance: 200 policies owned by the world's owner complete within 5 s wall-clock whether the
  writer is healthy, entirely down, or slow-then-failing. This holds on a **retry** too: a second
  Stop-all issued while the writer is still down also completes within 5 s.
- Locking: every targeted policy's level, history and `changed_by`, and every new part's
  enqueue, happen under a per-world **mutate** lock (sorted-and-acquired together across every
  touched world, to avoid lock-order deadlock between two calls touching overlapping world sets)
  — held only for that in-memory decision, **never across a `writer.append` call**. A *separate*,
  non-blocking per-world **drain** lock guards "at most one `append` in flight for this world at a
  time" (issue #46, S0's decision point 1): a call that finds it already held by another
  in-flight attempt (this call's own, or an earlier call's abandoned one) skips draining that
  world entirely this call, leaving the in-flight attempt — and everything behind it in that
  world's queue — exactly where it is. Because the mutate lock is never held across I/O, a kill
  switch against world A never waits on world B's writer latency, and a second call against the
  *same* world, issued while the first is still stuck on (or past the deadline of) a writer call
  that never returns, itself returns quickly: by the time it runs, the first call's mutate section
  has already released that world's lock, so the second call finds every policy already at L1.

### Pending writes and flush

`EventWriter.append` can raise, or simply not settle within its own per-part deadline (a hang).
Either way tilo-api does **not** let that stop the level change the part records, and does
**not** lose the part: it stays in (or is added to) `store.pending_events[world_id]`, counted in
the response's `"pending"`. **Flush trigger:** every mutating route (`stop`, `pause`, `revoke`)
attempts to drain every world it touches, oldest-queued-part-first, before computing its own
response — this is "the next mutating call that touches a world", not a background job, and is
the one resolved trigger for retrying whatever an earlier failed/hung call left behind. A part is
removed from the queue only once `append` actually confirms it committed (the stamped record is
already in `store.events` by then), so a part already written is never re-sent, and a part that
keeps failing stays pending indefinitely rather than being dropped.

**Within one drain of one world**, parts are attempted strictly in queue order, one at a time
(issue #46 retires round 7's parallel-dispatch-within-a-world design entirely: it produced
duplicate writes, out-of-order commits, and a world stuck forever behind a hung writer). A part
whose attempt does not settle within `part_deadline_s` is a **hang**: the drain for this call
stops right there (that part, and everything queued behind it, stays pending); the underlying
attempt is never cancelled (Python threads cannot be cancelled) — it keeps running in the
background, and whichever thread eventually observes it settle removes the part from the queue
(and releases the world's drain lock) at that point, so a later call naturally finds the world
free again once the writer genuinely answers. A part whose attempt **fails fast** (raises well
within its deadline) does not block a different part still waiting behind it in the same drain:
that different part is tried next, and the failed one is left pending, not retried again this
call — **except** when nothing else is left to try in this drain (the failed part is the sole
remaining candidate), in which case it is retried in place, a small bounded number of times,
since there is nothing more useful this call could otherwise do with its remaining budget. This
is what lets `world.paused` — enqueued and drained on its own, ahead of anything else (see next
section) — recover from a single fast failure and still land first, without letting an
ever-failing writer spin a whole call's budget on one permanently broken part when others are
waiting.

### `world.paused` goes first (FR-WLD-07, NFR-07: pause confirms within 2 s)

The pause route enqueues `world.paused` at the **front** of `store.worlds[world_id]`'s queue —
ahead of anything already pending there, and ahead of this same call's own `policy.changed`
parts, which are not even built yet — and drains it in its own phase before computing the
stop-all-style plan at all. Only once that phase returns (settled, given up, or handed off to a
hang) does pause build and enqueue its `policy.changed` parts and drain again. This is what keeps
`world.paused` reaching the writer within 2 s even against a slow writer working through an
unrelated backlog, and keeps it landing first in `store.events[world_id]` even when its own first
attempt fails fast and has to be retried (see "Pending writes and flush" above).

### `POST /worlds/{world_id}/pause` — FR-HIL-07 ("Pause all stops the agents too", PRD 10.4)

- Same membership, 404 and 403 as stop-all above.
- Request body: `{"channel": <common.schema.json#/$defs/channel> | null}` — **typed to the
  schema's own enum**, so a value outside it is a 422 from request validation, before the handler
  runs (nothing changes, nothing is emitted). The body is otherwise unused:
  `world.paused.data.channel` comes from `principal.channel` (the caller's own resolved session
  channel), never from the body — round-6/ST-3a-2, issue #38 item 5: a caller must not be able to
  claim a confirmation channel it is not actually on.
- 200 or 202 (same rule as stop-all): under the world's lock, when `store.worlds[world_id].paused`
  is **not already True**, sets it True and builds one `world.paused` part
  (`data == {"reason": "pause_all", "channel": principal.channel}`, `authz: null` since
  `world.paused` is `side_effect: false`, `vis: "all"`) — enqueued at the front, per above. When
  already True, no new part is built (a true idempotent repeat). **This dedupe is keyed on the
  flag alone, checked under the lock, never on whether this call's own Stop-all step lowered
  anything** (round-4 security finding, biggest: a Pause-all right after a Stop-all, or a world
  with no L2/L3 policies at all, both read `stopped == 0` yet are real, first-time pauses that a
  `stopped`-keyed dedupe would silently drop). Runs the same owned-policy plan-and-apply as
  stop-all afterward (same fail-safe, no-silent-repair, per-target-world `vis`, and
  pending-on-failure rules). `"paused"` is `true` whenever the request reaches this point at all,
  regardless of whether `world.paused`'s own part is still pending.
- Response body:
  `{"stopped": <int>, "already_l1": <int>, "paused": true, "pending": <int>}` (`"pending"` defined
  exactly as in stop-all's response, counting the `world.paused` part when one was built this
  call too).

### `POST /policies/{policy_id}/revoke` — FR-HIL-07, PI-13

- 404 when `policy_id` is not in `store.policies`, **or** when
  `principal.user_id != store.policies[policy_id]["owner"]` — exactly the same status and body
  either way, so a non-owner cannot tell "no such policy" from "not yours" (round-1 security
  finding). The store is unchanged in both cases.
- 200 otherwise, **never 500 even when the writer is down**. When `policy_id` maps to a world
  (`store.policy_worlds.get(policy_id)` is not `None`), that world's mutate lock is acquired
  first: under it, one history entry `{"by": owner, "at": now, "change": "revoked", "level": "L1"}`
  is always appended (even if already L1 — revoke is a distinct, explicit act, not a bulk
  operation, so it never skips the way stop-all's `already_l1` case does), `level = "L1"`,
  `changed_by` set, and one `policy.changed` part (`data.change == "revoked"`) is built and
  enqueued to the tail of the mapped world's queue — so draining that world (which always starts
  from the current head) flushes whatever was already pending there, oldest first, before this
  new part is ever attempted. A policy with no world mapping (policies live at org level) is
  still revoked (history entry, L1); its mutation is taken under a lock **scoped to that one
  policy id** instead (round-6/ST-3a-2, issue #38 item 5: a policy-id lock, not a world lock, so
  two concurrent revokes of the same unmapped policy cannot race and drop one's history entry,
  and an unrelated Stop-all/Pause-all against a different world is never blocked by it); no world
  lock is acquired and nothing is enqueued (there is no world to write to).
- Response 200 body: `{"policy_id": policy_id, "level": "L1"}` — revoke is a single-policy,
  single-event act, so its response carries no `"pending"` field of its own.

### `policy.changed` visibility (EV-13)

`vis` is `events.policy_vis(policy, world_districts)`: the intersection of the policy's own
`scope.districts` with the **target** world's own district ids (never the request world's, when
they differ — round-4 finding), in that world's own key order, when the intersection is
non-empty; `"all"` when the scope is missing/malformed, the target world has no layout, or the
intersection is empty. A non-string or otherwise unhashable entry in `scope.districts` (round-6/
ST-3a-2, issue #38 item 1: `[["D1"], 123, None, {"x": 1}, "D9"]`, mixed among a real district id)
is filtered out before any membership test runs, so it never raises `TypeError` and never aborts
the kill switch — every well-formed policy in the same call still reaches L1 and gets its own
event.

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

  **Hidden-district filter (round-5 security finding, biggest — runs in addition to, never instead
  of, the visibility filter above; owner exempt, same as the visibility filter):** even after the
  visibility filter above keeps an event, it is dropped anyway — entirely, not with fields nulled —
  for any non-owner principal whenever a district-shaped value (matching
  `common.schema.json#/$defs/district_id`'s pattern, `^D[0-9]{1,4}$`) naming a district outside
  `principal.districts` appears anywhere in it: the event's own `district` field; `target` or
  `actor` when either is district-shaped; or any district-id-shaped string found while walking
  `data` recursively — a leaf **value** at any depth, or a dict **key** at any depth (round-5
  finding 6, "data dict keys," below). This supersedes round 3/4's "null the offending field, keep
  the event" treatment for the *hidden* case (SEC-07 "never receive hidden names or counts" reads
  as: not even a stripped-down record of the event itself may reach a scoped viewer) — the
  `target`/`actor`/`district` rows of the allowlist table below now only ever apply to a value that
  is *not* hidden (either not district-shaped at all, or naming a district `principal.districts`
  does include), since the hidden case never reaches the allowlisting step at all. An event naming
  no district anywhere, or naming only districts `principal` can see, is unaffected.

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
  | `ts`, `type`, `level`, `severity`, `credits`, `summary`, `authz` | unchanged from the stored event | unchanged from the stored event — `authz` in particular is copied through exactly as stored, never redacted itself |
  | `target`, `actor` | unchanged from the stored event | the stored value unchanged — by the time an event reaches this table it has already passed the hidden-district filter above, so a district-shaped `target`/`actor` here is guaranteed to name a district `principal.districts` includes (or not be district-shaped at all); a hidden one means the whole event was already dropped, never reaching this row (round-5: supersedes round 4's "null the field, keep the event"). A **non-string** `target`/`actor` is never district-shaped by definition, so it always passes through unchanged too. |
  | `district` | the stored event's real `district` | the stored `district` unchanged — same reasoning as `target`/`actor` above: a hidden `district` value means the whole event was already dropped by the hidden-district filter, so this row only ever sees `None` or a visible district id (round-5: supersedes round 3's "null the field, keep the event") |
  | `cause` | unchanged | the *view-local id* (same `f"v{seq}"` scheme, using the **causing event's own view `seq` in this same response**) of the causing event, when that event survived filtering; `null` when it names an event that was dropped or never existed (round-1 rule, now expressed via the view-local id instead of the real one, since the real one is never returned to a scoped principal) — unaffected by round 5: a `cause` names an *event*, not a district, so it is never itself a reason to drop the whole event, only to be remapped or nulled |
  | `vis` | unchanged | `"all"` stays `"all"` (nothing to filter); **a district list is filtered to its intersection with `principal.districts`** before being returned — never the stored event's full, unfiltered list (round-4 security finding: the event is kept whenever `vis` intersects `principal.districts` at all, but the *full* stored list can name additional districts the caller cannot see at all, and returning it unfiltered tells that caller "someone else can see this too, and here is exactly which other district" — a leak of a hidden district's *id* through a field that was previously assumed safe because "it is never itself sensitive." The kept intersection is always non-empty, since the event would not have survived filtering otherwise, so this never turns a visible event invisible) |
  | `data` | unchanged | rebuilt by walking the stored `data` value **recursively** (round-4: a dict's values, and every item of a list, at any depth; round-5 extends this to dict **keys** too, and adds a depth guard — see "Depth and dict keys" below) applying, to every string leaf found: (1) if the key it is stored under is `"message_ref"` (at any depth, not only top-level), always `null` for a non-owner, regardless of shape, per the `trace.archive_ref` rule below; (2) else if it matches the ULID pattern, the same cause-style remap — the view-local id of the event it names, if that event survived filtering, else `null` (for example `policy.applied.data.instruction_id`, or the same value nested inside a list or a sub-object); (3) else if it matches the district_id pattern (`^D[0-9]{1,4}$`) — by round 5 this case can only be reached for a *visible* district (a hidden one already dropped the whole event via the hidden-district filter above) — left unchanged; every other value (a non-string, or a string matching none of the above) is left exactly as stored. **Dict keys** get the equivalent treatment (round-5 finding 6): a district-id-shaped key naming a hidden district already dropped the whole event (same filter, keys included); a district-id-shaped key naming a visible district is left unchanged; a ULID-shaped key naming an event that survived filtering is renamed to that event's own view-local id (its value redacted normally); a ULID-shaped key naming a hidden or unknown event is dropped — the key *and* its value are removed from the rebuilt dict, since a JSON key cannot itself be set to `null` the way a value can (ambiguity 17). The dict/list *shape* of `data` is otherwise always preserved; only leaf string values, and the specific keys named above, are ever rewritten or removed. |
  | `trace` | unchanged | **rebuilt by allowlisting exactly `event.schema.json#/$defs/trace`'s seven keys** (`model_role`, `profile`, `tokens_in`, `tokens_out`, `tool`, `latency_ms`, `archive_ref`), each copied through **exactly as stored**, with `archive_ref` always `null` (round-3 finding: `archive_ref`/`message_ref` name a position in the run-wide raw archive — PRD 13.2 — a counter unrelated to district visibility that would let a scoped viewer infer how many raw records exist between two events it can see, so it is stripped outright rather than filtered by visibility; round-6 finding, issue #38 item 5: a stored `trace` copied forward wholesale can carry an extra, schema-invalid key — the stored value should never have one, `trace.additionalProperties: false`, but a scoped view must not merely trust that — so anything outside those seven keys is dropped rather than copied) |

  A kept event's real store `id` and `trace.archive_ref` therefore never appear anywhere in a
  non-owner response — not as that event's own `id`/`archive_ref`, not inside another event's
  `cause` or a ULID-shaped `data` field, not inside `data.message_ref`. The owner's response
  never contains a view-local id at all.

### Malformed events (round-3 finding, code/qa/security)

An event in `store.events[world_id]` may itself be malformed — missing `id` (or `id` not a
string), a `cause` that is not a string or `None` (for example a list), or missing any other key
this schema requires. Such an event is dropped before the visibility filter runs, for **every**
principal including the owner. It never raises (never a 500) and never blocks its well-formed
siblings in the same response.

### Depth and dict keys (round-5 finding, qa/security)

`data` is not schema-bounded in depth; a payload nested arbitrarily deep (this ticket's own test
uses 500 levels) must never turn into a 500. **The owner's response never walks `data` at all** —
the stored value is copied forward unchanged into the response, however deeply nested. **The
non-owner (scoped) redaction walk fails closed past a bounded depth: the event is dropped
entirely** — the same treatment a malformed event already gets. Dict **keys** within `data` are
walked and redacted using the same rules as dict **values** at the same position (round-5 finding
6): see the `data` row of the allowlist table above for the exact per-key treatment.

### `GET /worlds/{world_id}` — FR-HIL-09, SEC-07 (layout/summary)

- 404 per the membership check above.
- 200: `{"world_id": world_id, "districts": [...], "has_hidden_districts": bool}`.
  `districts` lists only the districts `principal` may see (same visibility rule as above, using
  `store.worlds[world_id].districts`' keys as the district ids): each visible entry is
  `{"id": did, "name": ..., "summary": ...}`. A **hidden district is left out of the list
  entirely** — not included with its name blanked or its id kept — because no hidden district's
  id or name may appear anywhere in the response JSON; `has_hidden_districts` is the only trace
  that fog exists. **Fail closed on a malformed record:** a district entry that is `None` or
  otherwise missing a usable `.name`/`.summary` is treated as hidden — never a 500, whoever is
  asking.

## Role resolution this ticket assumes (not itself a new route)

No `/auth` or `/whoami` route exists yet; the builder's real role and world-membership resolver
(reading `orgs/{org}/users/{uid}`, team assignments, and per-world membership, PRD 15.3) is later
work. This ticket only pins the `Principal` shape the routes above consume once resolved, and
every test constructs `Principal` directly and installs it with
`app.dependency_overrides[get_current_principal] = lambda: principal`.

## What a contract change would still need (needs the harness or an ADR — see issues #29 and #38
item 6; not attempted by this ticket)

- **Summary free text still names hidden work**, and **world-level `vis: "all"` totals**
  (`world.planned.data.unit_count`, `world.completed.data.deliverable_count`/`credits_used`) still
  count it, even once every structured field (`district`, `target`, `actor`, `data`, `trace`) is
  correctly redacted or dropped by the rules above. Fixing this needs either the harness to write
  per-scope summaries/totals itself (PRD 15.3), or a contract change to `event.schema.json`/the
  `events/data/*` schemas so a redacted view can strip or recompute them — spark-456/tilo#29 tracks
  the contract side (EV-13). Out of reach for a ticket that may only touch `services/api/tests/`
  and `services/api/src/tilo_api/` without a contract change.

## Ambiguities resolved

4. **Hidden districts on `GET /worlds/{world_id}`**: left out of the list entirely rather than
   included with blanked fields; a malformed district record is folded into the same "hidden"
   treatment.
6. **World membership source**: `Principal.world_id` is a single value (one world per principal).
8. **View-local id scheme**: `f"v{seq}"`, that event's own dense position in *this response*.
11. **Malformed-event ownership**: dropped from *every* principal's response, owner included.
15. **Owner's response for depth-500 `data`**: returned unmodified, since the owner's response
    path never inspects `data`'s shape at all.
17. **ULID-shaped `data` key naming a hidden or unknown event**: dropped (key and value both
    removed), since a JSON key cannot be `null`.
16, 22. **The exact per-part write deadline and its config key/file** (`config/dispatch.yaml`'s
    `dispatch.part_write_deadline_s`): this ticket's own implementation choice; only the
    injectable seam (`get_part_write_deadline_s`) and "meaningfully smaller than 5s" are pinned.
19. **The unmapped-revoke lock's scope**: one lock per policy id (`Store.dispatch_state`), not a
    world lock (there is no world) and not one lock for every unmapped policy.
20. **The stable id's storage**: alongside the part, as the part's own `id` field (issue #46 makes
    this simpler than an earlier "id carried alongside, never inside" design — `id` is now itself
    a required, schema-legitimate part field, EV-10's own idempotency key, not a dispatch-only
    bookkeeping value).
21. **Which call gets to retry a stuck head**: whichever mutating call next touches that world and
    finds the world's drain lock free — never a background job, and never contingent on being
    handed a different writer object than the one already presumed stuck.
23. **The stable id's exact minting point**: once when the part is enqueued
    (`events.new_part_id`, called from the route handler at plan-build time); which layer mints it
    is this ticket's own implementation choice.
