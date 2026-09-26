# `tilo_api` — public shape ticket ST-3a pins (round 8, redone per issue #46's binding S0 decision
# after round 7/ST-3a-3's own writer design -- an 8-worker pool with an `_in_flight` map keyed by
# `id(part)`, and a retry gate keyed on writer-*instance* identity -- failed code/security/qa
# review a second time; see "What changed since round 7 (ST-3a-3) -- issue #46" below)

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

## What changed since round 4 (why the sections below moved again)

Round 4's own fixes above are unchanged and still pinned. Round 4 itself then failed code,
security and qa review on:

1. **Scoped views must drop a hidden-district event, never null one of its fields (security,
   biggest).** Round 4's redaction nulled `district`, `target`, `actor` and any district-shaped
   leaf inside `data` when they named a district outside `principal.districts`, but still *kept*
   the event — the round-3/round-4 "allowlist, don't copy" fix. That is no longer good enough: a
   scoped viewer who receives an event at all — even one with every district-shaped field blanked
   — still learns *something happened* in a district it cannot see (a count, a `summary`, a `ts`,
   an `authz`), which is exactly what SEC-07 "scoped users never receive hidden names **or
   counts**" rules out. **A kept event, for anyone but the owner, is now dropped entirely — not
   returned with fields nulled — whenever any of the following names a district outside
   `principal.districts`:** the event's own `district` field, `target` or `actor` when either is
   district-shaped (matches `district_id`'s pattern), or any district-id-shaped string appearing
   anywhere inside `data` — a leaf value at any depth, **or a dict key at any depth** (see finding
   6 below) — regardless of what `vis` says. This check runs *in addition to*, not instead of, the
   existing `vis`-based filter: an event is kept for a non-owner only when it passes **both** — its
   `vis` makes it visible at all, **and** nothing district-shaped inside it names a district outside
   `principal.districts`. An event that names no district anywhere (or names only districts the
   caller can see) is unaffected and still kept, redacted exactly as round 4 already pinned (view
   `seq`/`id`, `cause` remap, `vis` intersection, `message_ref`/`archive_ref` nulling, ULID remap).
   The owner is unaffected (owner sees everything, PRD 10.1; this whole check is skipped for the
   owner). Every "target/actor/district field is nulled" wording elsewhere in this document
   (unchanged text below, kept for the parts that still apply to a *visible* district-shaped value)
   is superseded for the *hidden* case: nulling was round 3/4's mechanism, dropping the whole event
   is round 5's.
2. **The kill switch must never hold a world's lock across writer I/O, and every writer attempt
   gets a deadline (qa biggest, security).** Round 4 did move writer calls onto a thread pool
   (`_write_parts`'s `ThreadPoolExecutor.map`), but that call is still made **while the route's own
   `_locked(touched)` context is held** — `pool.map` blocks the calling thread until every
   submitted writer call returns (or raises), so a writer that never returns at all (the harness
   process wedged, not merely slow or down) hangs the request forever, and a second call against
   the *same* world — even one with nothing left to change — cannot acquire that world's lock until
   the stuck call's writer phase eventually gives up, which round 4 never bounds either. Fixed:
   **the level/history/`changed_by`/`paused`-flag mutation happens under the touched worlds' locks,
   with no I/O of any kind inside that block; the lock(s) are released before any `writer.append`
   call is attempted**, for both the flush-pending step and the newly-built-parts step. Every
   individual `writer.append` attempt additionally carries its own bounded deadline (the exact
   value is this ticket's own implementation detail, not pinned here beyond "small enough that even
   a full 200-policy Stop-all's worth of missed deadlines cannot itself blow the 5 s budget," per
   the open question logged below); an attempt that does not return within its deadline is treated
   exactly like a raising `append` call — the part is left/queued in `store.pending_events` and
   counted in `"pending"` — **without the request waiting for that attempt to actually finish**. A
   writer call that eventually does complete after its deadline was already given up on is not
   itself an error (the response has already moved on); nothing in this ticket requires cancelling
   the underlying attempt, only not waiting on it. Consequences pinned by this round's tests:
   Stop-all and Pause-all both return well within 5 s even against a writer whose `append` never
   returns at all; a second Stop-all issued against the *same* world while the first is still stuck
   in its (already lock-released) writer phase also returns within 5 s, because by the time the
   second call runs, the level change is already durably applied and there is nothing left for it
   to do under the lock; and a Stop-all issued by a *different* owner against a *different* world
   that merely happens to be a target of the first owner's policy mapping is not held up either,
   for the same reason — that world's lock was released before the first call's writer phase began.
3. **Writes to one world must be sequential and ordered; only different worlds run in parallel
   (code biggest, qa).** Round 4's `_write_parts` submitted every part for a call — across every
   touched world at once — to one shared thread pool with no ordering guarantee at all, so the
   order parts actually land in `store.events` (and therefore the `seq` the writer assigns them)
   could diverge from the order they were built or queued, *within a single world*. Two
   consequences this round's tests pin directly: (a) `store.pending_events[w]`'s parts, which are
   already invariantly oldest-first (round 3), must be flushed to the writer **in that same
   oldest-first order**, and only once flushing is under way may this call's own newly-built parts
   for that world follow, also in their own build order — a **100**-part pending backlog for one
   world must land in `store.events[w]` in exactly its queued order; (b) within **the same call**,
   Pause-all's `policy.changed` parts (built first, one per lowered policy) must land before its
   own `world.paused` part (built last) in `store.events[world_id]`, never interleaved out of that
   order by concurrent completion. Parallel dispatch *within* one world's writer calls is still
   permitted for latency (finding 2's per-part deadline still needs every part to actually be
   attempted, not queued one full deadline apart), **but the order parts are committed to
   `store.events` must match the order they were queued/built for that world, regardless of which
   attempt happens to finish first on the wire** — i.e. an implementation may fire a world's writer
   calls concurrently, but must commit their results to the store in queue order (an in-order
   buffer/barrier), never in raw completion order. Parallelism *across different worlds* is
   unaffected and still required (finding 2, and the unchanged round-4 cross-world latency test
   below).
4. **Revoke must flush its own target world's whole pending backlog first, oldest first, under
   that world's lock — not only its own part (code/qa/security, supersedes round-4 ambiguity 12).**
   Round 4 deliberately scoped revoke's flush duty to "only its own policy's part," reasoning that
   clearing a whole world's backlog was a bulk (`stop`/`pause`-shaped) responsibility a
   single-policy revoke should not inherit. Review round 4 rejected that: a world whose owner never
   happens to call `stop` or `pause` again (for example one where autopilot was never turned back
   on) could carry a stuck backlog indefinitely even though every one of its owner's revokes keeps
   touching that same world, each one skipping past the very backlog sitting right there — the
   "next mutating call that touches a world" flush trigger (ambiguity 9) is defined at the level of
   *any* mutating route touching a world, not just `stop`/`pause`, and revoke's own text singling
   itself out was the bug, not a feature. **Ambiguity 12 (round 4) is superseded:** revoke now
   flushes `store.pending_events.get(mapped_world_id, [])` in full, oldest first, exactly like
   `stop`/`pause` flush every world they touch, before building and writing its own new part; the
   flush and the policy's own level/history mutation both happen with `mapped_world_id`'s lock
   held (the level mutation itself gains lock protection it never had before — round 4's revoke
   mutated `store.policies` with no lock at all — so a concurrent `stop`/`pause`/`revoke` against
   the same world can never interleave with revoke's own flush-then-write sequence and
   double-write a stale pending part). A policy with no `policy_worlds` mapping still has no world
   to flush or lock (ambiguity 7, unchanged): revoke of such a policy touches no lock and no
   pending queue at all.
5. **`data` nested far past any realistic depth must never turn into a 500, for anyone (qa,
   security).** Round 4's recursive `_redact_value`/`_data_hides_district`-style walk has no depth
   guard at all; a `data` payload nested a few hundred levels deep (500 is this round's own test
   depth) risks `RecursionError` once the walk's own stack frames stack on top of whatever the
   ASGI/FastAPI/pydantic call chain already used, which FastAPI turns into an unhandled-exception
   500 — a crash triggered by a single event's shape, taking the whole response down with it,
   including every well-formed sibling event in the same call. **Resolved default (this ticket may
   only touch `services/api/tests`, so this is pinned here rather than `docs/open-questions.md`):
   the scoped (non-owner) redaction walk fails closed past a bounded depth and the event carrying
   that `data` is dropped entirely — the same "cannot be safely/honestly processed, so it is not
   shown to that viewer" treatment already given to a malformed event.** The owner's own response
   never walks `data` at all — `_owner_event_view` (and any replacement for it) copies the stored
   `data` value forward unchanged, so there is nothing for the owner's path to recurse over and
   depth cannot 500 it; the owner therefore still receives the deeply nested event, `data`
   byte-for-byte as stored, same as any other field. (The exact bound the scoped walk fails closed
   at is this ticket's own implementation detail — this round's test only requires that 500 levels
   of nesting never 500s and is dropped for a non-owner; it does not pin the bound's precise value.)
6. **A `data` dict key that is itself a district id or an event ULID must get the same treatment a
   value in that position would (security).** Round 4's redaction walk (`_redact_value` and
   friends) only ever inspected dict *values*; a key was copied into the rebuilt dict verbatim,
   unexamined — so `data: {"D9": "..."}` or `data: {<hidden event's real ulid>: "..."}` put a
   hidden district id or a real store event id directly into the JSON response as a **key**,
   identical in effect to it appearing as a value, which finding 1 and round 3/4's own ULID-remap
   rule already forbid. **A district-id-shaped key is treated exactly like a district-id leaf value
   under finding 1 above: if it names a district outside `principal.districts`, the whole event is
   dropped** (a hidden district id is a hidden district id, whether Python/JSON happens to store it
   as a dict key or a dict value — both render as the same string in the response body). **A
   ULID-shaped key naming an event is treated like a ULID-shaped *value* naming one (the existing
   `cause`/data-value remap rule) with one necessary difference: a JSON object key cannot be set to
   `null`, so where a hidden/unknown-event value would be nulled, a hidden/unknown-event key is
   instead dropped — that key and its value are removed from the rebuilt dict entirely — and where
   a visible event's value would be remapped to that event's view-local id, a visible event's key is
   likewise renamed to that view-local id, its value redacted the same as any other value at that
   position.** A district-id-shaped key that names a *visible* district, or any other string key, is
   left exactly as stored. This is a value-level transformation within an already-kept event (it
   never triggers a whole-event drop by itself for the ULID case — only a *district-id* key or value
   does, per finding 1); it composes with finding 1's whole-event-drop check, which still runs
   first, over keys and values alike, before any surviving event's `data` is rebuilt.

## What changed since round 5 (ST-3a-2)

Round 5 passed nothing: all three reviewers failed it (issue #38, PR #39 stuck at the 5-round cap
before this extra fix round was opened). Round 5's own fixes above are unchanged and still pinned.
What round 5's implementation still gets wrong, in the issue's own priority order:

1. **A malformed stored scope aborts the kill switch instead of being skipped (security, blocking).**
   `events.py`'s `policy_vis` does `intersection = [d for d in districts if d in world_districts]`;
   when `scope.districts` holds a non-string entry -- `[["D1"]]` is the issue's own example, but any
   unhashable value (a list, a dict) has the same effect -- `d in world_districts` (a dict) raises
   `TypeError: unhashable type`, not a caught, skippable condition. Because `policy_vis` is called
   from *inside* `_stop_all_owner_policies`'s apply loop, which itself runs inside
   `_stop_all_and_dispatch`'s `with _locked(touched):` block -- **after** that block has already
   popped every touched world's pending backlog into a local `work` dict (`work[w] =
   store.pending_events.pop(w, [])`) -- the raise propagates straight out of the locked block, out of
   the route, to a bare 500: every policy after the malformed one in iteration order never reaches
   `L1`, and the popped-but-not-yet-dispatched `work` (which can include an unrelated, already-durably-
   -pending part such as a queued `world.paused`) is discarded, not restored -- silent data loss on
   top of the 500. Fixed: a non-string entry in `scope.districts` is skipped (filtered out of the
   intersection, exactly like a string entry that names a foreign district is already dropped by the
   intersection today) rather than raising; `vis` for every targeted policy is computed once, in the
   plan-building phase, before any policy is mutated and before any world's pending backlog is popped;
   and, as a defence in depth for any other exception this ticket has not anticipated, if anything
   still raises after pending has been popped for the locked worlds, every popped part is put back
   into `store.pending_events` before the exception is allowed to propagate (so a request that somehow
   still 500s never does so by losing data first) -- resolved default per the ticket brief, this
   ticket may only touch `services/api/tests`.
2. **A write whose attempt misses its deadline can still land twice (code/qa, biggest).**
   `_write_world` gives each part's writer call up to `_MAX_PART_DEADLINE_S`; a call that has not
   settled by then is queued pending and the loop moves on -- but the underlying `writer.append` call
   is never cancelled and keeps running on its own thread. If it later succeeds for real (the writer
   was merely slow that once, not actually down), nothing tells `store.pending_events` to drop the
   part: it stays queued, and the next mutating call that flushes this world re-sends the *same* part
   to the writer, which appends it *again* -- the same part lands in `store.events[w]` twice, out of
   its original build order relative to whatever else that later call wrote. Resolved default (not an
   idempotency key on the part -- `_api_lib.py`'s `_ALLOWED_PART_KEYS`/`assert_part_carries_no_stamped_fields`
   forbids exactly that, and this ticket's tests keep enforcing it): the writer for one world is now a
   single ordered channel where a part whose attempt has missed its deadline stays "at the head" --
   no later part for that same world is committed ahead of it, and once its own attempt does
   eventually settle (successfully or not), it is removed from `pending_events` before anything else
   for that world is considered flushed. A part is written at most once across every call and every
   flush this ticket's routes make, whatever timing the underlying writer calls land in.
3. **Unbounded thread growth against a hung writer (qa).** `_write_world` builds a brand-new
   `ThreadPoolExecutor(max_workers=len(parts))` on every call and calls `pool.shutdown(wait=False,
   cancel_futures=True)` once its own loop finishes -- `cancel_futures` only cancels futures that have
   not started yet; one already blocked inside a hung `writer.append` keeps its worker thread alive
   indefinitely, and because a fresh pool is built per call, every call against a hung writer leaks
   roughly one thread per part, unboundedly, across calls. Fixed: a bounded, per-world executor (a
   small constant number of worker threads per world, not one per part per call) that is reused
   rather than rebuilt on every call; a part that cannot be submitted because the executor is
   saturated is queued pending, never dropped.
4. **Size (code, mechanical only -- no test below).** `routes.py` (487 lines, ~630 with `deps.py` and
   `events.py`) is split into a redaction module (the `GET` routes' allowlisting: `_is_malformed_event`,
   `_hides_district`, `_data_hides_district`, `_event_hides_district`, `_redact_data`,
   `_owner_event_view`, `_scoped_event_view`, `_district_fields`, `_safe_districts`, `_visible`, and the
   two `GET` route handlers) and a dispatch module (the locking, pending/flush and writer-call
   machinery: `_lock_for`, `_locked`, `_pend`, `_settled`/its replacement, `_write_world`, `_dispatch`,
   `_touched_worlds`, `_stop_all_owner_policies`, `_stop_all_and_dispatch`, and the `stop`/`pause`/
   `revoke` route handlers) -- a purely mechanical move (same functions, same behaviour, new file
   boundaries), so no test in this directory pins it beyond continuing to import `tilo_api.app`/
   `tilo_api.deps` exactly as every existing test already does; whichever module ends up owning each
   route, the app's route table is unchanged.
5. **Smaller items (safety, security):**
   - The owner's `GET /worlds/{world_id}/events` still risks a 500 at extreme `data` nesting (~3000
     levels, stdlib `json`'s own default recursion limit) even though the owner's path never *walks*
     `data` -- `JSONResponse`'s underlying `json.dumps` still recurses to serialize it. Out of this
     round's own test list (500-deep is already pinned, round 5, for the scoped path; the owner path's
     much-deeper failure point is noted here, not newly tested, since the ticket's priority list marks
     it a "smaller item" behind 1-3 above).
   - `trace` is still copied into a scoped view via `dict(trace_value)` (every key the stored event's
     `trace` happens to carry) with only `archive_ref` overwritten afterward -- an extra key the
     stored event's `trace` should never have carried (schema-invalid, `trace.additionalProperties:
     false`) still reaches a scoped viewer verbatim. **Fixed: a scoped view's `trace` is rebuilt by
     allowlisting exactly `event.schema.json#/$defs/trace`'s seven keys (`model_role`, `profile`,
     `tokens_in`, `tokens_out`, `tool`, `latency_ms`, `archive_ref`) -- anything else present on the
     stored value is dropped, never copied forward.**
   - `PauseRequest.channel` is still taken directly from the request body and written unchanged into
     `world.paused.data.channel` -- a caller can claim any enabled-looking channel it likes, whether or
     not it is the channel the confirmation is actually happening on. **Fixed:** `Principal` gains one
     new field, `channel: Channel = "web"` (`common.schema.json#/$defs/channel`: `"web" | "mobile_web"
     | "whatsapp" | "email"`) -- the session channel the (still test-double) sign-in layer resolved for
     this request, exactly the same shape `Principal.world_id`/`Principal.districts` are already
     resolved the same way. `world.paused.data.channel` is now `principal.channel`, never
     `body.channel`; the request body's own `channel` field is accepted (still 422 outside the enum)
     but is no longer read by the pause route at all -- ambiguity 18 below.
   - Revoke of a policy with **no** `policy_worlds` mapping (the one branch this ticket's own text
     already calls out as "no lock is acquired and nothing is flushed... there is no world to flush or
     lock") mutates `store.policies[policy_id]` (history, level, `changed_by`) with no synchronization
     at all -- unlike every other mutator in this ticket, which is at least serialized by some lock.
     Two concurrent revokes of the same unmapped policy can each read a stale `history` and silently
     clobber one another's new entry. **Fixed: revoke of an unmapped policy now takes a lock scoped to
     that one policy id** (not a world lock -- there is no world to key one by) before reading or
     mutating `history`/`level`/`changed_by`, so two concurrent revokes of the same unmapped policy
     never race, and (being a policy-scoped lock, not a world lock) a concurrent Stop-all against an
     unrelated world is never blocked by it.
   - A second Stop-all issued while an earlier call's write for the same world is still in flight can
     report `"pending": 0` even though that earlier write has not actually landed yet (a race in how
     "pending" is counted, not in the level change itself, which is unaffected). Noted here as a
     "smaller item" per the issue; not pinned by a dedicated test this round (the existing "second call
     is not blocked" tests already constrain the level-change and blocking behaviour this counts
     alongside).
   - The busy-poll `_settled` helper burns CPU while waiting out a part's deadline. An implementation
     detail with no externally observable contract this ticket's tests can pin (the 5s budget tests
     already constrain wall-clock behaviour regardless of how the wait is implemented).
   - A 200k-event `GET` takes ~4.7s. Out of scope for this round's own priority list (item 6 in the
     issue, "needs the harness or a contract change," is explicitly out of reach for a
     `services/api/tests`-only ticket).
