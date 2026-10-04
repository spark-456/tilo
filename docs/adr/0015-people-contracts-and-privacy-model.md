# ADR-0015: Contracts for people, pinboards, calendar and the assistant panel

- Status: Proposed (2026-10-05, architect; ticket CC-PEOPLE). Everything in it is additive, so it
  needs no major bump, but it rests on ADR-0014, which waits for the user.
- Deciders: user (approval of ADR-0014), architect (proposal)
- Requirement: FR-MTG-03 to -07, FR-PA-01, -11 to -19, FR-PB-01 to -08, FR-CAL-01 to -08
  (`docs/prd-addendum-people-agents.md`); PRD 9.5, 10.1, 10.4, 15.2, 16.5

## Context
The addendum adds records (people, meetings, minutes, work items, pins, mentions, calendar
entries), events, and a side panel whose model may suggest UI actions. Each needs a contract
before three lanes build in parallel. Several choices decide privacy and safety and cannot be
left to the builders.

## Decision
1. **Records are the source of truth; events are the audit trail.** Boards, plates and calendars
   are read from records (`orgs/{org}/...`) through `tilo-api`, never from another person's event
   stream. Each change writes one event in the *actor's* world: a person's persistent **Desk
   world** (an Outpost-tier routine world created lazily, one writer, scale to zero) or the
   meeting's world. Events carry ids, counts and enums, never titles, transcript lines, bodies,
   addresses or links. (Rules PE-12, PE-13.)
2. **New schemas** `person`, `meeting`, `minutes`, `work_item`, `pinboard_item`, `mention`,
   `calendar_entry`, `ui_action`, and new `common` ids (`wi_`, `mt_`, `pb_`, `mn_`, `ce_`, `tm_`,
   utterance ids), `maker`, `record_ref`, `opaque_ref`. No existing field changes. Twelve new event
   types in five new families (`work_item`, `pinboard`, `mention`, `calendar`, `assistant`) plus
   `meeting.minuted`; `meeting.started` and `meeting.ended` gain optional fields. The registry and
   `registry.schema.json` go to 1.1.0, `common.schema.json` to 1.1.0.
3. **Privacy is structural.** A personal pin has no owner and no mention (schema); a mention names
   a team (schema); a calendar entry stores no description, attendee names, link or location
   (`additionalProperties: false`); a meeting record has no field that can hold a join link;
   minutes cite utterance ids, not text. The read rules PE-01 to PE-07 are validator rules with
   crossref fixtures that both `tests/contracts` and `tilo-api` run.
4. **Membership is a role grant like any other.** `person.memberships[]` carries
   `assigned_by: {by, at}`; it counts only when `by` is an org owner and `at` is no later than the
   request (the pattern of Team Leads and Approvers, ADR-0006).
5. **Tilo-made means unconfirmed.** `maker.by: tilo` forces a `source`; a Tilo-made team pin,
   work item from a meeting, or calendar proposal needs `confirmed_by` to leave `proposed`
   (schema). Tilo never confirms its own item (PE-07). Personal-board entries are `active` at once
   with an undo.
6. **The assistant's action list is data.** `ui_action.schema.json` is a closed union (`navigate`
   with a closed route list and typed target, `mark_done`, `snooze`, `draft_reply`, `tag`,
   `untag`). The panel executes only documents that validate; a model's output that does not is
   dropped. No kind clicks, types, selects, reads the DOM or sends. `assistant.replied` records the
   outcome, who decided (`rules` or `model`), the `sources` every claim cites and the validated
   action; an `answered` outcome with no source is invalid (HR-1).
7. **No new action type or card kind.** A follow-up, invite or minutes email is `send_email` with
   the `new_recipients` modifier, so T3. A calendar write is an outbox entry (T1 on the person's own
   calendar with no attendees, T3 otherwise); its action ids and tiers arrive with CC-PEOPLE-2
   (config), not in the contracts. A reminder is a `needs_you` card with `done`, `snooze`,
   `not_mine` (all reversible) or an `alert.raised` nudge.
8. **ADR-0009 does not block.** Owner-only `vis` would be the clean way to keep transcript-derived
   events from a Viewer. Until it lands, PE-12 keeps these events in worlds with no viewer and
   refuses to share such a world; afterwards they carry `vis: []` where `district` is null.
9. **Tilo writes only from sources the person owns.** Tilo adds a personal pin, work item or
   calendar proposal for person P only from P's own meeting, mail or request. What it derives from
   another person's meeting reaches P only as one action item the meeting's Owner released: a work
   item the Owner confirmed on minutes the Owner confirmed (`meeting.minutes_confirmed_by`), and a
   calendar proposal that cites that item (`mt_x#aiN`), never a bare transcript, a rejected item or
   a personal pin. A Google sync writes only the connected person's own entries.
   Proposed items are read by no one but the Owner, in the minutes. A person cannot push an item
   onto another plate. (PE-03, PE-08)
10. **Free/busy is for teammates.** Busy intervals of accepted entries, over at most 31 days, go
    to people who share a team with the owner and to no one else; titles never leave the owner
    except in an entry the owner shared with a team they are in. (PE-04)
11. **Stamps are written by `tilo-api`**, never from input, and are re-checked on read, confirm
    and tag (a confirmation names the person who owns the decision and is dated in range; a
    setter is the creator, or the owner of the source meeting for Tilo's entries). Directory
    changes are an org owner's. (PE-17, PE-19)
12. **Flagged content stays flagged.** `flagged` is required on work items, pins and calendar
    entries; anything built from a flagged record is T3 with `safety_flag`. (PE-21)
13. **Fixed counts are not hard-coded.** Team size and per-person team limits live in
   `config/personal.yaml`, not in the schemas, except `memberships` maxItems 8 as a safety bound.

## Alternatives considered
- *Events as the only store* (replay to rebuild boards): rejected; a teammate would need another
  person's stream and `vis` cannot express per-person privacy.
- *Reusing `work_item` for calendar entries*: rejected; a Google event is not a task, has no owner
  semantics, and needs sync state. The merged agenda is a read-model row (`agenda_item`).
- *A free-form action string for the panel, validated by regex*: rejected; a closed union is
  testable and generates types.
- *`channel.message_in` for panel messages*: rejected; its L2-instruction semantics (OB-01) must not
  widen to a new channel.

## Consequences
- Builders in three lanes start from generated types and fixtures on day 1.
- `tilo-api` must run `fixtures/person/crossref/` in its tests (CL-PEOPLE).
- The web app regenerates `registry.generated.ts`; AG-WEB maps the new types.
- Open: a `team` record with a display name; WhatsApp delivery for "get in touch" (needs an outbox
  connector action).
