# People, meetings, pinboards and calendar rules (CC-PEOPLE; person, meeting, minutes, work_item, pinboard_item, mention, calendar_entry, ui_action v1)

Source: `docs/prd-addendum-people-agents.md` (FR-MTG, FR-PA, FR-PB, FR-CAL), ADR-0014 (scope
extension to team scale) and ADR-0015 (these contracts and the privacy model). PRD 23.5 stays a hard rule: Tilo never monitors individuals. The schemas check one record; the
rules below need other records, another field or the clock. `tilo-api` (CL-PEOPLE) checks them
before it reads, writes or serves a record, and its tests run the same
`fixtures/person/crossref/` files as `tests/contracts`. Rule ids are stable. `PE-` is this
file's prefix (PRD 3.5 owns `EV-`, the PRD 3.1 principles own `PR-`).

Terms. A **member** of team T at time `now` is a person with a `memberships` entry for T whose
`assigned_by.by` is a person of the same org with `org_role: owner` and whose `assigned_by.at` is
no later than `now`. A **request** is `{actor, action, view}`: `read_full` (every field),
`read_status` (id, title, status, due), `read_busy` (busy intervals only, `calendar_entry.free_busy`),
`edit`, `confirm` (proposed to active/open), `mention` (tag a person) or `untag`.

| Rule | Rule | Checked by | Source |
| --- | --- | --- | --- |
| PE-01 | A personal pinboard item (`scope.kind: personal`) is read, listed, counted, searched, edited, removed and undone by `scope.user` only. No teammate, manager or org owner, and no assistant answer for another person, ever sees it; its events live in the owner's Desk world, which has no other viewer (PE-12). Its `owner` is null and it cannot be the subject of a mention (schema: a mention names a team). | validator (schema for `owner` and the mention team) | FR-PB-02, FR-PA-11; ADR-0014 |
| PE-02 | A team pinboard item that is `active` is read in full by the members of `scope.team`, and by no one else. A `proposed` or `removed` team item is read, confirmed or edited by its `set_up_by` person only. Membership counts only as defined above (an owner assigned it, no later than the request). | validator | FR-PB-01, FR-PB-06 |
| PE-03 | A work item is read in full by its `owner`. The person who assigned it (`assigned_by.by`, when not the owner) reads its status only (`read_status`), and only once it is no longer `proposed`; they never read `source`, `evidence` or `history`. Nobody else reads it. | validator | FR-PA-01, FR-PA-11 |
| PE-04 | A calendar entry is read in full by its `owner`. An entry shared with a team (`share` names the team, otherwise null) is also read in full by the members of that team. Everyone else, a teammate with a private entry included, can only `read_busy`: the interval, never title, source or attendee count. Org owners get no more than members. | validator | FR-CAL-06 |
| PE-05 | A meeting, its transcript and its minutes are read in full by the meeting `owner` only. An attendee, an assignee, a teammate and an org owner read nothing of them; an assignee sees their own work item (PE-03) and one evidence quote the API cuts from the transcript. Sharing minutes is an email, which is T3. | validator | FR-MTG-01, FR-MTG-10 |
| PE-06 | `mention`: only the `set_up_by` person of a team item, or Tilo for an item that person confirmed, tags a person; the tagged person is a member of the item's team at the request. A personal item takes no mention. `untag`: the tagged person always may remove themselves; the item's `set_up_by` person may remove anyone; no one else. A removed mention is never re-added: a new tag is a new record. | validator (schema for the team on a mention) | FR-PB-04 |
| PE-07 | `edit`: a personal item by `scope.user`; a team item by its `set_up_by` person only. `confirm`: a Tilo-made team item becomes `active`, and a Tilo-made work item from a meeting becomes `open`, only by the meeting Owner (the item's `set_up_by`, or `assigned_by.by`), who is recorded in `confirmed_by`; the schema requires `confirmed_by` on those states. Tilo never confirms its own item. | validator (schema for `confirmed_by`) | FR-MTG-06, FR-PB-06 |
| PE-08 | An item Tilo made carries `created_by.by: tilo` and a `source` (kind, reference, evidence) the person sees as "added by Tilo from <source>" (schema). On the personal board Tilo adds it as `active` and the person can undo it (history `undone`, status `removed`). On the team board it starts `proposed`. | schema; validator for the order | FR-PB-06 |
| PE-09 | "Get in touch" is a drafted message to the `set_up_by` person through their own `preferred_channel`. It is a send to another person: a new recipient, T3, a card, `approval.resolved` by the sender (PIN on WhatsApp), the outbox, `authz` on `data.transfer`. The recipient is the `set_up_by` person's address or number resolved by `tilo-api`, never one a model or the entry text names. | outbox OB-01, OB-05 | FR-PB-03, 10.4 |
| PE-10 | The assistant panel (FR-PA-12 to -19) acts only through a `ui_action` that validates against `ui_action.schema.json`; the closed union, the route list and the target kinds in it are the allow-list. A model's output that does not validate is dropped and the answer says so. `mark_done` and `snooze` act on the signed-in person's own work item; `tag` and `untag` follow PE-06; `draft_reply` makes a draft (T1) and sends nothing. A `navigate` target is a record the person may read under PE-01 to PE-05. No kind clicks, types, selects or sends. | validator; schema for the lists | FR-PA-14, FR-PA-16 |
| PE-11 | What the assistant reads for a person is what that person may read under PE-01 to PE-05, and nothing else. Every claim in `assistant.replied` cites `sources`; an `answered` outcome with no source is refused (schema). | validator; schema for `sources` | FR-PA-13, FR-PA-17, HR-1 |
| PE-12 | Events of the families `meeting` (minutes), `work_item`, `pinboard`, `mention`, `calendar` and `assistant` are written in a world with no Viewer, Approver or Team Lead scope: the Desk world of the person, or the meeting world of its Owner. Until ADR-0009 (owner-only `vis`) lands, `tilo-api` refuses to share such a world; afterwards these events carry `vis: []` wherever `district` is null. Team boards are read from their records, never from another person's event stream. The `summary` of these events names no title, quote, address or link, only display names and counts. | validator | SEC-07, FR-HIL-09 |
| PE-13 | What a synced Google event keeps is the title, the start and end, whether it is all day and a count of other attendees. No description, no attendee names or addresses, no conference link and no location is stored or sent anywhere (schema: no such field). Disconnecting Calendar, or deleting the person, deletes the person's cached entries (FR-MEM-09). A pinboard `url` passes the secret redactor before it is stored, since a bare token can look like a path (PE-02's team entries and personal ones alike). | schema; validator | FR-CAL-02, FR-CAL-08, 16.5 |
| PE-14 | A calendar write to Google is an outbox entry. An event on the person's own calendar with `attendee_count: 0` is T1 with the undo window; any entry with `attendee_count > 0` is T3 (`new_recipients`), always a person. | outbox OB-01; `config/autonomy.yaml` | FR-CAL-04 |
| PE-15 | Minutes: a `verified` decision or action item cites at least one utterance (schema). A resolved `owner` has `owner_text`; two or more people matching the same spoken name leave `owner` null and raise one question card (validator). `due` is a date computed by code from `due_text`, the meeting date and the assignee's `time_zone`, never by a model. | schema; validator | FR-MTG-04, FR-MTG-05 |
| PE-16 | A person's data is exported and deleted with them: persons, work items, personal pins, calendar entries and meetings they own (FR-MEM-09). Team items they set up stay, set up by "a former member". Transcripts are deleted at `delete_transcript_after`, minutes at `delete_minutes_after`. | validator; FR-MEM-09 script | 16.5, FR-MTG-10 |
| PE-17 | Directory changes are an org owner's: a `person` record is created, its `org_role` set and a `memberships` entry assigned only by a person of the same org whose `org_role` is `owner` (the first person of an org founds it and is its owner). A member cannot make themselves an owner or add themselves to a team; a `memberships[].assigned_by` that does not name such an owner grants nothing (PE-02). | validator | FR-PB-01, ADR-0014 |