6. **Needs the harness or a contract change (issue #29, out of reach for this ticket):** summary free
   text still names hidden work; world-level `vis: "all"` totals still count it;
   per-scope views must eventually be written by the harness itself, not derived per-request the way
   this ticket's `GET` routes still do. No test below touches these.

### Ambiguities resolved this round (round 6 / ST-3a-2)

18. **`PauseRequest.channel`'s new role.** The request body keeps its `channel` field (still validated
    against the schema's enum, still 422 outside it) so a caller's request shape does not change, but
    it is no longer consulted for `world.paused.data.channel` at all -- purely a legacy/compatibility
    field this round leaves in place rather than removing, since removing a field is a wire-shape
    change this ticket has no reason to force on every caller in the same round it fixes the trust
    boundary. `Principal.channel` (default `"web"`, mirroring how `Principal.districts` defaults to
    `()`) is the one and only source for the event's own `data.channel` from this round on.
19. **The per-policy lock for an unmapped revoke is not a world lock.** `_lock_for`'s existing registry
    is keyed by world id; an unmapped policy has no world id to key one by. This round's fix uses a
    lock keyed by the policy id itself (a disjoint namespace from world locks, e.g. a `"policy:"`-
    prefixed key sharing the same lock registry, or an entirely separate one) -- deliberately *not*
    the requesting world's own lock, so this fix cannot introduce a new way for an unrelated Stop-all
    to block on a revoke of an unrelated, unmapped policy.

## What changed since round 6 (ST-3a-2) -- ST-3a-3

Round 6 (immediately above) passed items 1, 4 and 5 of issue #38 but its own writer design failed
all three reviewers again (issue #38's last comment, PR #39 stuck at the round cap): `dispatch.py`'s
`_WorldChannel` -- an 8-worker pool, a per-call pending snapshot, and an `_in_flight` map keyed by
`id(part)` -- reproduced, under real concurrency:

1. **Duplicate writes** (2-3 writes in 4-7 of 20 trials): a call that snapshotted
   `store.pending_events` before an in-flight attempt had actually landed could resend a part
   another call had already committed and cleared.
2. **Out-of-build-order commits**: a part whose attempt missed its own deadline was skipped
   (`continue`), so later parts committed first, both within one call and across concurrent calls
   on the same world.
3. **A world getting permanently stuck**: after 8 writer calls that never return, the bounded pool
   is exhausted, and every already-submitted (but not yet started) future is still bound to the
   *writer instance closed over when it was submitted* -- a healthy writer swapped in afterward
   gets zero calls, and `world.paused` never reaches it even though the response already says
   `"paused": true`.
4. **`id(part)` reuse**: once a committed part's dict is garbage-collected, a later, unrelated part
   can be allocated at the same address; a dedupe keyed on `id()` then treats the new part as
   already-seen and drops it unwritten (3 of 20 trials).

**Resolved design (this ticket, ST-3a-3, may only touch `services/api/tests`; a later
`feat/FR-HIL-07-*` round implements it):**

- **One consumer per world**, owning an ordered queue that lives on the `Store` instance itself --
  never a module-level dict keyed by `world_id` alone. Two `Store` instances that happen to share a
  `world_id` string (two tests, or two tenants) must never share queue, lock or dedupe state (see
  the store-scope test below).
- **A mutating route only enqueues**, under the touched world's lock (the existing per-world lock
  registry, unchanged), then waits up to the call's shared budget for its own part(s) to settle --
  the lock is still released before any writer I/O, unchanged from round 4/5.
- **The head of a world's queue is never passed until it settles.** No later part for that world is
  ever committed to `store.events` ahead of it, whatever order the underlying writer calls finish
  on the wire (unchanged invariant, now held by construction rather than by a "skip a timed-out
  head" fallback -- round 6's `continue` violated exactly this).
- **A committed part is never re-sent.** Dedupe is keyed on a stable id carried *alongside* the
  part in the world's own queue record (assigned once, when the part is enqueued -- ambiguity 20
  below), never on `id(part)`, and that id is never added as a field of the part
  `EventWriter.append` itself receives -- `_api_lib.assert_part_carries_no_stamped_fields` still
  applies unchanged to every part a test inspects via `writer.calls`.
- **A hung writer attempt frees its worker.** Once an attempt's own bounded deadline passes without
  it returning, the world's single consumer stops waiting on it and becomes available to retry the
  same (still-head) part, using whichever writer the *most recently arrived* mutating call for that
  world supplied. Parts behind the head are never attempted early just because the head is stuck
  (see above); the backlog is unblocked by the head's own eventual settlement -- a real success, or
  a fresh attempt against a newly-healthy writer -- never by skipping it. This is what recovers
  **without a restart**: swapping in a healthy writer (or letting a truly-hung one eventually
  return) is enough for the same long-lived, per-world consumer to drain everything queued behind
  it, in order.
- **`world.paused` is enqueued ahead of every audit part for its world** -- this call's own
  `policy.changed` parts *and* anything already sitting in that world's pending backlog from an
  earlier call -- the moment Pause-all decides to build it (supersedes round 5's "Order within a
  world" finding 3, annotated above, which put it last). This is what makes FR-WLD-07/NFR-07's
  "pause reflected within 2s" hold even against a slow writer working through a large, unrelated
  backlog: the confirmation that autonomy actually stopped must never queue behind the audit trail
  of *why*.

### Ambiguities resolved this round (ST-3a-3)

20. **The stable part id's exact form.** Left as this ticket's own implementation choice (a
    monotonic per-`Store` counter, a uuid4, a ULID) -- this round's tests only require that the id
    is *not* `id(part)`, is carried outside the part shape `EventWriter.append` receives, and
    survives a part being copied into a fresh dict with identical content (the "persisted queue"
    test below), not that it take any particular form.
21. **Whether "the next mutating call that touches a world" (ambiguity 9, unchanged) is still the
    resolved flush/retry trigger, now that a per-world consumer is long-lived.** Yes, unchanged:
    nothing in ST-3a-3's own priority list (issue #38's writer-soundness findings) asks for a
    background retry loop, and FR-HIL-07 does not require one either. A world nobody ever issues
    another `stop`/`pause`/`revoke` against after a writer failure simply keeps its backlog queued,
    same as every round before this one -- the *consumer* is long-lived (one per world, not rebuilt
    per call), but it only gets a fresh chance to retry a stuck head when a call supplies one,
    exactly as the pending/flush trigger has always worked.

## What changed since round 7 (ST-3a-3) -- issue #46 (S0's decision, binding, round 8)

Round 7 (immediately above) fixed issue #38's duplicate writes, out-of-order commits and
permanently-stuck worlds by keying dedupe on a stable id carried *alongside* the part and by
retrying a stuck head only when handed a **different** writer object than the one already presumed
stuck (`head.attempt_writer is writer`). Issue #46 retires that instance-identity heuristic itself:
it made round 7 permanently stuck against the far more common case of a shared writer object that
merely *stops hanging* (the same long-lived harness connection recovering, or production's
`get_event_writer()` handing back the very same client on every call) -- exactly the scenario
`test_FR_HIL_07_pause_recovers_via_the_same_writer_object_once_it_stops_hanging` pins. S0's own
comment on issue #46 is binding:

> The idempotency key already exists: every event carries a required ULID `id`
> (contracts/event.schema.json), and `EventWriter.append` already refuses a reused id (EV-10). Use
> it: (1) Dispatcher (ST, services/api): build the full event, including `id`, once when the part
> is enqueued. Every retry re-sends that same event. Dedupe the queue on `id`, not on content. At
> most one append in flight per world. Read the part deadline from config, not a constant tuned to
> the tests. (2) Harness writer (SH, services/harness/writer.py): if `append` gets an event whose
> `id` is already committed and whose content is byte-identical to the committed event, return the
> committed event (idempotent success) instead of raising. Same id with different content stays
> EventRejected. (3) The api-side `EventWriter` protocol passes the pre-built event (with `id`)
> instead of a bare part.

Concretely, this round changes:

1. **The full event, `id` included, is built once at enqueue time.** `tilo-api` no longer builds a
   bare part (round 1-7's `type`/`actor`/.../`data` dict with no identity of its own); it builds
   that same shape *plus a fresh `id` (a ULID)*, at the moment the part is enqueued onto a world's
   queue, and hands that exact same dict to `EventWriter.append` on every retry -- the same object
   (or an equivalent copy, e.g. after a persisted-queue reload, ambiguity 20, unchanged) every
   time, never a freshly-`uuid4()`'d one per attempt. `seq`, `ts` and `run_id` remain writer-only,
   stamped on first commit, exactly as every round before this one.
2. **Dedupe moves from content, and from writer-instance identity, onto that `id`.** Round 7's
   `_content_key` (JSON-serialize-and-hash the part) and its `head.attempt_writer is writer` retry
   gate are both retired. `EventWriter.append` itself is now the one and only place idempotency is
   decided (EV-10): the same `id` with byte-identical content already committed is a no-op success
   (the already-committed record is returned); the same `id` with *different* content is
   `EventRejected` (new, above) -- a real conflict, never a silent overwrite. This is strictly more
   permissive about *retrying* (any writer object, the same one or a different one, may answer a
   retry) and strictly less permissive about *content drift* under one id than round 7 was.
3. **At most one `append` in flight per world, at any instant.** Round 7 allowed "parallel dispatch
   within one world's writer calls... for latency," committed in an order-preserving buffer. Round
   8 drops that complexity along with the bugs it produced (issue #38's duplicate writes and
   out-of-order commits): exactly one `append` call is ever outstanding for a given world at a
   time, in queue order, `world.paused` still jumping to the front ahead of any audit part
   (unchanged from ST-3a-3). A part whose attempt does not settle within its own deadline is left
   at the head, pending, for *this* call; the world's long-lived consumer gets another chance to
   attempt that same head -- against whatever writer the *next* mutating call supplies, the same
   instance or a different one, it no longer matters -- on a later call, never by spawning a second
   concurrent attempt for it within the same call (ambiguity 21's "the consumer only gets a fresh
   chance when a call supplies one" stays unchanged; what changes is that a *same-instance* retry
   is now just as eligible as a different-instance one).
4. **The per-part write deadline is config-backed, not a module constant.** Round 7's
   `_PART_DEADLINE_S = 0.3` (a value ambiguity 16 explicitly left as "this ticket's own
   implementation choice... not pinned... beyond 'meaningfully smaller than 5s'") is replaced by
   `deps.get_part_write_deadline_s()` (new, above) -- injectable exactly like `get_store`/
   `get_event_writer`, so production reads a real config value and every test can prove the route
   reads it fresh rather than capturing a constant once at import time. Ambiguity 16's own
   resolution (the exact number is still not pinned) is otherwise unchanged.
5. **`_ALLOWED_PART_KEYS` gains `id`.** `_api_lib.py`'s allowlist of keys the event tilo-api hands
   to `EventWriter.append` may carry now includes `id` (required, ULID-shaped) alongside the
   existing part-content keys and `trace`; `seq`/`ts`/`run_id` remain the only fields still
   forbidden on the caller's side (`_STAMPED_ONLY_KEYS`, now three entries instead of four).
   `assert_part_carries_no_stamped_fields` (unchanged name) now also asserts `id`'s presence and
   shape, not just the writer-only fields' absence.
6. **`WorldRecord.paused` must never be observed `True` without its own `world.paused` event
   existing somewhere in the store (pending or committed) -- fail-safe extended to a corrupted
   `pending_events` entry.** Round 5's fail-safe rule for a malformed *policy* record (never abort
   the kill switch, never half-apply) extends explicitly to a corrupted `store.pending_events`
   entry for the *pause* flow specifically: a non-list value under `store.pending_events[world_id]`
   (for example `None`, standing in for some other write having left it in a bad shape) must never
   raise past the route, and -- because `world.paused` is set under the same lock that decides to
   enqueue its own event -- must never leave `paused` flipped `True` with no corresponding event
   anywhere (PRD 9.4 honesty: nothing animates without a recorded event, applied to the durable
   flag itself, not only to the on-screen animation).
7. **A fast (non-hanging) failure with call budget remaining is retried within the same call.**
   Round 4-7 treated any raising `append` -- fast or slow -- as an immediate "queue it pending, move
   on" signal. Round 8 distinguishes a *fast* failure (the attempt concluded, raising, well inside
   its own per-part deadline) from a *hang* (the deadline itself elapsed): a fast failure, with
   meaningful call budget still left, is retried right away, within the same call -- `EventWriter.
   append` being idempotent-by-id (finding 2 above) makes an immediate retry safe -- rather than
   being parked pending on its very first failure. This does not change how a *hang* is handled
   (finding 3: still left pending for this call, retried only on a later one).

Round 7's `test_FR_HIL_07_nine_hung_writer_calls_recover_via_a_swapped_in_healthy_writer` is
removed (not merely superseded): it proved recovery specifically *by swapping in a different
writer object*, the exact signal this round retires. Its scenario is covered by two round-8 tests
instead: one using a single shared writer object throughout (never swapped), and one using a fresh
writer object on every single call (the opposite extreme) against a persistently hung harness, to
pin the thread-bound and single-in-flight properties independently of recovery.

### Ambiguities resolved this round (round 8)

22. **The exact config key/file for the part-write deadline.** Left as this ticket's own
    implementation choice, same resolution style as ambiguity 16: `deps.get_part_write_deadline_s`
    is the pinned, testable seam; which `config/*.yaml` file and key production reads through it is
    not pinned here.
23. **The stable event `id`'s exact minting point.** "Once when the part is enqueued" (S0's own
    wording) is pinned; whether that happens inside the route handler itself or one layer down in
    the dispatch module is this ticket's own implementation choice, same resolution style as
    ambiguity 20's "any stable form is fine."

