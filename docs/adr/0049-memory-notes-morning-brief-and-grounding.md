# ADR-0049: "Tilo remembers" notes, the morning brief, and per-account grounding

- Status: **Accepted** (16 Oct 2026). The product owner chose, in the supervisor chat at about 02:20 IST on 16 Oct
  2026, as MUST for the 17 Oct submission "A1 agents know the user's context", "B1 Morning brief: today's meetings,
  important mail, deadlines" and "B9 Memory of preferences ('I prefer morning meetings', 'my manager is X') as a
  simple 'Tilo remembers' list you can edit", and as NICE "B3 inbox triage (bills/deliveries/appointments ->
  to-dos)" and "A18 daily/weekly digest to yourself", and replied "okay proceed". At about 03:00 IST the owner asked
  "We need to use some vectordb or something similar to ground ai's reponses for each account right?", and the
  supervisor added per-account retrieval grounding to this scope (decision 5). The supervisor relayed both quotes;
  the architect did not see that chat. All changes are additive: three new contracts at 1.0.0, no existing schema,
  event type or config shape changes. (Numbered 0049: 0045 to 0047 are on `cx/INVITE-LINK`, `contracts/INVITE-LINK`
  and `contracts/MEETING-BRIEF`; 0048 is `contracts/WORKSPACE-TOOLS`' read tools, whose `read_events` and
  `search_email` this ADR uses and does not define.)
- Deciders: product owner (scope), architect (contracts and rules)
- Requirement: PRD 13.1 (Preferences, Artifact memory), FR-INT-05, FR-MEM-05, FR-MEM-09, FR-PA-06, FR-CHN-18,
  FR-MTR-04, EFF-01, EFF-03, EFF-04, PL-01, PL-06, SEC-04, HR-1, HR-7; PE-01 to PE-05, PE-08, PE-12, PE-24, PE-27,
  PE-31 to PE-33; USET-07, USET-08; ADR-0018, ADR-0030, ADR-0040, ADR-0044, ADR-0047, ADR-0048
- Rules: MI-01 to MI-10 (`contracts/memory_item.rules.md`), MO-01 to MO-12 (`contracts/morning_brief.rules.md`),
  RT-01 to RT-10 (`contracts/retrieval_chunk.rules.md`). Questions: BQ-MEMB-1 to BQ-MEMB-9.

## Context
1. Memory is not live (capability audit, 16 Oct): planning uses `InMemoryPreferenceStore` and nothing writes it,
   `memory.saved` has no emitter, and no Firestore vector index or typed `embed` exists (ADR-0030's MEM30 tickets
   were never built). The Quick side assistant (`POST /intake` mode quick) knows nothing about the person.
2. The plate (PE-27), the owner-only digest (`DigestService.enqueue_text`, one mail per kind per UTC day), the
   Desk world (PE-12), the Scheduler's every-minute tick with its sweeps, `POST /v1/work-items` with a mail source
   (PE-08) and the artifact store (ADR-0018) exist. ADR-0048 adds read tools on tilo-connectors.
3. ADR-0030 decided that preferences are written by code from the person's own acts, never extracted by a model
   from sessions, mail or documents (stored prompt injection), and that artifact memory is offered, never silently
   reused. USET-08 promises that profile text never enters the raw archive or a trace.

## Decision
1. **"Tilo remembers" notes (`memory_item.schema.json` 1.0.0, MI-01 to MI-10).** A person's own list of at most
   100 notes, each one line of at most 280 characters, `kind` preference, fact or person, `source` user or
   tilo_suggested (provenance only). Routes `GET /v1/memory`, `POST /v1/memory`, `PATCH /v1/memory/{id}`,
   `DELETE /v1/memory/{id}` (hard delete), owner-only with one 404 for every id that is not the principal's. Text is
   link-free with no hidden characters (schema and MI-03), refused if the secret redactor would change it or the
   safety provider flags it. A create or edit writes `memory.saved` (`preferences`) in the Desk world; a delete
   writes nothing.
2. **Suggest, never save (MI-04).** There is no unconfirmed state: Tilo stores nothing by itself. A Quick answer may
   carry one `suggestion` that code cut from the person's own words in that question when it holds a phrase of
   `config/quick.yaml` `memory_triggers` (shape below); a question that is only "remember that ..." gets the
   suggestion and no model call. The person's tap POSTs it with `source: tilo_suggested`. A model never writes note
   text, so no mail, document or web page can become a lasting "preference" (ADR-0030's reason, kept).
3. **A1, the person's context (MI-05).** `prompt_context` holds the person's local date and their 20 newest notes;
   tilo-api renders it as fenced data in the user turn (EFF-04) of exactly two calls: the person's own Quick ask
   and the Director's brief extraction for their own signed-in intake. It carries no name, title, address or other
   settings text, because USET-08 keeps profile text out of the raw archive; a person who wants Tilo to know their
   role adds a note. With no notes and no passages the prompt is byte-identical to today's (recorded replays keep
   their keys, B-007). Notes are not FR-INT-05 `applied_preferences` (MI-10); the Director may cite a note it used
   in `brief.sources` (`kind: memory`), and code keeps only ids it sent.
