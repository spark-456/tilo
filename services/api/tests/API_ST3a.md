# `tilo_api` — public shape ticket ST-3a pins

Ticket ST-3a (session ST). Requirements FR-HIL-07 (kill switches), FR-HIL-09 and SEC-07 (roles
and redaction). Invariant PI-13 of `docs/security/p4-policy-invariants.md` applies. This file is
the contract the builder implements exactly; the tests in this directory import only what is
listed here. Nothing here is business logic — it is the shape tests hold the builder to, the same
convention `packages/policy/tests/API.md` uses for P4-01. `tilo_policy` (package `packages/policy`,
built in parallel by ticket P4-01) is used read-only for one integration test below; it is not a
workspace member yet, so importing it fails until P4-01 lands — that failure is expected and
correct for this ticket.

Real sign-in, Firestore, and `packages/policy`'s own internals are out of scope: this ticket adds
route handlers over an **injected, in-memory store** (no Firestore, no network, PRD 15.3's
document layout is the shape to keep in mind for a later ticket, not implemented here) and an
**injected principal** (no real auth; "Auth is a test double" per the ticket brief).

## `tilo_api.deps` (new module; does not exist yet — every test here fails on this import until
the builder adds it)

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

Role = Literal["owner", "team_lead", "approver", "viewer"]


@dataclass(frozen=True)
class Principal:
    """The test double for auth (real sign-in is a later ticket). One instance per request,
    supplied by overriding get_current_principal in tests via app.dependency_overrides."""

    user_id: str  # common.schema.json#/$defs/user_id
    role: Role
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
class Store:
    """In-memory injected state (no Firestore this ticket). One instance built fresh per test
    and supplied by overriding get_store; a route handler mutates it in place, the same object
    the test holds, so a test can inspect the result without a second GET."""

    worlds: dict[str, "WorldRecord"] = field(default_factory=dict)
    policies: dict[str, dict] = field(
        default_factory=dict
    )  # policy_id -> policy.schema.json record (mutated in place: level, changed_by, history)
    policy_worlds: dict[str, str] = field(
        default_factory=dict
    )  # policy_id -> world_id whose event stream receives that policy's policy.changed events (policy.schema.json itself carries no world_id, PRD 15.3 keeps policies at the org level; this map is this ticket's own bookkeeping, not a new contract field)
    events: dict[str, list[dict]] = field(
        default_factory=dict
    )  # world_id -> event.schema.json records, append-only, oldest first (seq strictly increasing, EV-10)


@dataclass
class WorldRecord:
    owner: str  # common.schema.json#/$defs/user_id
    owner_channels: tuple[
        str, ...
    ]  # common.schema.json#/$defs/channel values; the owner's enabled channels for kill-switch confirmations
    districts: dict[str, "DistrictRecord"]  # district_id -> DistrictRecord, this world's full layout (owner's-eye view)


@dataclass
class DistrictRecord:
    name: str
    summary: str


def get_current_principal() -> Principal:
    """Raises NotImplementedError in production until real sign-in lands; every test overrides
    this via app.dependency_overrides[get_current_principal]."""
    raise NotImplementedError


def get_store() -> Store:
    """Raises NotImplementedError in production until Firestore wiring lands; every test
    overrides this via app.dependency_overrides[get_store]."""
    raise NotImplementedError
```

## Routes (new; `tilo_api.app` currently has only `GET /healthz`)

All four take `principal: Principal = Depends(get_current_principal)` and
`store: Store = Depends(get_store)`. `now()` is read internally by the handler (`datetime.now`
wrapped as an RFC 3339 string, `common.schema.json#/$defs/timestamp` shape); no clock is
injected — the 5 s budget below is measured as wall-clock time around the test's own call, "the
injected clock or wall time, whichever is honest" resolved toward wall time since a fake clock
would not prove the ≤ 5 s requirement about anything real.

### `POST /worlds/{world_id}/autopilot/stop` — FR-HIL-07, PI-13

- 404 when `world_id` is not in `store.worlds`.
- 403 when `principal.role != "owner"` or `principal.user_id != store.worlds[world_id].owner`;
  the store is unchanged.
- 200 otherwise: for every `policy_id -> policy` in `store.policies` whose `policy["owner"] ==`
  the world's owner: **skip policies already at `"L1"`** (idempotency, decided below); for every
  other one, append one history entry
  `{"by": owner, "at": now, "change": "stop_all", "level": "L1"}`, set `policy["level"] = "L1"`
  and `policy["changed_by"] = {"by": owner, "at": now}`, and append one `policy.changed` event
  (`data.change == "stop_all"`, `data.level == "L1"`, `authz == {"by": "person", "ref": owner,
  "at": now}`) to `store.events[store.policy_worlds[policy_id]]` — exactly one `policy.changed`
  part per policy actually changed this call (PI-13's "one `policy.changed` per policy" reading
  applied to a single call, not to the policy's whole lifetime).
- **Idempotency (decided, not in the ticket text verbatim):** a policy already at `"L1"` gets no
  new history entry and no event on a second call — appending a same-level entry would grow
  history forever on repeated Stop-alls and add nothing PI-13 needs (PI-13 needs the level to
  reach L1 and stay covered-by-nothing; a no-op repeat already satisfies that). `"stopped"` in the
  response counts only policies actually changed this call.
- Response 200 body:
  `{"stopped": <int>, "already_l1": <int>, "confirmations": [{"channel": c} for c in store.worlds[world_id].owner_channels]}`
  — one confirmation part per the owner's enabled channel (`common.schema.json#/$defs/channel`
  values), returned in the body rather than sent anywhere real (no network, no paid calls,
  EFF-01). Channel list assumed: `("web", "whatsapp", "email")` (PRD 10.2's "all enabled
  channels", `mobile_web` treated as the same surface as `web` for this ticket's confirmation
  purposes — logged in `docs/open-questions.md`).