## `tilo_api.deps` (module; `Principal.channel` is new this round -- every test that constructs one
via `make_principal(channel=...)` fails on that keyword until the builder adds the field)

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
    channel: str = "web"  # common.schema.json#/$defs/channel ("web" | "mobile_web" | "whatsapp" |
    # "email"): the session channel the (still test-double) sign-in layer resolved for this
    # request -- new this round (ST-3a-2, issue #38 item 5). The pause route's world.paused
    # event now takes its data.channel from here, never from the request body, so a caller
    # cannot claim a confirmation channel it is not actually on.
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


class EventRejected(Exception):
    """Issue #46 (S0's decision, binding, round 8): raised by EventWriter.append when a caller
    resends an `id` that is already committed for that world_id with *different* content than
    what was committed under that id. Same id, same content -> idempotent success (the
    already-committed record is returned, nothing new is appended, EV-10). Same id, different
    content -> this exception; tilo-api must let a genuinely differing resend surface as a real
    conflict, never silently overwrite the committed record and never silently drop the new one."""


class EventWriter(Protocol):
    """The single writer of events (PRD 15.3). Round 8 (issue #46) replaces round 7's *bare part*
    with the *full, pre-built event*: tilo-api now builds every event.schema.json field except
    `seq`, `ts`, `run_id` and `trace` (trace defaults to all-null) -- crucially now **including
    its own `id`, a ULID, built once when the part is enqueued and resent unchanged on every
    retry** -- and hands the whole thing here. `append` dedupes on that `id` (EV-10), never on
    raw content-equality (round 7's `_content_key`, retired) and never on whether this call
    happens to be handed the same writer *object* as an earlier, still-outstanding attempt (round
    7's `head.attempt_writer is writer` check, retired -- see "What changed since round 7" below).
    A production implementation talks to the harness process (services/harness/writer.py, a
    small SH ticket under this same requirement ID implements the identical idempotent-by-id
    contract there); this ticket only pins the call shape. Every test supplies its own in-memory
    stand-in (`_api_lib.FakeEventWriter`), which stamps `seq`/`ts`/`run_id` itself (from
    Store.worlds[world_id].run_id and a per-world counter, O(1) per call) on first commit only,
    returns the already-committed record unchanged on an idempotent-by-id retry, and raises
    `EventRejected` when the same id shows up with different content -- and that records every
    call so a test can assert the event tilo-api handed over carried its own stable `id` but none
    of the three still-writer-only fields."""

    def append(self, world_id: str, event: dict) -> dict:
        """event keys: id, type, actor, target, level, district, item, severity, credits,
        summary, cause, vis, authz, data (any key the caller has no value for is set to that
        field's schema-honest default: null, "info", 0, or "all" for vis; `id` is always present,
        a ULID, and is the sole idempotency key). Returns the fully stamped event.schema.json
        record that is (or already was) appended to store.events[world_id]; raises
        `EventRejected` on a same-id/different-content conflict."""
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
    """Round 8 (issue #46, S0's decision point 1: "Read the part deadline from config, not a
    constant tuned to the tests"). Production reads this from `config/` (the exact file/key is
    this ticket's own implementation choice, ambiguity 16 extended below -- e.g. a
    `dispatch.part_write_deadline_s` entry in a new or existing `config/*.yaml`), never a module
    constant like round 7's `_PART_DEADLINE_S = 0.3`. Resolved through this same Depends() seam as
    get_store/get_event_writer/get_current_principal precisely so a test can prove the route reads
    it fresh on every call rather than capturing a constant once at import time: every test
    overrides this via app.dependency_overrides[get_part_write_deadline_s] (`_api_lib.
    as_part_write_deadline`), and a test may re-install a different value mid-test to prove the
    same writer/latency combination behaves differently under a shorter vs. a longer deadline."""
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
- Locking (round-4 finding, qa biggest; deadline and same-world/cross-owner clarifications new in
  round 5, "What changed since round 4" finding 2): every targeted policy's level, history and
  `changed_by` are updated to L1 in `store.policies` **before** this call attempts any writer call
  for that policy's part — the level change is what "instant" means for a kill switch (PRD 10.4),
  the event is only its audit trail. **The lock(s) for every touched world are held only for that
  mutation (and the decision of what to flush) — never across any `writer.append` call, flush or
  new-part alike; every writer call happens strictly outside the locked section, and each attempt
  carries its own bounded deadline** (round-5 finding 2), so an attempt whose writer never returns
  at all does not hold the request open past that deadline (it is queued pending instead, like any
  other failed attempt) and does not hold any lock open at all (the lock was already released
  before the attempt began). Whatever serializes two concurrent calls against the *same* world (so
  they do not each independently read the pre-change state and double-apply, round-3's concurrency
  finding) must not also serialize calls against *different* worlds behind writer I/O: writer calls
  happen outside that serialization, or through a flush bounded well under the 5 s budget
  regardless of how many parts are pending or how slow the writer is per call, so that a kill
  switch pressed against world A never waits on world B's writer latency, and vice versa. A
  one-policy Stop-all against a different, otherwise-idle world, issued while a 200-policy Stop-all
  against a slow-and-failing writer is still in flight for another world, finishes in under 1 s.
  Two further cases this round's tests pin, both following from "no lock is ever held across writer
  I/O": **a second Stop-all against the *same* world, issued while the first is still stuck waiting
  on (or past the deadline of) a writer call that never returns, itself returns within 5 s** — by
  the time it runs, the first call's level-change section has already released that world's lock,
  so the second call finds every policy already at L1 (`already_l1`, nothing new to do) and returns
  almost immediately; and **a Stop-all issued by a *different* owner against a *different* world
  that the first owner's own Stop-all merely happens to also touch (via `policy_worlds`) is not held
  up by the first owner's stuck writer call either** — that shared world's lock was likewise
  released before the first call's writer phase began, so the second owner's own, direct Stop-all
  against their own world acquires it immediately.

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