4. **Morning brief (`morning_brief.schema.json` 1.0.0, MO-01 to MO-12).** Per person, off by default
   (`/v1/me/brief-settings`: `enabled`, `time` 07:30, `time_zone`, `email_copy`; `email_rule_ready` read-only).
   The Scheduler tick's sweep (`TILO_MORNING_BRIEF=1`) makes one at the person's time within a 3-hour window, at
   most 10 per tick, claimed per (org, user, local date); `POST /v1/me/brief` makes one now, 3 per day. Code copies
   today's meetings (ADR-0048 `read_events`, own primary calendar), the last 24 hours of inbox mail headers
   (`search_email`, 10, never bodies) and the plate's deadlines up to 2 days ahead, cleaned like quotes (PE-24). One
   JSON-mode call on the existing `assistant` role picks the mail needing a reply and writes up to 5 suggestions and
   up to 5 to-dos, each citing only items code offered (MO-07, MO-08); without it the mail is shown `unsorted`
   ("unread"), never as needing a reply. Every section has a `status`, so "not connected" or "could not read" is
   never shown as "nothing today" (MO-12). The brief is the Desk-world artifact `art_mbrief_<yyyymmdd>` (versions,
   `artifact.created`/`versioned`, `vis: []`), kept 7 days; `GET /v1/me/brief` serves today's latest. The Home
   card shows it.
5. **Email copy and A18 (MO-10).** A scheduled brief is mailed to the person's own address only through the existing
   owner-only digest path (`enqueue_text(kind="morning_brief")`, the person's own pinned L3 `send_email` rule,
   quiet hours), at most once per UTC day, plain text, no links. This is A18's daily digest to oneself; a weekly
   one is a later additive kind (BQ-MEMB-6). Without the standing rule nothing is sent, and the settings answer
   says so (`email_rule_ready`).
6. **B3 to-dos (MO-11).** A to-do suggestion becomes a work item only when the person confirms it through the
   existing `POST /v1/work-items` with `source: {kind: mail, ref}`; the source-owners seam vouches for a message id
   that appears in the person's own brief of the last 7 days. The work item is person-made; code computes `due`
   from `due_text` (PE-15). Nothing else in a brief acts (no outbox entry but the email copy, no gate or card).
7. **Per-account grounding (`retrieval_chunk.schema.json` 1.0.0, RT-01 to RT-10).** Firestore native vector search
   on a new collection `orgs/{org}/chunks/{id}`: passages (at most 1200 characters) of the person's run
   deliverables, uploaded files' text, confirmed minutes, pins and notes, written by code from records already
   screened clean, each with `owner`, `team_id` (only a team pin or a deliverable of a world shared with that team;
   never an upload, minutes or a note, schema) and `world_id`. A query runs one `find_nearest` per readable scope
   with the scope filter inside the vector query (own chunks; each team the caller is a current, accepted member
   of), merges by distance, re-checks every hit against its source's read rule at that moment and drops failures
   (RT-03). At most 5 passages go to the same two calls as decision 3, as untrusted fenced data; a Quick answer
   lists what it looked at (`grounded_on`), so nothing is used silently (PRD 13.1). Chunks are deleted with their
   source (same operation, plus a daily sweep) and by erasure (RT-07). This replaces ADR-0030 decision 3's summary
   index (never built); ADR-0030's pre-filter, re-check, profile pinning and erasure rules carry over, and its
   "offer a starting point" flow (MEM30-c) is unchanged and later.
