# ADR-0040: Team-shared worlds

- Status: Accepted (user, 12 Oct 2026, relayed by the supervisor and recorded by the architect on the same
  day); builders start after the architect's contract PR (TSW-0) merges. Written as Proposed earlier the same
  day; the design below is the one accepted, unchanged. It amends a frozen people rule (PE-03) and adds one
  schema, one optional field and one event type, all of which land in TSW-0 and nowhere else.
- Deciders: user (acceptance), architect (proposal)
- Requirement: BQ-CTX-TEAMWORLD (Context aggregate, PR #851); FR-TEAM-01 to FR-TEAM-06; FR-HIL-09, SEC-07;
  PRD 10.1 (Viewer: "shared scope"); PE-01 to PE-12, PE-20, PE-26 to PE-30; ADR-0006, ADR-0009, ADR-0012,
  ADR-0015, ADR-0016, ADR-0018
- Number: 0040. 0037 to 0039 are on `phase0-stack` (taught-skill run provenance, owner-only pin placement,
  settings); 0040 was free on the base and on every remote branch on 2026-10-12. Re-check before merge.

## Context

The user's direction (12 Oct, as relayed): a world shared with a team is visible to everyone in that team,
including each other member's contributions and active work (pins, work items, artifacts, runs). Only
personal items (personal pins, the personal plate, private meetings and mail of one person) stay invisible to
others. The user answered yes to: "a team-shared world shows members' work items, artifacts and runs to the
whole team; that needs a world-to-team link and a rule change to PE-03".

What exists, read from the code on `phase0-stack` (2b156ac0):

- **No link.** `WorldRecord` (`services/api/src/tilo_api/deps.py`) has one `owner` and no team. A deployed
  sign-in is `role="owner"`, `world_id=None` (`principal_from_claims`); `member_world` lets a request reach a
  world only when the principal is bound to it or is its record owner on a web session, and every other case is
  the one unknown-world 404 (no membership oracle). A teammate therefore gets 404 for a teammate's world.
- **PE-03.** A work item is read in full by its `owner` only; the assigner reads its status. Work items have no
  world field (the Context aggregate guesses a world from `source.kind == "request"`, which is not a contract).
- **Teams are the directory's.** `person.memberships` (`team`, `assigned_by`) and `Directory.is_member`
  (PE-02 terms) are the only team facts. The Park team store (`team_store.py`, one team per install, roles
  Owner/Admin/Member/Guest) is a separate thing (BQ-DSN-01, BQ-TEAMRT-2) and this ADR does not touch it.
- **Viewer already exists.** PRD 10.1 gives a Viewer the world, Story and Trace "in shared scope";
  `redaction.py` already serves a bound principal with `districts` through `vis`, and ADR-0018 serves artifact
  bytes to "a scoped viewer whose district saw the creating event". `vis: []` is owner-only (ADR-0009).
- **Pins** already do what the user wants: an active team pin is read by the members of its team (PE-02).

## Decision

1. **The link is its own record, `world_share`, in the people stores; the world record is untouched.** One
   record per (world, team): `{id, org_id, world_id, team, granted_by: {by, at}, revoked: null | {by, at}}`.
   `id` is `ws_` plus the first 32 hex characters of SHA-256 of `<world_id>/<team>`, so uniqueness is
   structural and a retry is idempotent. It lives in `PeopleStores.world_shares` beside the records whose
   rules it feeds (indexed by `world_id` and by `team`), not on `WorldRecord`, for three reasons: the world
   document is rewritten by every run commit and a revocation must never ride on, or be lost by, a stale
   rewrite; "which worlds are shared with my teams" needs a team-keyed query that a world field does not give;
   and the oracle's inputs, fixtures and erasure (PE-16) all live in `tilo_people`.
2. **Who creates and revokes: the world's owner only.** `PUT` and `DELETE /worlds/{world_id}/team-shares/{team}`
   need the record owner on a full web or mobile-web sign-in session (`full_session`, channel `web` or
   `mobile_web`; never an email, signed-link, demo or world-bound session) and, to create, that the owner is a
   member of `{team}` at the request (the PE-04 rule for sharing a calendar entry). `granted_by` and `revoked`
   are stamped from the verified principal and the server clock (PE-19), never from a body. No model, agent,
   assistant `ui_action` or Approver can call it. Org owners get no revoke right: removing the world owner
   from the team (PE-17, already theirs) lapses every share that person made to it, which is the off switch.
3. **A share is in force only while it still means what it said.** At `now`: `revoked` is null,
   `granted_by.by` equals the world's current record owner, `granted_by.at <= now`, and the owner holds a
   membership of the team assigned no later than `granted_by.at`. So it lapses when the owner leaves the
   team, it does not revive when they come back (they share again), and a world whose record owner changed
   shares nothing until the new owner shares it. A lapsed or revoked share is "no share", not an error.
4. **What a team member gets in that world: a read-only Viewer of every district, nothing else.** A person
   who is not the owner reads the world as a **team reader**: full web or mobile-web session of the same org,
   bound to no world, member of the team of a share in force. `tilo-api` derives an internal Viewer principal
   (`role="viewer"`, `districts` = every district the record and layout name) for the read routes only:
   events with `vis` `all` or a district (never `vis: []`), layout, world, delivery and the artifact bytes
   and manifests those events name (ADR-0018's `.../artifacts/{artifact_id}/versions/{version}` and
   `.../manifest`, which tilo-api does not serve yet: TSW-4b gives each the team path where it lands).
   Delivery answers its owner only today (`runs.py`); this widens it to team readers on purpose, since it lists
   what the same readers already see as `artifact.delivered` and `world.completed`. Cards, console, costs,
   policies, kill switch, schedules, pause, answers, approvals, sharing and `/worlds/{id}/apps/...` (it
   writes events) stay on `member_world`, so they keep answering the unknown-world 404. Approver and
   Team Lead rights come only from their own ADR-0006 assignments. A team reader is not on the plate (PE-27:
   "nothing from a world where they are only a Viewer").
5. **How it is checked, per request, server side.** Inputs are the verified principal
   (`get_current_principal`), the world record from the store, the `Directory` built from the people store and
   the server clock. The team is never taken from a header, query, path or body for a read: the route lists
   the world's shares and finds one in force whose team the actor belongs to. Order inside one helper,
   `deps.readable_world(principal, store, people, clock, world_id) -> (WorldRecord, Principal)`: (a) the
   existing `member_world` path first, unchanged (owner, bound viewer, bound approver); (b) else the
   session-shape test; (c) else the share test; (d) else the same 404 body. A people store that cannot be
   opened is 404 for a non-owner (logged, no detail) so absence of access and absence of a world look alike.
   There is no cache: revocation, removal from the team and a lapse take effect on the next request
   (`GET` routes poll; there is no streaming route).
6. **Work items: an optional `world_id`, visibility derived from the world's share.** `work_item` 1.1.0 adds
   an optional `world_id` (absent = personal, as every item was). It is set only at creation, by the person who
   made and owns the item, who owns that world or is a team reader of it, and never changes; a Tilo-made item
   never has one (a meeting's action items stay personal, PE-08). A new action `read_team` returns the team
   view (`id`, `title`, `status`, `due`, `owner`, `world_id`) to a person who is a member of the team of a
   share in force for that `world_id` when the item's owner is also a member of that team, the item is `open`
   or `done`, and it is not `flagged`. `read_full`, `edit`, `mark_done`, `confirm` and the assigner's
   `read_status` are unchanged, so a teammate can read the row and change nothing. Dropping an item removes it
   from the team. Exact PE-03 wording and the new rules PE-31 to PE-35 are in "Exact diffs".
7. **Artifacts and runs follow the world, with attribution that adds no new name source.** Both are read
   through the same Viewer path (decision 4); the artifact scope is the world's own (`org_id`, `world_id`,
   `world.owner` from the record, never from the principal) so a team reader cannot name another scope. The
   names shown are the ones the world's pages already show for those events, plus a person's display name only
   as PE-20's directory view allows a teammate (id and display name; never address, aliases, time zone or
   channel). A run or artifact of a member is a run or artifact of that member's own world that they shared.