- Performance: 200 policies owned by the world's owner complete within 5 s wall-clock.

### `POST /worlds/{world_id}/pause` — FR-HIL-07 ("Pause all stops the agents too", PRD 10.4)

- Same 404/403 as above.
- 200: runs the same "every owner policy to L1" step as stop-all (same idempotency rule, same
  `policy.changed` events), **plus** appends exactly one `world.paused` event to
  `store.events[world_id]` with `data == {"reason": "pause_all", "channel": <request body's
  channel>}`, `authz: null` (`world.paused` is `side_effect: false`, registry `events/registry.yaml`),
  `vis: "all"`. Request body: `{"channel": <common.schema.json#/$defs/channel> | null}` (the
  channel Pause-all came from, per `world.paused.schema.json`'s description; default `null` when
  omitted, e.g. a web button that does not carry a "channel" the way a WhatsApp keyword does —
  `null` is reserved for the kill-switch case per the schema description, so a request with no
  body still names its own channel where known; tests always pass one explicitly to avoid this
  ambiguity).
- Response 200 body: `{"stopped": <int>, "already_l1": <int>, "paused": true}`.

### `POST /policies/{policy_id}/revoke` — FR-HIL-07, PI-13

- 404 when `policy_id` is not in `store.policies`.
- 403 when `principal.role != "owner"` or `principal.user_id != store.policies[policy_id]["owner"]`
  (a Team Lead, Approver or Viewer always gets 403, PRD 10.1 "Team Lead proposes only"); the
  store is unchanged — no history entry, no event, even when the policy is already at L1.
- 200 otherwise: appends one history entry
  `{"by": owner, "at": now, "change": "revoked", "level": "L1"}` (always appended, even if already
  L1 — revoke is a distinct, explicit act unlike the bulk Stop-all, so no idempotency skip here),
  sets `level = "L1"`, `changed_by = {"by": owner, "at": now}`, and appends one `policy.changed`
  event (`data.change == "revoked"`, `data.level == "L1"`) to
  `store.events[store.policy_worlds[policy_id]]`.
- Response 200 body: `{"policy_id": policy_id, "level": "L1"}`.

### `GET /worlds/{world_id}/events` — FR-HIL-09, SEC-07

- 404 when `world_id` is not in `store.worlds`.
- 200: `{"events": [...]}`, `store.events[world_id]` filtered to the events `principal` may see,
  in original order:
  - kept when `event["vis"] == "all"`;
  - kept when `principal.role == "owner"` and `principal.user_id == store.worlds[world_id].owner`
    (the owner sees everything regardless of `vis`, PRD 10.1);
  - kept when `event["vis"]` is a list and it intersects `principal.districts`;
  - dropped otherwise — not redacted-in-place, removed from the list entirely, so nothing about
    a hidden event (its `summary`, `data`, or any other field) appears in the response.

### `GET /worlds/{world_id}` — FR-HIL-09, SEC-07 (layout/summary)

- 404 when `world_id` is not in `store.worlds`.
- 200: `{"world_id": world_id, "districts": [...], "has_hidden_districts": bool}`.
  `districts` lists only the districts `principal` may see (same visibility rule as above, using
  `store.worlds[world_id].districts`' keys as the district ids): each visible entry is
  `{"id": did, "name": ..., "summary": ...}`. A **hidden district is left out of the list
  entirely** — not included with its name blanked or its id kept — because the acceptance test
  below requires that no hidden district's id *or* name appear anywhere in the response JSON;
  `has_hidden_districts` is the only trace that fog exists (a bare boolean, no id, no name, no
  count, matching PRD 10.1 "hidden districts show fog with no names or counts").

## Role resolution this ticket assumes (not itself a new route)

No `/auth` or `/whoami` route exists yet; the builder's real role resolver (reading
`orgs/{org}/users/{uid}`, team assignments, and per-world membership, PRD 15.3) is later work.
This ticket only pins the `Principal` shape the routes above consume once resolved, and every
test constructs `Principal` directly and installs it with
`app.dependency_overrides[get_current_principal] = lambda: principal`.

## Ambiguities resolved (logged to `docs/open-questions.md`)

1. **Idempotency of Stop-all** (PI-13 says "one `policy.changed` per policy" without saying per
   call or per lifetime): resolved as per call — a policy already at L1 is skipped on a repeat
   call, emitting no duplicate history entry or event.
2. **Confirmation channel list**: `("web", "whatsapp", "email")`, taking the ticket's own example;
   `mobile_web` folded into `web` for this ticket's confirmation-count purposes.
3. **Policy-to-world routing for `policy.changed` events**: `policy.schema.json` carries no
   `world_id` (PRD 15.3 keeps policies at the org level); `Store.policy_worlds` is this ticket's
   own bookkeeping to know which world's event stream receives a policy's `policy.changed` parts,
   not a new contract field.
4. **Hidden districts on `GET /worlds/{world_id}`**: left out of the list entirely (only a
   `has_hidden_districts` boolean survives) rather than included with blanked fields, since the
   acceptance test requires no hidden id or name anywhere in the response.
5. **Pause-all's `channel` when the caller does not say**: defaults to `null` (the schema's
   kill-switch sentinel); tests always pass an explicit channel to keep this untested edge out of
   scope.