## Fixtures

- `fixtures/<name>/valid|invalid/` for `person`, `meeting`, `minutes`, `work_item`,
  `pinboard_item`, `mention`, `calendar_entry`, `ui_action`; `fixtures/calendar_entry.agenda_item/`
  and `fixtures/calendar_entry.free_busy/` exercise those `$defs`. Invalid file names say the
  rule they break.
- `fixtures/person/crossref/{valid,invalid}/` (contracts-check skips this folder): each file is
  `{rule, note, now, persons, record, request}`. `persons` maps ids to `person` records, `record`
  is `{kind, data}` (a `pinboard_item`, `work_item`, `calendar_entry`, `meeting` or `mention`
  with the `pinboard_item` it tags in `pin`), and `request` is `{actor, action, view}`. Every part
  is shape-valid. A valid file is a request the rules grant (`rule` is null); each invalid file
  is a request they refuse and breaks only the rule its `rule` field and name state. The
  `tilo-api` tests run the same files.
- `fixtures/events/valid/<type>.json` for each new event type (registry, below).

## Events (registry 1.1.0)

`meeting.minuted`, `work_item.created`, `work_item.changed`, `pinboard.item_added`,
`pinboard.item_changed`, `mention.added`, `mention.removed`, `calendar.synced`,
`calendar.entry_proposed`, `calendar.entry_changed`, `assistant.asked`, `assistant.replied`:
none is a side effect and none carries `authz`; a send, an invite or a calendar write is an
outbox entry with its own `data.transfer`. Payloads carry ids, counts and enums, never a title,
a transcript line, a message body, an address or a link: an assistant message points at the
redacted raw-archive record (`message_ref`). `meeting.started` and `meeting.ended` gain
optional `meeting_id` and, on `meeting.ended`, `reason` (1.1.0, additive).