### Order within a world (round-5 code/qa finding, "What changed since round 4" finding 3)

Whatever order a world's writer calls are *dispatched* in (concurrently is fine, finding 2's
per-part deadline needs every part actually attempted rather than queued one deadline apart), the
order their results are **committed to `store.events[w]`** — and therefore the `seq` the writer
assigns each one — must match the order the parts were queued or built for that world, never the
order the underlying writer calls happen to finish on the wire. Concretely, for a single call
against a single world `w`:

1. Every part already sitting in `store.pending_events[w]` is flushed **first, in that list's own
   oldest-first order** (unchanged invariant, round 3) — before any part this call newly builds for
   `w` is attempted at all.
2. This call's own newly-built parts for `w` follow, in the order the route built them (its own
   "build order" — for `stop`/`revoke` this is plan order, i.e. `store.policies`' iteration order
   filtered to this call's owner; for `pause` this is every lowered policy's `policy.changed` part,
   in that same plan order, ~~**then** the one `world.paused` part last, since `pause`'s own
   handler builds it only after the stop-all-style plan is built~~ **superseded by ST-3a-3** (see
   "What changed since round 6 (ST-3a-2) — ST-3a-3" below): `world.paused` is now enqueued
   *ahead* of this call's own `policy.changed` parts, not after them, and ahead of anything already
   pending for `w` too — item 1 above no longer applies to a *new* `world.paused` part this call
   builds, only to parts that were already pending before this call started).

