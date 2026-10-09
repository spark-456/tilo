# PEOPLE-SEAMS-1: the four people seams on real backends

Ticket: `deps.get_plate_sources`, `get_source_owners`, `get_desk_worlds` and `get_meeting_worlds` answered 503 on Cloud
Run. They now read and write the API's own store (`tilo_api.seams_store`), so they are 503 `not_configured` exactly when
`deps.get_store` is (no `TILO_API_STORE=firestore` plus project); a demo session gets its own in-memory store, dev mode
keeps its overrides (`dev.py`). Each seam is the owner-scoping boundary: every read is keyed by the signed-in user, an id
that does not match its schema never reaches a backend, and unknown, malformed or ambiguous means nothing (`None`, `[]`).

| Seam | Reads or writes | Scope and bounds |
| --- | --- | --- |
| `get_plate_sources().cards(u)` | `CardStore.plate_facts(u)` of every run in the process | open cards of worlds `u` owns (the stored world must name `u` too) and open gates whose live Approver assignment names `u`; one per group; at most 500 |
| `.runs(u)` | the owner's tasks (`DurableStore.load_owner_tasks`, 500), their worlds and cached events | `world.started`, no `world.completed/failed`, not paused; `blocked` while an `agent.blocked` is unanswered (BQ-PEOPLESEAMS1-2); goal and date from the brief |
| `.mail(u)` | `orgs/{org}/mail_triage` where `owner == u` | `needs_reply`, not flagged, well formed; 500; none without a Firestore client (BQ-PEOPLESEAMS1-1) |
| `get_source_owners().owner_of(kind, ref)` | `mail`: the triage record by `message_id`; `request`: the world or task record | one holder or nobody; ref and kind checked first |
| `get_desk_worlds()` | `desk.ensure_desk` (the panel's Desk) | org must be `deps.ORG_ID`, user a `u_` id; an id held by another owner is refused (503), never adopted; `desk_owner` is the cached record's owner or `None` |
| `get_meeting_worlds()` | one persisted world `w_mtg_<24 hex>` per meeting | created once (create precondition; a lost race reads the winner), same id on repeat, another owner refused |

Tests: `test_PEOPLE_SEAMS_1_sources.py` (owners, strangers, hostile ids, huge lists, restart, mail),
`test_PEOPLE_SEAMS_1_worlds_and_routes.py` (Desk and meeting worlds with the real `WorldWriterAdapter`, the plate, a
Viewer principal, mail-sourced work item, the meeting-world route, deployed with no config). No network, no credentials.
Left for later: a durable card store and tilo-channels' triage writer (BQ-PEOPLESEAMS1-1, -3).