8. **Still private inside a shared world:** personal pins; the plate and its rows; meetings, transcripts,
   minutes and evidence quotes; mail; calendar entries beyond PE-04; proposed items; flagged records (PE-21);
   a teammate's snoozes, assigners and sources; `vis: []` events; cards, costs and consoles. The assistant,
   digest and plate never carry a teammate's item (PE-11, PE-27 unchanged), and a team view is a list row, not
   a `navigate` target (PE-10).
9. **Events and routing (PE-12) are unchanged, plus one event.** A work item's events stay in its owner's Desk
   world with `vis: []`; the team list is read from records, exactly as team boards are ("read from their
   records, never from another person's event stream"). So the team's Story and Trace carry no line about a
   teammate's item and the scene animates nothing for it (HR-1); the web shows the list as a read model. One
   new type, `world.share_changed` (data `team`, `state` on or off), is written in the shared world by
   `tilo-api`: actor the owner, `target` null, `district` null, `vis: []`, not a side effect (no `authz`,
   like `team_rule.changed`), ids only. Order: record write first, event second. If the event fails on a grant
   the route removes the record again and answers 503; on a revoke the revocation stays (fail closed) and the
   identical retry writes the missing event (deterministic part id). A lapse writes nothing, because no one
   acted; the API says `in_force: false` and why in a fixed word.
10. **Migration: nothing is exposed that was not already shared.** No backfill. Every existing world has no
    share; every existing work item has no `world_id`; the `source.kind: request` guess is never used as a
    link. Items a person already has in a world stay personal even after that world is shared; only items
    created with a `world_id` afterwards are visible. The share dialog says plainly that the whole world's
    Story, Trace, runs and artifacts, past and future, except owner-only lines, become visible to every member
    of the team, and that items added in the world from then on are visible too.

### Exact diffs

New file `contracts/world_share.schema.json` (1.0.0; fixtures below):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://contracts.tilo.example/world_share.schema.json",
  "x-version": "1.0.0",
  "title": "WorldShare",
  "description": "A world shared with one team (ADR-0040, PE-31): the members of `team` read that world's Story, Trace, runs and artifacts as Viewers of every district, and read the team view of the work items made in it (PE-33). It is not a role: it carries no scope and no right to answer, approve, start, stop or share, and adds no Approver or Team Lead (ADR-0006). `granted_by` is the world's owner, stamped by tilo-api from the signed-in session and the server clock (PE-19). `revoked` is null while the share stands and the owner's stamp once withdrawn, effective on the next request. One record per world and team (`id` is ws_ and the first 32 hex characters of SHA-256 of `<world_id>/<team>`, checked by the validator); sharing again after a revoke replaces the record and the world's `world.share_changed` events keep the history. Whether the share is in force also depends on the directory (PE-31), which this schema cannot see.",
  "type": "object",
  "additionalProperties": false,
  "required": ["id", "org_id", "world_id", "team", "granted_by", "revoked"],
  "properties": {
    "id": { "$ref": "#/$defs/id" },
    "org_id": { "$ref": "common.schema.json#/$defs/org_id" },
    "world_id": { "$ref": "common.schema.json#/$defs/world_id" },
    "team": { "$ref": "common.schema.json#/$defs/team_id" },
    "granted_by": { "$ref": "team_lead.schema.json#/$defs/assignment" },
    "revoked": {
      "anyOf": [{ "$ref": "team_lead.schema.json#/$defs/assignment" }, { "type": "null" }]
    }
  },
  "$defs": {
    "id": { "type": "string", "pattern": "^ws_[0-9a-f]{32}$" }
  }
}
```

`contracts/work_item.schema.json` (1.0.0 to 1.1.0, additive; `dependentSchemas` keeps the root conditional
single, both generators ignore it):

```diff
-  "x-version": "1.0.0",
+  "x-version": "1.1.0",
...
-  "description": "One thing a person has to do (FR-PA-01): ... A model never sets `due`: code computes it from `due_text` (PE-15).",
+  "description": "One thing a person has to do (FR-PA-01): ... A model never sets `due`: code computes it from `due_text` (PE-15). An optional `world_id` (ADR-0040, PE-33) binds a person-made item to a world its owner may read; while a team share of that world is in force (PE-31) the members of the team read the item's team view (id, title, status, due, owner, world) when it is open or done and not flagged. Absent means personal, as every item was before 1.1.0; it is set only at creation, never changed, and a Tilo-made item never has one.",
...
     "flagged": { ... },
