# ADR-0012: An event in a district is visible by district (EV-13)

- Status: Proposed — awaiting user approval (2026-10-02, architect; issue #29, BQ-28). It tightens
  a frozen event rule and rewrites frozen fixtures, so nothing in `contracts/` changes until the
  user approves (root `CLAUDE.md`, ADR-0002 decision 2).
- Deciders: user (approval), architect (proposal)
- Requirement: FR-HIL-09, SEC-07 (PRD 9.3, 10.1, 15.3)
- Lands with: ADR-0009 (issue #125). Both change EV-13 and `vis`.

## Context
EV-13 says that when `district` is set and `vis` is a list, the list includes `district`. It
still allows `vis: "all"` with a district set. BQ-28's default was that the harness chooses
`"all"` from the world's viewer scopes.

The valid fixtures for `district.created` and `agent.spawned` set `district: "D1"` with
`vis: "all"`, and they name the district ("District Mail is set up.", `data.name: "Mail"`). So a
district's name reaches every viewer, including viewers the district is hidden from. PRD 10.1
says hidden districts show fog "with no names or counts". FR-HIL-09 says a Viewer's API
responses never contain hidden-district names.

BQ-28's default also fails over time. `vis` is written once, when the event happens, but viewers
can be added later. A viewer added with `D1` hidden would still see every earlier `"all"` event
of `D1`. Today `tilo-api` works around this by failing closed: for anyone but the owner, it drops
every event that names a hidden district in `district`, `target`, `actor` or `data`.

Of the 125 event fixtures, 88 have a district with `vis: "all"`. So do 34 of the 44 events in
`fixtures/streams/village-basic.jsonl`.

## Decision (proposed)
1. **EV-13 (validator).** When `district` is set, `vis` is a list that includes that district,
   and never `"all"`. `"all"` (and, under ADR-0009, the empty list) is only for events whose
   `district` is null. A list may also name other districts the event concerns, as now. Every
   listed district exists in the world's layout, as now.
2. **No schema change for the rule.** It compares two fields, like the rest of EV-13. A second
   root conditional in `event.schema.json` would sit beside EV-03's. json-schema-to-typescript
   turns a root `allOf` into an unusable intersection type, and nesting the rule into both
   branches would duplicate it. Only the `vis` description changes (folded into ADR-0009's
   1.1.0; on its own this would be a 1.0.1 text change). `v` stays `"1.0"`.
3. **The harness sets `vis` from where the event renders.** By default it writes `[district]`
   for every event in a district, never from the current viewer list, so later viewers cannot
   see past events of a hidden district.

```diff
 contracts/event.rules.md
-| EV-13 | `vis` is tied to where the event renders: when `district` is set and `vis` lists districts, the list includes `district`, so that district's viewers see what happens in it; every district `vis` lists exists in the world's layout (BQ-28). | validator | 9.3, 10.1, FR-HIL-09 |
+| EV-13 | `vis` is tied to where the event renders: when `district` is set, `vis` is a list that includes `district`, never `all`, so only that district's viewers (and the owner) see what happens in it, whoever is added as a viewer later; `all` is only for an event with no district; every district `vis` lists exists in the world's layout (BQ-28, ADR-0012). | validator | 9.3, 10.1, FR-HIL-09, SEC-07 |
```

```diff
 scripts/contracts_events.py  (event_problems)
-    if isinstance(event["vis"], list) and event["district"] is not None and event["district"] not in event["vis"]:
-        problems.append("EV-13: vis must include the district the event renders in")
+    if event["district"] is not None and (not isinstance(event["vis"], list) or event["district"] not in event["vis"]):
+        problems.append("EV-13: an event in a district has a vis list that includes that district")
```

`services/harness/src/tilo_harness/validator.py` (line 377, the same check before every write)
gets the same change.

## Alternatives considered
- **Keep `"all"` allowed, chosen from the current viewers (BQ-28 as it stands).** This leaks to
  viewers added after the event. Rejected.
- **Redact only in the reader**, as tilo-api's fail-closed drop does. PRD 15.3 says the harness
  writes each redacted view itself. Dropping every event that mentions a hidden id also loses
  what fog should still show. Keep the drop as defence in depth, not as the rule.
- **Put the rule in the schema** (if `district` is a string, `vis` is an array). See decision 2:
  the TypeScript generation pitfall, or duplication. The validator already runs EV-13 before
  every write.
- **A redacted copy per scope with the name replaced.** That is the view writer's job on top of
  this rule, not instead of it.

## Migration and fixture impact
- **Mechanical rewrite.** For every event fixture with `district` set and `vis: "all"`, set
  `vis: [district]`. That is 88 files across `fixtures/events/valid/`,
  `fixtures/events/invalid/` and `fixtures/events/registry/invalid/`, plus 34 lines in
  `fixtures/streams/village-basic.jsonl`. Each invalid fixture still fails only its own rule,
  because `vis` is not what it tests. Write with LF, then run
  `pnpm exec biome format --write contracts`.
- **New invalid fixture:** `fixtures/events/registry/invalid/ev13_district_event_visible_to_all.json`.
  The migrated stream supplies the valid case.
- **Producers:**
  - The harness and its run events (CL-INT-2) set `vis: [district]`.
  - `tilo-api` card parts already use `[district]` (BQ-73).
  - `packages/planning` events have no district, so `"all"` stays correct there.
- **Web and test data** that build district events with `vis: "all"` need the same rewrite,
  where they pass through the validator:
  - `apps/web/src/api/fixtures/events.ts`;
  - `apps/web/e2e/world-actor-move-order.spec.ts`;
  - `apps/web/scripts/make-crowd-fixture.mjs` and the `apps/web/fixtures/*.events.jsonl` it
    writes;
  - the harness and API tests that list `vis` (`git grep -l '"vis"' services/*/tests`).

  `design/source/` is read-only and is never validated as events (BQ-07).
- **No stored data to migrate:** only local emulators exist (ADR-0003), and their state is reset.

## Consequences
- Unblocks:
  - FR-HIL-09 and SEC-07: the contract itself keeps hidden-district events out of other
    scopes.
  - The harness-written views of PRD 15.3 (`services/harness/src/tilo_harness/views.py` needs
    no change, since it already reads lists).
  - Most of issue #38 item 6.
- **Still open for the view writer (not a contract change).** World-level events with
  `vis: "all"` can still name or count hidden work, through `summary` text and totals such as
  `world.planned` `unit_count` and `world.completed` `deliverable_count` / `credits_used`. PRD
  10.1 says "no names or counts". In a scoped view, the writer must rebuild such a line from a
  template for that scope, or leave the count out. This belongs to the views ticket.
- **A Viewer's scope.** After this change, a Viewer whose scope is `shared` (BQ-40) sees only
  world-level events. A viewer who should see the whole world, such as the public demo link,
  needs a scope that covers every district. Either the view writer adds such a view, or
  tilo-api filters the full stream per principal, as `redaction.py` does today. The views
  ticket decides.
