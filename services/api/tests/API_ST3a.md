# `tilo_api` — public shape ticket FR-HIL-09/SEC-07 pins (roles and redaction)

Requirements FR-HIL-09 and SEC-07 (roles and redaction). Invariant PI-18 of
`docs/security/p4-policy-invariants.md` applies. This file is the contract the builder implements
exactly; the tests in this directory import only what is listed here. Nothing here is business
logic — it is the shape tests hold the builder to, the same convention `packages/policy/tests/API.md`
uses for P4-01.

Real sign-in, Firestore, and the harness's own internals are out of scope: this ticket adds route
handlers over an **injected, in-memory store** (no Firestore, no network; PRD 15.3's document
layout is the shape to keep in mind for a later ticket, not implemented here) and an **injected
principal** (no real auth; "Auth is a test double" per the ticket brief).

This file is split out of the original ST-3a spec (session ST, which also covered FR-HIL-07 kill
switches on the same in-memory `Store`/`Principal` shapes, PR #39). Only the sections the roles and
redaction routes need are kept here; the kill-switch route specs (`stop`, `pause`, `revoke`,
pending-write flush, per-world locking/ordering) and their own round-by-round review history live
with FR-HIL-07 instead. Round numbers below refer to that same shared review history (rounds 1-7),
kept only where a round changed something the redaction routes or `tilo_api.deps` still rely on.

## `tilo_api.deps` (module)

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
    # "that world does not exist" from "you are not in it" (round 1
    # security finding).
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
    districts: dict[
        str, "DistrictRecord | None"
    ]  # district_id -> DistrictRecord, this world's full layout (owner's-eye view). A test may
    # store None or another malformed value under a key to prove the read routes fail closed
    # (treat it as hidden) rather than raising.
    run_id: str  # common.schema.json#/$defs/run_id: the world's current run, the harness's own
    # record. tilo-api reads this to know which run an event belongs to; it never
    # invents one (PI-18 round-1 finding: run_id = f"r_{world_id}" was tilo-api's own
    # guess, not the harness's actual run).


@dataclass
class Store:
    """In-memory injected state (no Firestore this ticket). One instance built fresh per test
    and supplied by overriding get_store; a route handler mutates it in place, the same object
    the test holds, so a test can inspect the result without a second GET."""

    worlds: dict[str, WorldRecord] = field(default_factory=dict)
    events: dict[str, list[dict]] = field(
        default_factory=dict
    )  # world_id -> event.schema.json records, append-only, oldest first (seq strictly increasing,
    # EV-10). Only EventWriter.append appends here; a route handler never does.


class EventWriter(Protocol):
    """The single writer of events (PRD 15.3). tilo-api builds an event *part* -- every
    event.schema.json field except v, id, seq, ts, world_id, run_id and trace -- and hands it
    here. A production implementation talks to the harness process; this ticket only pins the
    call shape. The redaction routes below never call it -- they are read-only -- but the shared
    test scaffolding (services/api/tests/conftest.py) wires one up for every test regardless, the
    same in-memory `_api_lib.FakeEventWriter` the FR-HIL-07 kill-switch routes exercise for real."""

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

Both routes below take `principal: Principal = Depends(get_current_principal)` and
`store: Store = Depends(get_store)`. Neither emits an event, so neither takes an `EventWriter`.

### World membership check (applies first, on every route below that takes a `world_id` path
parameter)

Before anything else: if `principal.world_id != world_id`, respond exactly as for
`world_id not in store.worlds` — same status (404), same body, so a caller cannot distinguish "no
such world" from "you are not a member of it". Only once `principal.world_id == world_id` does
the handler read `store.worlds.get(world_id)` and 404 if that lookup itself misses (a member
whose own world record is missing is an inconsistent store, treated the same way — still 404, no
new status code invented for it).

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
principal including the owner (resolved default, this ticket may only write
`services/api/tests`: the same "cannot be safely read, cannot be honestly shown to anyone" rule
round 2 already applies to a malformed `WorldRecord.districts` entry). It never raises (never a
500) and never blocks its well-formed siblings in the same response.

### Depth and dict keys (round-5 finding, qa/security — "What changed since round 4," findings 5-6)