+    "world_id": {
+      "$ref": "common.schema.json#/$defs/world_id"
+    },
     "history": { ... },
...
   "if": { ... },
   "then": { ... },
+  "dependentSchemas": {
+    "world_id": {
+      "properties": {
+        "created_by": {
+          "properties": { "by": { "const": "person" } },
+          "required": ["by"]
+        }
+      }
+    }
+  },
   "$defs": { ... }
```

`contracts/events/registry.yaml` (1.4.0 to 1.5.0 unless an open PR already holds 1.5.0; take the next free
minor and copy that PR's version-pin test hunk, ADR-0028). Family `world` exists, so
`registry.schema.json` does not change:

```diff
-version: 1.4.0
+version: 1.5.0
...
+  world.share_changed:
+    family: world
+    verb: share_changed
+    priority: should
+    pillar: P4
+    default_severity: info
+    side_effect: false
+    world_effect: "A team badge shows on the world's gate while the share stands and comes down when it is withdrawn."
+    hud_effect: "The world's sharing line names the team, or says it is not shared."
+    story_template: "{actor} turned team sharing {data.state} for this world."
+    trace_row: "team={data.team} state={data.state}"
+    data_schema: events/data/world.share_changed.schema.json
+    fixture: fixtures/events/valid/world.share_changed.json
```

New `contracts/events/data/world.share_changed.schema.json` (1.0.0):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://contracts.tilo.example/events/data/world.share_changed.schema.json",
  "x-version": "1.0.0",
  "title": "WorldShareChangedData",
  "description": "data of world.share_changed (registry 1.5.0, ADR-0040). The world's owner turned team sharing on or off for one team. tilo-api writes it in the shared world after the world_share record was written, never an agent or a model: actor is the world's owner (the actor of its first world.requested), target and district are null and vis is [] (owner-only, ADR-0009). state on means a share record now exists for team; off means it was revoked. It authorises nothing outside Tilo and sends nothing, so it is not a side effect and authz is null. A share that lapses because the owner left the team writes no event.",
  "type": "object",
  "additionalProperties": false,
  "required": ["team", "state"],
  "properties": {
    "team": { "$ref": "../../common.schema.json#/$defs/team_id" },
    "state": { "type": "string", "enum": ["on", "off"] }
  }
}
```

