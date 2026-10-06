# ADR-0016: Contracts for people, pinboards, calendar and the assistant panel

- Status: Accepted (2026-10-05, user, confirmed in chat; ticket CC-PEOPLE).
  Everything in it is additive, so it needs no major bump. It rests on ADR-0015. Renumbered from 0015.
  Amended 2026-10-06 by the meeting link check (decision 14, architect, issue #464; Proposed until merged).
- Deciders: user (approval of ADR-0015), architect (proposal)
- Requirement: FR-MTG-01 (decision 14), FR-MTG-03 to -07, FR-PA-01, -11 to -19, FR-PB-01 to -08, FR-CAL-01 to -08
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
14. **Meeting text holds no link (`meeting` 1.2.0, 2026-10-06, issue #464).** The 1.1.0 check
    (`://` plus three hosts) let `g.co/meet/...`, `teams.live.com/meet/...`, `webex.com/meet/...`,
    a bare `example.com/x` and invisible characters that split `://` (U+034F, U+FE0F, U+3164,
    U+2800) reach a stored meeting through `POST /v1/meetings`. The title, agenda titles and
    attendee names now share one rule (PE-13), with a test that the three copies stay equal:
    (a) no `://` and no backslash form of it; (b) no meeting host (meet.google.com,
    teams.microsoft.com, teams.live.com, zoom.us, webex.com, whereby.com), alone or as a suffix
    (`acme.zoom.us`), in any case, bounded by characters that cannot continue a host name;
    (c) no bare `host.tld/segment`: a last label of 2 to 63 ASCII letters other than `js`, an
    optional port, a slash and a path character (this also catches g.co/meet and services not
    listed); (d) no Cc, Zl, Zp or Basic Multilingual Plane Cf (the class of `quote_line`, PE-24),
    no Hangul filler, U+2800 or unassigned default-ignorable code point; (e) an invisible
    combining mark (U+034F, U+17B4, U+17B5, the Mongolian free variation selectors, U+FE00 to
    U+FE0F) only after a non-ASCII character, or U+FE0E and U+FE0F after a keycap base (`#`, `*`,
    a digit), so emoji keep their variation selector (BQ-MLINK-4). The patterns are read alike by
    Python `re` (jsonschema), ECMA-262 with and without the `u` flag (ajv in `apps/web`) and, for
    `pattern`, pydantic's Rust engine: no inline flags, no `\p{}`, lookahead only inside `not`,
    which the generated models drop. Astral characters cannot be named that way, so they are the
    validator's: `clean_line` removes astral Cf, and `tilo-api` must also remove or refuse the
    other astral default-ignorables (U+E0000 to U+E0FFF) before the schema check (BQ-MLINK-3).
    Accepted false positives: a dotted name ending in a TLD-like word and followed by a slash
    (`ASP.NET/Blazor`, `St.Louis/Chicago`) and a meeting host named by its domain (`zoom.us
    licence`) are refused. Kept: `Q4 plan v2.1`, `a.b notes`, `Node.js/React`, `1:1 w/ Priya`,
    `zoom.usage`, `example.com` without a path, emoji, keycaps and non-Latin scripts. Left to
    later work (BQ-MLINK-2): a scheme split by a visible space, fullwidth or ideographic dots and
    letters that IDNA maps to ASCII, IP hosts, app schemes without `//`, dial-in numbers and PINs.
    The rule is stricter, not wider; it is a minor bump because PE-13 already said these fields
    hold no link and none of the 115 meeting records in the repository (fixtures, streams, web
    copies) changes verdict (BQ-MLINK-1).

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
- Open: a `team` record with a display name.
- Decision 14: a writer that copies text from outside (a calendar title, a participant's display
  name) gets a refused record when that text holds a link or a hidden character; the meeting bot
  and `tilo-api` must clean or replace such a name before they write (BQ-MLINK-5).