8. **Embeddings (RT-05), from ADR-0030 MEM30-a.** `packages/providers/interfaces.py` gains (architect-owned
   interface, built in ticket R1a): `EmbedRequest(texts: list[str] 1..64, task: Literal["document", "query"],
   dimensions: int 64..2048)` and `EmbedResponse(vectors: list[list[float]], profile_id: str, usage: dict[str, int]
   | None)`, both `extra="forbid"`; `ModelProvider.embed(EmbedRequest) -> EmbedResponse`; the fake returns
   SHA-256-seeded unit vectors with no network call; replay keeps `embed_recording_key`. Config: a role `embed`
   whose dev profile is the fake (price 0); the live profile (a Google embedding model) and its price are the
   owner's to add (PL-06). `config/memory.yaml` (loader-checked, ADR-0030 decision 7): `vector: {dimensions: 768,
   k: 5, max_distance: null, chunk_chars: 1200, per_source: 200, per_person: 2000}`, `embed: {batch_max: 64}`.
9. **`config/quick.yaml` `memory_triggers` (MI-04),** read by `tilo_api.quick_rules`: `lead: [remember that,
   remember, note that, please remember, don't forget that]`, `preference: [i prefer, i like, i don't like, i
   always, i never, please always, please never]`, `person: [my manager is, my boss is, i report to, my assistant
   is, my team lead is]`, `fact: [i work on, i work at, my role is, i am responsible for]`; matched after NFKC and
   casefold like the other word lists; `kind` comes from the list that matched (`lead` alone: fact).
10. **No new event type.** `memory.saved` gets its first emitter (Desk world, `preferences`; at run end,
    `artifact_memory`). Briefs use `artifact.created`/`versioned`; queries write none; `memory.hit` stays a
    verified reuse that saved credits (FR-MEM-02).

## Security
- Owner-only everywhere: notes, briefs, settings and personal chunks are read only by their owner through the
  verified principal; every foreign id is the same 404 (MI-01, MO-01). Team chunks follow the source's own team rule
  and are re-checked at every query; the cross-owner and cross-team leakage tests (identical texts and vectors, a
  revoked share, a removed member) are R1b's acceptance tests (RT-03).
- Stored prompt injection: no model writes a note; note text is screened and secret-checked at write; mail, calendar
  and document text reach a model only as fenced untrusted data in a user turn, and the model's output is either ids
  from a closed set (needs-reply mail) or short link-free lines checked by code and screened (MO-07). Neither the
  Quick call nor the brief extraction has tools; any send still needs its gate (MI-07, HR-7).
- Unauthenticated channels: notes and passages go only to signed-in web or mobile-web intake, never to email
  intake (MI-05, RT-04). Demo sessions read no Google account and use in-memory stores.
- Data minimisation: no mail bodies anywhere; subjects and sender names live 7 days in the Desk-world brief; no
  addresses; chunks die with their sources; erasure covers notes, briefs, settings, claims and chunks.
- Cost: one assistant-role call per brief and one query embedding per ask, metered on the person's allowance;
  failures degrade to fewer sections, never a failed ask (MO-07, RT-06). Dev and CI use fakes only (EFF-01).

## Consequences
- Contracts: three new schemas, three rules files, fixtures, the `memory.saved` Desk-world fixture, regenerated types
  and `tests/contracts/test_MEMORY_BRIEF_contract.py`. Builders never edit `contracts/`.
- Tickets (tests first; Codex builds the ones marked so; reviewers in brackets), detailed in
  `agy-bridge/tasks/MEMORY-BRIEF-TICKETS.md`: **M1** memory routes and store (Codex; code, security);
  **M2** "Tilo remembers" settings page and the Quick suggestion chip (Codex; design, qa); **M3** notes context,
  suggestion detection and `memory_triggers` in Quick and the Director (Claude; security, cost); **B1a** brief
  generator, sweep, routes, email copy, source-owners vouching (Claude; security, cost); **B1b** Home brief card and
  brief settings (Codex; design, qa); **R1a** typed embed, `embed` role and fake, `config/memory.yaml` (Codex;
  cost); **R1b** chunk store, indexer hooks, deletion and erasure, Terraform vector indexes (Claude; security,
  cost); **R2** retrieval into Quick and the Director with `grounded_on` (Claude; security, cost).
- Follow-ups: a weekly digest kind; screened mail subjects on the plate (BQ-269 stays as it is); ADR-0030 MEM30-c.

## Alternatives
- *A `confirmed` flag with stored, pending suggestions:* model text would persist without consent and need expiry
  and a cap; a tap that POSTs the suggestion keeps every stored note the person's own act.
- *Model-written suggestions from the conversation:* a careless tap could store text a document or mail planted;
  code-cut text from the person's own question cannot carry anyone else's words.
- *Profile name and title in the context:* USET-08 keeps profile text out of the raw archive, which a Director call
  reaches; a note does the same job under the person's control.
- *Brief settings inside `user_settings`:* a new required section is a breaking change, and an optional one would be
  dropped by any client that saves the whole document (USET-02).
- *Vertex AI Vector Search or a vector database:* an always-on endpoint costs money at zero traffic (PRD 6.6) and
  adds a store to erase; Firestore vector search costs reads and storage only and keeps the data in the project.
- *Filtering after ranking:* a top-k over everyone's chunks, filtered afterwards, leaks by omission and ranking;
  the scope filter is inside each vector query and every hit is re-checked.
