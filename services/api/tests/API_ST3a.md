# `tilo_api` — public shape ticket ST-3a pins (round 2, post code/security/qa review)

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
- 200 otherwise. **Validate first, then apply (no half-apply):** build the full list of
  `(policy_id, policy)` pairs in `store.policies` whose `policy.get("owner") == store.worlds[world_id].owner`
  before mutating anything; skip a policy whose `policy.get("level") == "L0"` (already below L1,
  left untouched, not counted) or `== "L1"` (idempotent repeat, `already_l1` += 1, no history
  entry, no event); every other policy — whatever its `level` reads as, including missing or not
  one of `L0`..`L3` (fail safe: not proven to be at L1 already, so it is lowered) — gets exactly
  one history entry `{"by": owner, "at": now, "change": "stop_all", "level": "L1"}` appended to
  `policy["history"]` (a missing or non-list `history` is replaced with a fresh one-entry list,
  never raises), `policy["level"] = "L1"`, `policy["changed_by"] = {"by": owner, "at": now}`, and
  exactly one `policy.changed` part handed to the writer for the world named by
  `store.policy_worlds.get(policy_id, world_id)` (a policy with no entry in `policy_worlds` still
  gets an event, routed to the world Stop-all was pressed in, never a `KeyError`). The part's
  `data` is `{"policy_id": policy_id, "change": "stop_all", "level": "L1"}`, `authz` is
  `{"by": "person", "ref": owner, "at": now}`, and `vis` is the policy's own `scope.districts`
  list when non-empty (missing or malformed `scope`/`scope.districts` treated as empty, i.e.
  unrestricted), else `"all"` (EV-13; see "`policy.changed` visibility" below). No request ever
  returns 500, whatever shape the matched policies are in, and every policy actually changed this
  call is reflected — none are skipped because another one in the same call was malformed.
- Response 200 body:
  `{"stopped": <int>, "already_l1": <int>, "confirmations": [{"channel": c} for c in store.worlds[world_id].owner_channels]}`.
  `"stopped"` counts only policies actually changed this call (including malformed ones that were
  still lowered). Channel list assumed: `("web", "whatsapp", "email")` (PRD 10.2's "all enabled
  channels", `mobile_web` treated as the same surface as `web` for this ticket's confirmation
  purposes — logged as an ambiguity below, unchanged from round 1).
- Performance: 200 policies owned by the world's owner complete within 5 s wall-clock (PI-18's
  per-world O(1) counter, not round 1's O(n) rescan per event, is what makes this hold at n=200
  without the budget being a coincidence of hardware).

### `POST /worlds/{world_id}/pause` — FR-HIL-07 ("Pause all stops the agents too", PRD 10.4)

- Same membership and 404/403 as stop-all above.
- Request body: `{"channel": <common.schema.json#/$defs/channel> | null}`
  (`web` | `mobile_web` | `whatsapp` | `email` | `null`; **typed to the schema's own enum**, so a
  value outside it is a 422 from request validation, before the handler runs — nothing in the
  store changes and nothing is emitted. Default `null` when the field is omitted; tests always
  pass one explicitly for the 200 paths to keep that default's own edge case out of scope, per
  the ambiguity logged below).
- 200: runs the same "every owner policy to L1, validate first" step as stop-all (same fail-safe
  and no-half-apply rules, same `policy.changed` parts including the per-policy `vis` rule),
  **plus** hands the writer exactly one `world.paused` part for `world_id` itself (never
  `policy_worlds`) with `data == {"reason": "pause_all", "channel": <body.channel>}`,
  `authz: null` (`world.paused` is `side_effect: false`, registry `events/registry.yaml`),
  `vis: "all"`.
- Response 200 body: `{"stopped": <int>, "already_l1": <int>, "paused": true}`.

### `POST /policies/{policy_id}/revoke` — FR-HIL-07, PI-13

- 404 when `policy_id` is not in `store.policies`, **or** when
  `principal.user_id != store.policies[policy_id]["owner"]` (whatever `principal.role` is) —
  exactly the same status and body either way, so a non-owner cannot tell "no such policy" from
  "not yours" (round-1 security finding; this collapses what round 1 answered with 403 for a
  known policy into the same 404 an unknown policy id gets). The store is unchanged in both
  cases.