`contracts/people.rules.md` (people rules; PE-03 amended, PE-31 to PE-35 added, PE-12 gets one sentence):

```diff
-| PE-03 | A `proposed` work item ... nobody else reads it. A person-made item is its creator's own ... | validator | FR-PA-01, FR-PA-11, FR-MTG-06 |
+| PE-03 | A `proposed` work item (only Tilo makes those, from minutes) is read by no one: the meeting Owner sees its content in the minutes, and only that Owner (`assigned_by.by`) confirms it. Once `open`, `done` or `dropped` the `owner` reads and edits it and marks it done; the person who assigned it reads its status only (`read_status`), never `source`, `evidence` or `history`; nobody else reads it, with one exception (PE-33, ADR-0040): a person-made item that names a `world_id` is also read as the team view (`read_team`: id, title, status, due, owner, world) by the members of a team that world is shared with (PE-31), while it is `open` or `done` and not `flagged`. A person-made item is its creator's own (`owner` equals `created_by.ref`): nobody pushes an item onto another person's plate, a hand-over is a `reassign_requested` the owner accepts. | validator (schema for `world_id`) | FR-PA-01, FR-PA-11, FR-MTG-06; ADR-0040 |
```

```diff
-| PE-12 | ... Team boards are read from their records, never from another person's event stream. The `summary` ...
+| PE-12 | ... Team boards, and the team view of a shared world's work items (PE-33), are read from their records, never from another person's event stream. The `summary` ...
```

