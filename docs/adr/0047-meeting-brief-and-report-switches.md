# ADR-0047: The meeting brief, and the owner's brief and report switches

- Status: **Accepted** (16 Oct 2026). The product owner approved it at 01:15 IST on 16 Oct 2026, in the supervisor
  chat, with the words "approved, we will test it all", in reply to the request to approve ADR-0024 amendment 5 and
  this contract (then "ADR-0045, proposed number") as described in `agy-bridge/reports/MEETING-LOOP-DESIGN.md`
  sections 1(c), 2(c), 3(c), 6 and 7. The supervisor relayed the quote; the architect did not see that chat. The
  change is additive: `meeting.schema.json` goes from 1.2.0 to 1.3.0, `meeting_brief.schema.json` 1.0.0 is new, and
  every stored record and fixture stays valid. (Numbered 0047: 0045 is on `cx/INVITE-LINK` and 0046 on
  `contracts/INVITE-LINK`, both at 16 Oct.)
- Deciders: product owner (the meeting loop), architect (contract shape and rules)
- Requirement: FR-MTG-01, FR-MTG-03, FR-MTG-06, FR-MTG-08, FR-MTG-10, FR-CHN-18, FR-MTR-04; PE-05, PE-13, PE-15;
  HR-1; ADR-0018, ADR-0020, ADR-0024 (amendment 5, same approval)
- Rules: MB-01 to MB-12 in `contracts/meeting_brief.rules.md`. Questions: BQ-MLOOP-1 to BQ-MLOOP-6.

## Context
1. Agenda shows "Ask Tilo for a brief" and a brief switch, but both only toast: there is no route, contract or
   stored switch, and the join, pins and brief switches are React state that a reload loses.
2. The inputs already exist as Tilo data: the meeting's `agenda` (at most 20 lines with planned minutes), its
   `series`, the confirmed minutes of earlier meetings of that series (decisions, action items with work items), and
   the work items' status. No Google call is needed.
3. After a meeting the owner wants a report by mail. Mail to attendees is T3 always (FR-MTG-08). Mail to the owner
   alone goes through the owner's digest (`Digest.enqueue_text`, FR-CHN-18), which sends only under the owner's
   standing policy and keys one mail per kind per UTC day, so a second meeting the same day would be dropped.
4. `brief.schema.json` is the intake brief (FR-INT-03); the meeting's brief needs another name.

## Decision
1. **`meeting.schema.json` 1.3.0 (additive).** Three optional fields, each absent and never null (like `world_id`,
   ADR-0011): `brief_requested: boolean` and `auto_report: boolean`, the owner's switches; `brief`, an
   `artifact_ref` without `label` that pins the latest brief version. tilo-api writes `brief` when it stores a brief
   and never takes it from a request. A discarded or deleted meeting keeps no `brief` (schema, FR-MTG-10).
