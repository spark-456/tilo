# ADR-0020: The evidence-quote read model

- Status: Accepted by the user, 2026-10-05 ("accept all of #381": Option A with the new transcript contract and optional `meeting.world_id`; an assignee sees exactly one quote, no meeting title, and nothing if the transcript is flagged). Proposed earlier the same day by the architect (BQ-PPL40a-1). It adds a new contract, an optional
  field on `meeting` and four rules to the people contracts (all additive), so it needs the user's
  approval before ticket CC-PEOPLE-3 makes it.
  This PR is docs only: nothing in `contracts/`, `config/` or code changes here. ADR-0019 is taken
  by the WhatsApp-removal rules on `fix/CH-RM-contracts`. Lands with ADR-0021 (the plate).
- Deciders: user (approval), architect (proposal)
- Requirement: FR-PA-03, FR-MTG-02, FR-MTG-04, FR-MTG-10, FR-PA-11
  (`docs/prd-addendum-people-agents.md`, section 6.3); PE-03, PE-05, PE-08, PE-12, PE-20, PE-21
  (`contracts/people.rules.md`); ADR-0016, ADR-0018; HR-1 (PRD 9.4); SEC-01 (PRD 16.1)

## Context
1. S-26 shows the evidence behind every minutes item, and S-27 shows it under a work item made
   from a meeting (PPL-40a, PR #376). Minutes and work items cite utterance ids only
   (`minutes.schema.json` `$defs/evidence`, `work_item.schema.json` `source.evidence`): ADR-0016
   decision 3 keeps transcript text out of both, and `fixtures/minutes/invalid/transcript_text_field.json`
   enforces it.
2. PE-05: the meeting owner reads the meeting, transcript and minutes in full; an assignee reads
   their own confirmed work item "and one evidence quote the API cuts from the transcript". No
   contract names that quote, so the screen keeps its own `EvidenceQuote {speaker, text}` over
   `apps/web/src/people/fixtures/quotes.json`, the one fixture with no schema.
3. The transcript is an artifact version (FR-MTG-02; ADR-0018 store, `screening`, `redacted`),
   pinned by `minutes.transcript` and deleted at `meeting.delete_transcript_after` (30 days,
   FR-MTG-10). Its content has no contract either: the meet-bot writes `transcript.jsonl` lines of
   `{speaker, text, t}` with no ids, and ingest assigns `u0001`.
4. The addendum (6.3) says an assignee sees "their item, the meeting title and one evidence
   quote"; PE-05 (the contract, which wins) gives no title.

## Decision (Option A)
1. **A quote is computed, never kept.** `tilo-api` cuts it per request from three stored things:
   the record that cites the utterance, the meeting record, and the transcript version the minutes
   pin, read through the artifact store with the meeting's own `Scope` (its org, its world, its
   owner, all taken from the stored meeting, never from the request; BQ-273). Nothing new is
   stored. A quote is never written to an event,
   a log, the raw archive, an email or digest, a notification, a cache that outlives the request,
   or a model prompt (the assistant panel cites `record_ref`s, which have no transcript kind).
2. **It expires with the transcript.** After `delete_transcript_after`, a sweep, or a deleted or
   discarded meeting (PE-19 tombstone), the quote's state is `expired`; no copy outlives the
   30-day transcript, while the minutes stay 90 days and keep their ids.
3. **Who gets what.**
   - The meeting owner: a quote for every utterance a minutes item cites (up to 20 per item).
   - A work item's owner who is not the meeting owner: at most one quote, only while PE-03 lets
     them read the item (`open`, `done` or `dropped`; confirmed by the meeting owner on confirmed
     minutes, PE-08), and only for an utterance cited by both the work item and the minutes action
     item its `source.ref` (`mt_x#aiN`) names. The quote is the lowest such id present in the
     pinned version (BQ-265). No meeting title (PE-05 over the addendum; BQ-266).
   - Everyone else (the assigner reading status under PE-03, attendees, teammates, org owners):
     404, with no sign that a quote exists (the AR-03 pattern).
4. **Redaction for a viewer who is not the meeting owner.** The quote is `withheld` unless the
   transcript version is `screening: clean` and the minutes are not `flagged` (BQ-267). A shown
   quote has email addresses, phone numbers and URLs replaced by `[removed]` and passes the secret
   redactor (SEC-01). Its speaker is the directory display name (PE-20) of the person the label
   resolved to through `meeting.attendees` (PE-15), only if the viewer shares a team with that
   person; otherwise null, shown as "A participant" (BQ-268).
5. **Untrusted text, for every viewer.** Code removes control and format characters (Unicode Cc
   and Cf, so no bidi override), cuts at 240 characters on a word boundary with `truncated: true`,
   and the web renders it as plain text: no Markdown, HTML or link detection.
6. **Honest states (HR-1).** `shown` only when the utterance exists in the pinned version;
   `missing` when it does not (an FR-MTG-04 fault: logged by id for PPL-51, never shown as backed);
   `expired`; `withheld`. A quote that is not `shown` has `text` and `speaker` null. An item that
   cites nothing says "No evidence cited", as S-26 does today.