```diff
+| PE-31 | **World share.** A `world_share` links one world to one team. It is made only by the world's owner (the record owner from the store, never the request) in a full web or mobile-web sign-in session, for a team the owner is a member of at the request; `granted_by` is that owner and, like `revoked`, is stamped from the session and the server clock (PE-19). Only that owner revokes, and it takes effect on the next request. The `id` is `ws_` and the first 32 hex characters of the SHA-256 of `<world_id>/<team>`. A share is **in force** at `now` only while `revoked` is null, `granted_by.by` is the world's current owner, `granted_by.at` is no later than `now`, and the owner has a membership of the team (PE-02 terms) assigned no later than `granted_by.at`, so it lapses when the owner leaves the team and does not revive when they return. Any other state is no share, never an error. A share is not a role: Approvers and Team Leads come only from their own assignments (ADR-0006). | validator (schema for the shape) | ADR-0040; PRD 10.1 |
+| PE-32 | **Team reader.** A person who does not own a world reads it only as a team reader: a full web or mobile-web sign-in session of the same org, bound to no world (never an email, signed-link, demo or world-bound session), who is a member of the team of a share in force for that world (PE-31) at the request. They get the Viewer view (PRD 10.1) of every district: events whose `vis` is `all` or lists a district, the layout, the delivery, and the artifacts and runs those events name; never an event with `vis: []` (PE-12), a card, the console, costs, a policy, a kill switch, a schedule or any write. The check runs on every request from the verified session, the world record and the directory, never from a header, query, path team or body, so a revoked, lapsed or removed reader loses access on the next request, and every refusal (an unknown world and a world not shared with the person alike) is the one unknown-world 404. | validator; API tests | ADR-0040; SEC-07, FR-HIL-09 |
+| PE-33 | **Work items in a shared world.** `world_id` is set only when a person creates an item they own and made (`created_by.by` person, `owner` equals `created_by.ref`), who owns that world or is a team reader of it (PE-32) at the create; it never changes, and Tilo never sets one (a meeting's items stay personal, PE-08). `read_team` of an item is allowed to a person who is a member of the team of a share in force (PE-31) for its `world_id` when the item's `owner` is also a member of that team at the request, its `status` is `open` or `done` and `flagged` is false. The view is `id`, `title`, `status`, `due`, `owner`, `world_id` and never `source`, `evidence`, `history`, `assigned_by`, `snoozed_until` or `flagged`. `read_full`, `edit`, `mark_done` and `confirm` stay as PE-03: a teammate gets none. The plate, the digest and the assistant never carry a teammate's item (PE-27, PE-11 unchanged) and a team view is not a `navigate` target (PE-10). | validator (schema for `world_id`) | ADR-0040; FR-PA-01 |
+| PE-34 | **Private inside a shared world.** A share never exposes personal pins (PE-01), the plate and its rows (PE-26 to PE-29), meetings, transcripts, minutes and evidence quotes (PE-05, PE-22 to PE-25), mail, calendar entries beyond PE-04's busy view, proposed or flagged records (PE-21), a teammate's snoozes, assigners or sources, or a person's address, aliases, time zone or channel (PE-20: teammates read id and display name only). Team pins stay readable only under PE-02, whatever worlds are shared. | validator; API tests | ADR-0040; PE-01 to PE-20 |
+| PE-35 | **Events and erasure.** A work item's events stay in its owner's Desk world with `vis: []` (PE-12); a shared world's Story and Trace carry no line about a teammate's item. `world.share_changed` is written in the shared world by `tilo-api` after the record is written: `actor` the owner, `target` and `district` null, `vis: []`, `data` a team id and `on` or `off` (registry 1.5.0). A lapse writes nothing. Deleting a person (PE-16) deletes the shares they granted with their items; a share whose `granted_by` is no longer a person is never in force. | validator; API tests | ADR-0040; HR-1, FR-MEM-09 |
```