2. **`meeting_brief.schema.json` 1.0.0 (new),** the content of a brief artifact version (`application/json`):
   `v` ("1.0"), `meeting_id`, `generated_at`, `flagged`, `agenda_points[{title, minutes, talk_points[{text,
   evidence[]}]}]` and `carry_over[{text, kind: decision | open_action, from_meeting, item}]`. Code copies the agenda
   lines (MB-04) and the carry-over (MB-06, MB-07); a model writes only talk-point text. Each talk point cites one to
   ten sources: `{kind: "agenda", index}` (a line of this meeting's agenda) or `{kind: "prior", meeting_id, item}`
   (an item of prior confirmed minutes: `ai<n>` an action item id, `d<n>` the decision at index n, because decisions
   have no id). `carry_over` also names its `item`, so its copied text can be checked (a decision cites `d<n>`, an
   open action `ai<n>`, schema). Every text is one link-free line with the meeting title's checks, at most 240
   characters. Caps: 20 agenda points, 5 talk points each, 30 carry-over items. No recipient, time, address or link
   field exists.
3. **Routes (tilo-api).** `GET /v1/meetings/{meeting_id}/brief` answers 200 with the pinned brief, or 404
   `not_ready` when there is none (MB-02); `POST /v1/meetings/{meeting_id}/brief` with body `{}` makes one now and
   answers 200 with it (MB-03). Both are owner-only: anyone else gets the one 404 `not_found` of a missing meeting,
   checked before `not_ready` (MB-01, PE-05). `MeetingEditIn` (`PATCH /v1/meetings/{meeting_id}`) gains
   `brief_requested` and `auto_report` as strict booleans (MB-10).
4. **The model.** One call on the existing role `meeting_analyst` (`config/models.yaml`), so no config shape
   changes. The template is `prompts/meeting_analyst/meeting_brief.md`: the design names `prompts/meeting_brief.md`,
   but `tilo_providers.prompts.load_prompt` reads `prompts/<role>/<template>.md` (`prompts/README.md`). The prompt
   lists the agenda lines and the prior items as delimited, untrusted data with their source ids; the reply is
   checked by code (MB-05) and screened (MB-08). Metered on the owner's existing per-user allowance like minutes.
5. **The prior set (architect default).** The latest earlier meeting of the same owner and non-null `series` whose
   minutes the owner confirmed (MB-06). Widening it later (more meetings) needs no contract change.
6. **No new event type.** A brief is an artifact: `artifact.created` the first time, `artifact.versioned` after,
   both registered, in the meeting's world. Setting `meeting.brief` writes no event, like `world_id` (MB-12).
7. **The switches stay inside the owner's own reach (MB-10).** `brief_requested` lets the T-15 sweep (after
   submission) make the brief; until then it has no automatic effect and the panel promises none. `auto_report`
   lets Wrap-up hand the report to the owner's digest under a per-meeting key; it sends only under the owner's own
   `send_email` policy (T2, known recipient, L3 by policy only) and otherwise sends nothing. No switch changes a
   tier, a recipient or FR-MTG-08's T3 card for attendees.

## Security
- Owner-only reads and writes, the PE-05 404 for everyone else and the owner check first, so `not_ready` is no
  existence oracle (MB-01).
- The model's reply is untrusted: it writes only talk-point text, cites only sources code offered, and a failing
  point is dropped, never repaired (MB-05). A flagged run keeps only the code-copied parts (MB-08). No field can hold
  a recipient, a time or a link, and every line refuses links and hidden characters (schema, MB-11).
- Making a brief is read-only: no outbox entry, gate, card, policy or message (MB-12). The report switch reuses the
  digest's policy path unchanged; it widens no tier.
- Deletion: a discarded or deleted meeting drops `brief` (schema) and its versions (MB-09). A stored brief copies
  text from prior minutes; `GET` stops serving it once a cited meeting's minutes are gone (MB-09).

## Consequences
- Contract changes: `meeting.schema.json` 1.3.0, `meeting_brief.schema.json` 1.0.0, `meeting_brief.rules.md`,
  fixtures for both, regenerated types. `people.rules.md` is unchanged: MB-01 applies PE-05 to the brief.
- Builder tickets (acceptance tests first): the brief API, generator and prompt with fake-provider tests; the
  Agenda brief panel and the two switches; Wrap-up's report to the owner's digest with a per-meeting key; and the
  host-card sentence of ADR-0024 amendment 5.
- Follow-up: the stored copies of prior-minutes text in older brief versions outlive those minutes until the
  retention sweep deletes brief versions that cite deleted minutes; `GET` already refuses to serve them (MB-09).
  The T-15 sweep, push and mail delivery of briefs are after submission.

## Alternatives
- *One `brief` object stored on the meeting record:* the meeting record would grow by up to 20 x 5 lines, and
  versioning, the hash check and retention already exist for artifacts.
- *Let the model write carry-over:* it could claim a decision nobody took; copying by code with an item id is
  checkable.
- *A new `meeting.briefed` event:* the artifact events already render it; a new type needs a registry entry and
  world, HUD, Story and Trace effects for no new fact.