Parallelism across *different* worlds is unaffected and still required (finding 2): world `w1`'s
writes and world `w2`'s writes may proceed fully concurrently with each other: only the ordering
*within* a single world's own stream is constrained. **Superseded in part by round 8 (issue #46,
"What changed since round 7" finding 3): parallel dispatch *within* one world's own writer calls
is no longer required or permitted at all -- at most one `append` is ever in flight for a given
world, full stop, in queue order.** This simplification is what the id-based idempotency finding 2
of round 8 makes safe to rely on instead of an in-order commit buffer: ordering within a world no
longer needs a buffer to hold a fast-finishing later part back, because there never is a later part
being attempted concurrently with an earlier, still-unsettled one. This round's tests pin two
concrete cases: a
world with **100** parts already pending (from an earlier failed call) lands in `store.events[w]`
in exactly that queued order once flushed; and, within one `pause` call, ~~every `policy.changed`
part it builds lands in `store.events[world_id]` before that same call's own `world.paused`
part~~ **superseded by ST-3a-3: `world.paused` now lands before every `policy.changed` part this
same call builds** — never interleaved out of order by which writer call happens to return first.

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
  (never `policy_worlds`) with `data == {"reason": "pause_all", "channel": <principal.channel>}`
  (round-6/ST-3a-2, issue #38 item 5: derived from the caller's own resolved session channel, never
  from `body.channel` -- the request body's `channel` field is still validated against the schema
  enum, 422 outside it, but is no longer read for this purpose; see ambiguity 18),
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
  When `policy_id` maps to a world (`store.policy_worlds.get(policy_id)` is not `None`), **that
  world's lock is acquired first, before anything else this route does** (round-5 code/qa/security
  finding, supersedes round-4 ambiguity 12 — see "What changed since round 4," finding 4): under
  that lock, revoke first flushes `store.pending_events.get(mapped_world_id, [])` **in full,
  oldest first** (not only a part revoke's own earlier attempt might have left there — any other
  policy's stuck part sitting in that world's queue too, exactly as `stop`/`pause` flush every
  world they touch), then appends one history entry
  `{"by": owner, "at": now, "change": "revoked", "level": "L1"}` (always appended, even if already
  L1 — revoke is a distinct, explicit act unlike the bulk Stop-all, so no idempotency skip here; a
  missing or non-list `history` is replaced the same fail-safe way stop-all does), sets
  `level = "L1"`, `changed_by = {"by": owner, "at": now}` — **this part never depends on the writer
  and is never rolled back, whatever the writer does next** — and builds one `policy.changed` part
  (`data.change == "revoked"`, `data.level == "L1"`, `vis` by the same target-world-scope-
  intersection rule as stop-all, computed against the policy's mapped world's own districts) for
  the policy's mapped world, handed to the writer per the same "Pending writes and flush" rule
  stop-all and pause use, still under the same lock's mutation (never during writer I/O, finding 2):
  a writer failure or a missed deadline keeps the part in
  `store.pending_events.setdefault(mapped_world_id, [])` instead of raising or being lost, to be
  flushed by a later mutating call that touches that world — which may again be another revoke, per
  this same rule. A policy with no world mapping (policies live at org level, PRD 15.3) is still
  revoked (history entry, L1); no world lock is acquired and nothing is flushed (there is no world to
  flush or lock), and no event (pending or otherwise) is handed to any world: revoke has no world of
  its own, and an event is never filed under a world that does not exist (PRD 9.4 honesty). **Its own
  history/level/changed_by mutation is nonetheless taken under a lock scoped to that one policy id**
  (round-6/ST-3a-2, issue #38 item 5 — see "What changed since round 5" and ambiguity 19: a policy-id
  lock, not a world lock, so two concurrent revokes of the same unmapped policy cannot race and lose
  one's history entry, and a concurrent Stop-all/Pause-all against an unrelated world is never blocked
  by it). The history
  entry is the audit record either way.
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
  | `ts`, `type`, `level`, `severity`, `credits`, `summary`, `authz` | unchanged from the stored event | unchanged from the stored event |
  | `target`, `actor` | unchanged from the stored event | the stored value unchanged — by the time an event reaches this table it has already passed the hidden-district filter above, so a district-shaped `target`/`actor` here is guaranteed to name a district `principal.districts` includes (or not be district-shaped at all); a hidden one means the whole event was already dropped, never reaching this row (round-5: supersedes round 4's "null the field, keep the event") |
  | `district` | the stored event's real `district` | the stored `district` unchanged — same reasoning as `target`/`actor` above: a hidden `district` value means the whole event was already dropped by the hidden-district filter, so this row only ever sees `None` or a visible district id (round-5: supersedes round 3's "null the field, keep the event") |
  | `cause` | unchanged | the *view-local id* (same `f"v{seq}"` scheme, using the **causing event's own view `seq` in this same response**) of the causing event, when that event survived filtering; `null` when it names an event that was dropped or never existed (round-1 rule, now expressed via the view-local id instead of the real one, since the real one is never returned to a scoped principal) — unaffected by round 5: a `cause` names an *event*, not a district, so it is never itself a reason to drop the whole event, only to be remapped or nulled |
  | `vis` | unchanged | `"all"` stays `"all"` (nothing to filter); **a district list is filtered to its intersection with `principal.districts`** before being returned — never the stored event's full, unfiltered list (round-4 security finding: the event is kept whenever `vis` intersects `principal.districts` at all, but the *full* stored list can name additional districts the caller cannot see at all, and returning it unfiltered tells that caller "someone else can see this too, and here is exactly which other district" — a leak of a hidden district's *id* through a field that was previously assumed safe because "it is never itself sensitive." The kept intersection is always non-empty, since the event would not have survived filtering otherwise, so this never turns a visible event invisible) |
  | `data` | unchanged | rebuilt by walking the stored `data` value **recursively** (round-4: a dict's values, and every item of a list, at any depth; round-5 extends this to dict **keys** too, and adds a depth guard — see "Depth and dict keys" below) applying, to every string leaf found: (1) if the key it is stored under is `"message_ref"` (at any depth, not only top-level), always `null` for a non-owner, regardless of shape, per the `trace.archive_ref` rule below; (2) else if it matches the ULID pattern, the same cause-style remap — the view-local id of the event it names, if that event survived filtering, else `null` (for example `policy.applied.data.instruction_id`, or the same value nested inside a list or a sub-object); (3) else if it matches the district_id pattern (`^D[0-9]{1,4}$`) — by round 5 this case can only be reached for a *visible* district (a hidden one already dropped the whole event via the hidden-district filter above) — left unchanged; every other value (a non-string, or a string matching none of the above) is left exactly as stored. **Dict keys** get the equivalent treatment (round-5 finding 6): a district-id-shaped key naming a hidden district already dropped the whole event (same filter, keys included); a district-id-shaped key naming a visible district is left unchanged; a ULID-shaped key naming an event that survived filtering is renamed to that event's own view-local id (its value redacted normally); a ULID-shaped key naming a hidden or unknown event is dropped — the key *and* its value are removed from the rebuilt dict, since a JSON key cannot itself be set to `null` the way a value can (ambiguity 17). The dict/list *shape* of `data` is otherwise always preserved; only leaf string values, and the specific keys named above, are ever rewritten or removed. |
  | `trace` | unchanged | **rebuilt by allowlisting exactly `event.schema.json#/$defs/trace`'s seven keys** (`model_role`, `profile`, `tokens_in`, `tokens_out`, `tool`, `latency_ms`, `archive_ref`) with `archive_ref` always `null` (round-3 finding: `archive_ref`/`message_ref` name a position in the run-wide raw archive — PRD 13.2 — a counter unrelated to district visibility that would let a scoped viewer infer how many raw records exist between two events it can see, so it is stripped outright rather than filtered by visibility; round-6/ST-3a-2 finding, issue #38 item 5: a stored `trace` copied forward wholesale can carry an extra, schema-invalid key — the stored value should never have one, `trace.additionalProperties: false`, but a scoped view must not merely trust that — so anything outside those seven keys is dropped rather than copied) |

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

12. **Revoke's own flush scope.** ~~Revoke now uses pending-on-failure for its own one part
    (ambiguity 9, superseded), but does not proactively flush any *other* policy's pending part for
    the same world when it runs — only its own. Flushing a whole world's backlog on a
    single-policy revoke would make one policy's revoke responsible for clearing another,
    unrelated policy's stuck write, which is a `stop`/`pause`-shaped bulk responsibility, not a
    revoke-shaped one; a world's other pending parts are still flushed the next time `stop` or
    `pause` touches that world, per "Which worlds a call touches" above.~~ **superseded, round 5:
    revoke now flushes its target world's whole pending backlog, oldest first, under that world's
    lock, exactly like `stop`/`pause` — see "What changed since round 4," finding 4.**
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

## Ambiguities resolved this round (round 5)

15. **Owner's response for depth-500 `data`.** The owner's view returns the stored event, `data`
    included, unmodified — never redacted, never dropped — regardless of nesting depth, because the
    owner's response path never recurses over `data` at all ("What changed since round 4," finding
    5). This was a real choice, not the only defensible one (an alternative would drop *every*
    viewer's copy of an absurdly deep event, owner included, for uniformity) — resolved toward
    "owner sees everything" (PRD 10.1) since deep-but-well-formed `data` is not itself a malformed
    record the way a missing `id` or a non-string `cause` is (ambiguity 11), and the owner's code
    path has no reason to ever inspect `data`'s shape at all.
16. **The exact per-writer-attempt deadline value (finding 2).** Left as this ticket's own
    implementation choice, not pinned to a specific number of milliseconds here: this round's tests
    only require that the request-level 5 s budget holds against a writer whose `append` call never
    returns at all (an unbounded block), which is true for *any* finite per-attempt deadline
    meaningfully smaller than 5 s, so pinning an exact figure would constrain the implementation
    without the tests needing it to prove the property FR-HIL-07/PI-18 actually cares about.
17. **ULID-shaped `data` key naming a hidden or unknown event (finding 6).** Dropped (key and value
    both removed from the rebuilt dict) rather than kept with some placeholder key, since a JSON key
    cannot be null and inventing a synthetic placeholder key (e.g. `"_hidden"`) would itself be new
    information not present in the original shape and could collide with a real key already in the
    same dict.