In "Terms" and the fixtures section of the same file: `read_team` joins the request list (`read_team`, a
shared-world work item's team view); a stamp list gains `granted_by` and `revoked`; a case may add the
`world_share` of the item's world and its `world_owner`; the events paragraph names `world.share_changed`
(registry 1.5.0).

`tilo_people` (not a contract, named so builders keep one oracle): `AccessRequest` gains optional
`world_share` and `world_owner` (validated in `_gate`); `ACTIONS` gains `read_team`; `READS` stays
`("read_full", "read_status")` so no other record kind can answer `read_team`; `VIEW_FIELDS["team"]`
is `("id", "title", "status", "due", "owner", "world_id")` and `project` refuses it for any kind but
`work_item`; `_work_item` handles `read_team` and `create` with a `world_id`; `INDEXES` gains `world_share`
(`world_id`, `team`) and `work_item.world_id`; `PeopleStores` gains `world_shares` as a required field, with no
in-memory default, so a production door that forgets it fails at build instead of silently losing shares (its
two constructors, `in_memory` and the Firestore door, and every test that builds `PeopleStores(...)` by hand
change in TSW-1 and TSW-2); `erase_person` removes shares granted by the person.
`tests/contracts/_people_lib.py` (the reference oracle) gets the same `read_team` clause so "decide implies
permits" holds.

### Fixtures

- `contracts/fixtures/world_share/valid/`: `active.json`, `revoked.json`.
  `invalid/`: `extra_role_field.json` (a `role` key), `team_is_a_user_id.json`, `world_is_a_team_id.json`,
  `granted_by_missing.json`, `revoked_missing.json` (null is allowed, absent is not), `id_not_derived_shape.json`.
- `contracts/fixtures/work_item/valid/open_in_shared_world.json` (a `manual_open` with `world_id`).
  `invalid/world_id_on_tilo_made_item.json`, `world_id_not_a_world.json`.
- `contracts/fixtures/events/valid/world.share_changed.json` (the id must be unique in that folder; check the
  folder-count pin in `packages/memory/tests`); `contracts/fixtures/events/invalid/world_share_changed_state_removed.json`.
- `contracts/fixtures/person/crossref/` (new keys `world_share`, `world_owner`; one rule per invalid file):
  valid: `teammate_reads_team_work_item`, `teammate_reads_done_team_work_item`,
  `world_owner_reads_members_team_work_item`, `member_creates_work_item_in_shared_world`,
  `owner_creates_work_item_in_own_world`.
  invalid: `pe31_world_share_revoked`, `pe31_world_owner_left_the_team`, `pe31_world_owner_rejoined_after_the_grant`,
  `pe31_share_granted_by_someone_who_is_not_the_world_owner`, `pe31_share_of_another_world`,
  `pe33_outsider_reads_team_work_item`, `pe33_item_owner_left_the_team`, `pe33_dropped_work_item`,
  `pe33_flagged_work_item`, `pe33_personal_work_item_read_team`, `pe33_teammate_reads_team_work_item_full`,
  `pe33_teammate_edits_team_work_item`, `pe33_teammate_marks_team_work_item_done`,
  `pe33_teammate_reads_pin_as_read_team`, `pe33_member_creates_item_in_world_not_shared_with_them`,
  `pe33_member_creates_item_for_another_person_in_shared_world`. The existing
  `invalid/pe03_teammate_reads_work_item.json` must stay invalid.

### Tests that must exist

Contracts and `tilo_people`: every fixture above; `decide` against the reference oracle on all crossref files
(parity property unchanged); a "team view carries exactly six keys" projection test; version-floor pins
loosened for `work_item` (`test_CC_PEOPLE_contract_files.py` pins 1.0.0 and the registry/event pins check
floors). Mutants that must die, each by a named case above: drop the actor's membership test
(`pe33_outsider_reads_team_work_item`); drop the revocation test (`pe31_world_share_revoked`); drop the
owner-membership lapse (`pe31_world_owner_left_the_team`); drop the "membership predates the grant" test
(`pe31_world_owner_rejoined_after_the_grant`); drop `granted_by.by == world owner`
(`pe31_share_granted_by_someone_who_is_not_the_world_owner`); drop `share.world_id == item.world_id`
(`pe31_share_of_another_world`); drop the item owner's membership (`pe33_item_owner_left_the_team`); drop the
status and flagged filters; let `read_team` answer for a pin.

`tilo-api` (one file per slice below): positive: a teammate reads events, layout, world, delivery and an
artifact of a shared world and sees the team items; the owner sees it unchanged. Negative, each a 404 with a
body byte-equal to an unknown world's: an outsider; a person of another org; a teammate after revoke; after
the owner left the team; after the reader left it; a world-bound session; an email, signed-link and demo
session; a teammate on `POST` pause, stop, answer, approve, share, cards, console, costs (404 as before);
`?team=`, `X-Tilo-Team` or a body team that names a team the reader is in but the share is not for; the
teammate's `vis: []` events absent; the owner's other worlds absent; an item with no `world_id` absent; a
proposed, flagged and dropped item absent; the sample world refused. Mutants: the helper accepts a team from
the request; the derived Viewer principal is handed to a write route; the session-shape test is skipped; the
share list is cached across requests (revoke then read in one test).

## Alternatives considered

**Items carry their own scope, mirroring pins** (`work_item.scope: personal | team`, a `team` id on the item).
It would let an item be team-visible without any world, and it makes "this one is for the team" explicit per
item. Rejected as the base because the user's decision is world-linked ("a team-shared world shows ..."):
two switches (the item's team and the world's share) can disagree, a revoked world share would not hide an
item that still names the team, a required field is a breaking change for every work-item fixture and
consumer (an optional one gives two ways to be personal), and it reopens PE-07/PE-08 for Tilo-made items. If
the user wants a team work list that exists without worlds, it can be added later as its own decision on
top of this one.

## Consequences

- Contracts change in TSW-0 only: new `world_share` 1.0.0, `work_item` 1.1.0, registry 1.5.0 with one
  type and one data schema, `people.rules.md` (PE-03, PE-12, PE-31 to PE-35). Regeneration steps for the
  builder: `contracts_codegen.py gen`, `node apps/web/scripts/generate-registry.mjs` then biome, and a grep for
  `x-version" ==` and `["version"] ==` pins. Nothing a team reader receives is new content: it is what a
  Viewer receives today, now reachable by a teammate.
- **Residual risks the user accepted by saying yes.** (a) Sharing is whole-world and retroactive: everything
  in the world's `vis: "all"` or district events, artifacts and runs, past and future, is readable by every
  member, including members added to the team later. (b) A member's item in a shared world is visible to all
  teammates as long as the member stays in the team, with no per-item "make private" (drop it). (c) Because a
  lapse writes no event, the Trace cannot say why access ended; the API's `in_force` and its reason word can.
  (d) Team members who are not in the Park install's single team (BQ-TEAMRT-2) are still directory members;
  the share dialog lists the owner's directory memberships (at most 8).
- Context aggregate (PR #851, `cx/context-panel-P2-owner`): its `worlds` and `work_items` sections can add
  team-shared worlds and teammates' team views through `readable_world` and `read_team`, and BQ-CTX-TEAMWORLD
  closes; its `pins` section is already PE-02. KnowledgeItem `scope: world | team` (ADR-0036, Proposed) should
  read this link, so "the team of a world" has one definition.
- Security paths: every slice below touches who can read what, so each gets a Sonnet security review before
  merge. The architect expects the usual findings (stamps taken from input, a check that runs on create but not
  on read, a derived principal that leaks into a write route, an oracle weaker than its rules); the test
  list above is written against them.

## Effort slices (each under 400 hand-written lines, fixtures and generated files excluded)

Order is fixed; test-writer writes each slice's failing tests first (`tests/<ID>`), builders do not edit
`contracts/`. IDs are proposals.

| Slice | Owner | Content | About |
| --- | --- | --- | --- |
| TSW-0 | architect | the contract and fixture changes under "Exact diffs", reference-oracle clause, pin loosening, regen | 230 |
| TSW-1 | people package | `tilo_people.world_share` (`share_id`, `in_force`), `decide` `read_team` and create with `world_id`, `INDEXES`, `PeopleStores.world_shares`, memory store, `erase_person` | 340 |
| TSW-2 | api | Firestore adapter for `world_shares`, `deps.readable_world` and the derived Viewer principal, session-shape test | 260 |
| TSW-3 | api | `PUT`/`DELETE`/`GET /worlds/{id}/team-shares`, record-then-event with the undo rules, `in_force` and reason word | 320 |
| TSW-4a | api | events, layout, world, delivery through `readable_world` (`redaction.py`, `runs.py`), owner-only negatives | 300 |
| TSW-4b | api | `GET /worlds` team rows (`access: "team"`, cursor re-scoped), the artifact version and manifest routes as they land (scope from the world record), `GET /worlds/{id}` `shared_with` | 330 |
| TSW-5 | api | `world_id` on create, `GET /worlds/{id}/work-items` (`read_team` rows), Context aggregate sections, BQ-CTX-TEAMWORLD closed | 330 |
| TSW-6 | web | share dialog with the consent copy above, sharing line and badge from `world.share_changed`, team work list | 350 |

TSW-1 to TSW-5 run in that order; TSW-4a and TSW-5 can overlap after TSW-2. TSW-6 starts after TSW-3 on
fixtures. Dev mode binds the dev owner to the path's world (`dev.py`), so tests use explicit principals, as the
existing viewer tests do.

## Decisions (contract lane, TSW-0, 13 Oct 2026)

TSW-0 landed `world_share` 1.0.0, `work_item` 1.1.0, registry 1.5.0 with `world.share_changed`, PE-03 and PE-12
amended, PE-31 to PE-35, fixtures and the reference clause `world_share_permits` in
`tests/contracts/_people_lib.py`. The text above is the accepted design; the contracts are what shipped, and
where this section and the text above differ, this section and the contracts win (BQ-TEAMWORLD-2).

1. **`world.share_changed.target` is the world's own id, not null.** `event.schema.json` is frozen and has
   no null target, so every "target null" above reads "target the world's id", as for `world.paused`.
2. **The crossref cases are in `fixtures/world_share/crossref/{valid,invalid}/`, not `person/crossref/`.**
   `tilo_people` PPL-10a and `tests/contracts` run every file of the latter with the old case keys and
   14 actions, and `decide` refuses `read_team` until TSW-1, so landing them there turns the base red. TSW-1
   runs the new folder through `decide` against `world_share_permits`, and may move the files into
   `person/crossref` in the change that teaches `CASE_KEYS` and the PPL-10a counts the new keys.
3. **Two refusals the accepted text left implicit**, each with a named invalid case: a share's `org_id` is
   the owner's org (PE-31) and a reader is of the item's org (PE-33). The teammate-edits, marks-done,
   reads-in-full and create-for-another-person cases are named `pe03_*`, since PE-03 refuses them.
4. **Not checkable on one record.** PE-32 and PE-34 have no record to validate (the `tilo-api` tests of
   TSW-2 to TSW-5 enforce them), and "`world_id` never changes" is a write-path refusal in TSW-1.

## Open questions

Logged as BQ-TEAMWORLD-1 in `docs/open-questions.md` with the defaults used here: org owners cannot revoke;
all districts, no per-share scope (a `districts` list is an additive `world_share` minor); no "make private"
edit; the assistant never reads team items; the dialog states past and future.