`data` is not schema-bounded in depth; a payload nested arbitrarily deep (this ticket's own test
uses 500 levels) must never turn into a 500. **The owner's response never walks `data` at all** —
the stored value is copied forward unchanged into the response, exactly like every other
unredacted owner field, so depth cannot 500 the owner's path and the owner still receives the
event, `data` included, however deeply nested (ambiguity 15). **The non-owner (scoped) redaction
walk fails closed past a bounded depth: the event is dropped entirely** — the same treatment a
malformed event already gets, on the reasoning that `data` too deep to safely walk cannot be
honestly redacted, and cannot therefore be honestly shown to a scoped viewer either. The exact
depth the scoped walk's own bound sits at is this ticket's own implementation choice (ambiguity
16-adjacent; not pinned beyond "500 levels must not 500 and must be dropped for a non-owner").
Dict **keys** within `data` are walked and redacted using the same rules as dict **values** at the
same position (round-5 finding 6): see the `data` row of the allowlist table above for the exact
per-key treatment (district-id key: hidden drops the whole event, visible is left unchanged;
ULID key: visible is renamed to the named event's view-local id, hidden/unknown drops the key).

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
  the contract side (EV-13: an event with `district` set should not be allowed `vis: "all"`, which
  is what lets `district.created`/`agent.spawned`'s own fixtures name a district in free text on an
  otherwise-global event). Both are out of reach for a ticket that may only touch
  `services/api/tests/` and `services/api/src/tilo_api/` without a contract change.

## Ambiguities resolved (kept out of `docs/open-questions.md`: this ticket may only touch
`services/api/tests/`; logged here and in the test-writer's report instead)

4. **Hidden districts on `GET /worlds/{world_id}`** (unchanged from round 1): left out of the
   list entirely rather than included with blanked fields. New this round: a malformed district
   record is folded into the same "hidden" treatment, for the same no-leak reason, and additionally
   because a value tilo-api cannot safely read cannot be honestly shown to anyone, owner included.
6. **World membership source**: `Principal.world_id` is a single value (one world per principal)
   because nothing in scope for this ticket needs a principal bound to more than one world at a
   time; a person who owns or belongs to several worlds in the product's real data model is later
   work (the real sign-in/session resolver, PRD 15.3), out of scope for this in-memory test double.
8. **View-local id scheme.** A scoped (non-owner) response's event `id` is `f"v{seq}"`, where
   `seq` is that same event's own dense position in *this response*: simple, deterministic given
   the store's contents and the caller's own visibility, trivially distinct from a real ULID
   (which never starts with `"v"`), and derivable from data the route already computes for `seq`
   itself rather than needing a second id-minting scheme. A `cause` naming a visible event is
   remapped the same way, using that *other* event's own view `seq`. The owner's response never
   uses this scheme — see "Owner vs. everyone else" under `GET /worlds/{world_id}/events` above.
11. **Malformed-event ownership.** A malformed event is dropped from *every* principal's response,
    owner included (not only scoped ones) — see "Malformed events" above; this mirrors round 2's
    own resolution for a malformed `WorldRecord.districts` entry (ambiguity 4) rather than
    introducing a second rule for events.
15. **Owner's response for depth-500 `data`.** The owner's view returns the stored event, `data`
    included, unmodified — never redacted, never dropped — regardless of nesting depth, because the
    owner's response path never recurses over `data` at all ("What changed since round 4," finding
    5). This was a real choice, not the only defensible one (an alternative would drop *every*
    viewer's copy of an absurdly deep event, owner included, for uniformity) — resolved toward
    "owner sees everything" (PRD 10.1) since deep-but-well-formed `data` is not itself a malformed
    record the way a missing `id` or a non-string `cause` is (ambiguity 11), and the owner's code
    path has no reason to ever inspect `data`'s shape at all.
17. **ULID-shaped `data` key naming a hidden or unknown event (finding 6).** Dropped (key and value
    both removed from the rebuilt dict) rather than kept with some placeholder key, since a JSON key
    cannot be null and inventing a synthetic placeholder key (e.g. `"_hidden"`) would itself be new
    information not present in the original shape and could collide with a real key already in the
    same dict.