## Options
| Option | What | Verdict |
| --- | --- | --- |
| **A (recommended)** | Computed per request from the pinned transcript; a transcript content contract plus a quote read-model row; four rules | ~0.5 day contracts (CC-PEOPLE-3), ~1 day `tilo-api` (PPL-11a), ~0.5 day web (PPL-41) |
| B | Copy the quote text into minutes items or onto the work item at confirmation | Rejected: transcript text outlives the 30-day transcript, breaks ADR-0016 decision 3, and puts another person's words into the assignee's export (PE-16) |
| C | Send the transcript (or a window of it) to the client, which cuts the quote | Rejected: an assignee would receive more than one quote (PE-05) |
| D | Carry the quote in `work_item.created` or `meeting.minuted` | Rejected: PE-12 and the registry keep transcript lines out of events (`fixtures/events/invalid/meeting_minuted_with_transcript_text.json`) |

## Contract changes (ticket CC-PEOPLE-3, T1; all additive)
- **New `contracts/transcript.schema.json` 1.0.0, title `Transcript`:** the content of a
  transcript artifact version (`application/json`, inside ADR-0018's 2,000,000-byte text cap):
  `{v: "1.0", meeting_id, utterances}`; `$defs/utterance` `{id: utterance_id, speaker (1..80,
  the label as captioned or uploaded, untrusted, no control characters, no "://"), t_ms (integer
  >= 0), text (1..4,000, no control characters)}`, at most 10,000 utterances. Ingest (FR-MTG-02)
  writes it; ids strictly increase (validator rule).
- **`$defs/evidence_quote`** in the same file, the read-model row (never stored):
  `{meeting_id, transcript: artifact_ref without label, utterance_id, state: shown | missing |
  expired | withheld, speaker: string 1..80 | null, text: string 1..240 | null, truncated}`,
  with `if state != shown then text and speaker are null`. `$defs/evidence_quotes`:
  `{quotes: [evidence_quote]}`, at most 20.
- **`contracts/people.rules.md`:** PE-22 (decisions 1 and 2), PE-23 (decision 3), PE-24
  (decisions 4 and 5), PE-25 (decision 6). The crossref format gains an optional `minutes` beside
  the source `meeting`, a `read_quote` view and a `utterance_id` on the request. Cases: owner
  reads; assignee reads one; refused for a second quote, a proposed item, unconfirmed minutes, an
  utterance the minutes item does not cite, the assigner, an attendee, a teammate, an org owner,
  another org's meeting; `withheld` for a flagged transcript; `expired` after the sweep.
- **Fixtures:** `fixtures/transcript/{valid,invalid}`, `fixtures/transcript.evidence_quote/{valid,invalid}`
  (invalid: shown without text, withheld with text, text over 240, text with a newline, a
  labelled transcript ref). Synthetic names and example.com only.
- **`meeting.schema.json` 1.0.0 to 1.1.0:** optional `world_id` (absent, never null, ADR-0011),
  the world that holds the meeting's transcript and minutes, written by `tilo-api` when it creates
  that world. The record has no world today, and the artifact store's `Scope` needs one. A meeting
  without it yields no quote (fails closed; BQ-273).
- **No event, registry, `minutes` or `work_item` change.** Generated types regenerate.

## Builders (after T1)
- PPL-11a (`tilo-api`): `GET /v1/meetings/{id}/quotes?ids=` (owner) and
  `GET /v1/work-items/{id}/quote` (item owner), one cutter function, the crossref files in its
  tests. Ingest (FR-MTG-02) writes `Transcript` documents.
- PPL-41 (web): S-26 and S-27 read `EvidenceQuote` from `@tilo/contracts`; `quotes.json` becomes
  `evidence_quote` fixtures validated by the PPL-40a fixture test.
- PPL-50, PPL-51: E-PRIV cases for quotes (a second quote, a non-assignee, a flagged transcript, a
  quote after 30 days: 0 leaked characters).

## Security notes
- Owner-only by default; the assignee path is the one cross-owner read in the people model and
  returns at most one utterance, never the artifact, and only through the cutter.
- The scope for the artifact read (org, world, owner) comes from the stored meeting the checked
  `source.ref` names; a missing world, or a mismatch of org, owner, `assigned_by.by` or
  `confirmed_by`, fails closed (PE-19).
- No cross-world leak: no quote enters an event, so no world stream or Viewer ever carries one;
  the panel and digest never receive quote text.

## Consequences
- S-26 and S-27 can go live without a transcript endpoint for assignees.
- Quotes disappear honestly at 30 days; minutes then show ids with "Transcript deleted".
- FR-MTG-02 now has a content contract to write, which the minutes skill (PPL-20) also reads.

## Open questions (`docs/open-questions.md`)
- BQ-265: which single quote an assignee gets. Default: the lowest cited id both records share.
- BQ-266: the meeting title for an assignee. Default: none (PE-05 wins over addendum 6.3).
- BQ-267: a flagged or unscreened transcript. Default: `withheld` for non-owners.
- BQ-268: length, speaker and masking. Default: 240 characters, a teammate's display name or
  null, emails, phone numbers and URLs masked for non-owners.
- BQ-273: which world holds a meeting's transcript. Default: an optional `meeting.world_id`.