- 200 otherwise: appends one history entry
  `{"by": owner, "at": now, "change": "revoked", "level": "L1"}` (always appended, even if already
  L1 — revoke is a distinct, explicit act unlike the bulk Stop-all, so no idempotency skip here;
  a missing or non-list `history` is replaced the same fail-safe way stop-all does), sets
  `level = "L1"`, `changed_by = {"by": owner, "at": now}`, and hands the writer one `policy.changed`
  part (`data.change == "revoked"`, `data.level == "L1"`, `vis` by the same scope.districts rule
  as stop-all) for the policy's mapped world, `store.policy_worlds[policy_id]`. A policy with no
  world mapping (policies live at org level, PRD 15.3) is still revoked (history entry, L1), but
  no event is handed to any world: revoke has no world of its own, and an event is never filed
  under a world that does not exist (PRD 9.4 honesty). The history entry is the audit record.
- Response 200 body: `{"policy_id": policy_id, "level": "L1"}`.

### `GET /worlds/{world_id}/events` — FR-HIL-09, SEC-07

- 404 per the membership check above.
- 200: `{"events": [...]}`, `store.events.get(world_id, [])` filtered to the events `principal`
  may see, in original order:
  - kept when `event["vis"] == "all"`;
  - kept when `principal.role == "owner"` and `principal.user_id == store.worlds[world_id].owner`
    (the owner sees everything regardless of `vis`, PRD 10.1);
  - kept when `event["vis"]` is a list and it intersects `principal.districts`;
  - dropped otherwise — not redacted-in-place, removed from the list entirely, so nothing about
    a hidden event (its `summary`, `data`, or any other field) appears in the response.

  Two redaction rules new this round (PRD 15.3 `views/{scope}/events/{seq}` is a distinct
  sequence per view, not the full stream's own numbering):
  - **`seq` is the view's own dense sequence:** the returned events are renumbered `1, 2, 3, ...`
    in the order they survive filtering (the underlying store `seq` is never returned), so a
    scoped viewer cannot count the gaps to learn how many events were hidden between two it can
    see. Every other field of a kept event is returned unchanged (its real `id`, `ts`, and so on).
  - **A dangling `cause` is nulled:** if a kept event's `cause` names an event that filtering
    dropped (or that never existed in the stream), the returned copy's `cause` is `null` instead
    of that id — a viewer must never learn the id of an event it cannot fetch.

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

## `policy.changed` visibility (EV-13; security review round-1 finding)

Every `policy.changed` part this ticket's three routes build (stop-all, pause, revoke) sets
`vis` from the policy's own `scope.districts` at the moment of change: non-empty → that list
(so only viewers who can see every one of those districts — in practice, viewers whose
`principal.districts` intersects the list, plus the owner — receive the event); empty, missing,
or malformed `scope`/`scope.districts` → `"all"` (unrestricted policy, unrestricted event). The
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

1. **Idempotency of Stop-all** (unchanged from round 1): resolved as per call — a policy already
   at L1 is skipped on a repeat call, emitting no duplicate history entry or event. A policy
   whose `level` cannot be read as one of `L0`..`L3` (missing or malformed) is treated as *not*
   proven to be at L1 already, so it is lowered and counted as `stopped`, not `already_l1` — the
   fail-safe reading PI-13 needs ("the level reaches L1 and stays covered by nothing") over the
   alternative of leaving an unreadable record untouched.
2. **Confirmation channel list** (unchanged from round 1): `("web", "whatsapp", "email")`, taking
   the ticket's own example; `mobile_web` folded into `web` for this ticket's confirmation-count
   purposes.
3. **Policy-to-world routing for `policy.changed` events** (unchanged from round 1):
   `policy.schema.json` carries no `world_id`; `Store.policy_worlds` is this ticket's own
   bookkeeping. New this round: a policy absent from that map is not an error — stop-all and
   pause route its event to the world the request was made against; revoke (no world_id in its
   own path) routes it to a synthetic world named after the policy id, purely so revoke can never
   raise; no test depends on that synthetic value beyond "no 500".
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
