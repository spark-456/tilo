# ADR-0030: Hybrid memory: Memory Bank preferences and Firestore vector search

- Status: Accepted (user approved 8 Oct 2026). The supervisor asked for this design on the user's behalf;
  the user approved it in the supervisor chat. Open questions keep their stated defaults.
- Deciders: user (approval, embedding price, the region question), architect (design)
- Requirement: PRD 13.1 (memory layers), FR-MEM-01, FR-MEM-02, FR-MEM-05, FR-MEM-09, FR-INT-05, FR-AGT-07;
  PRD 6.4 (`ModelProvider.embed`), 6.6 (efficiency), 14.3 (credits saved), 16.5 (deletion); PL-01, PL-06,
  EFF-01, EFF-03, NFR-25; HR-1
- Relates to: ADR-0018 (artifact store and Scope), ADR-0029 (live web and media, being drafted: downloaded
  documents and possibly a per-unit price shape)

## Context
1. **What exists.** `tilo_planning.memory.MemoryLookup` is the seam for preferences and decisions; only
   `InMemoryPreferenceStore` implements it. The result cache (`tilo_memory.cache.ResultCache`) is exact-key
   (normalised request plus source fingerprint), runs the fit check and the Verifier, and emits one
   `memory.hit` per reuse. Decisions are exact-key Firestore records (`decision.schema.json`, FR-AGT-07).
   Erasure (`tilo_memory.erasure`) already requires a `memory_bank` store in its registry.
2. **What PRD 13.1 asks and nothing builds yet.** Preferences ("user and org preferences, triage corrections,
   style profile") live in Agent Platform Memory Bank and are "applied in planning and drafting". Artifact
   memory ("past deliverables and their manifests") is "offered as a starting point, never silently reused".
   Neither has a store, and an exact key cannot find "last month's supplier deck" for a new, differently
   worded task.
3. **What the contracts already cover.** `memory.hit` (a reuse that passed the fit check and the Verifier,
   with `origin_cost`, `lookup_cost`, `saved`), `memory.saved` (layers `result_cache`, `artifact_memory`,
   `decisions`, `preferences`), `brief.sources[]` kind `memory` (ref: a memory entry id), `brief.citation`
   kinds `preference` and `decision`, and question cards. `ModelProvider.embed` exists in all three adapters
   (google, openai-compatible, fake) but is untyped (`Any`), and no `embed` role or profile is configured.

## Decision
1. **Three stores, each for what it does best.**

   | Layer | Store | Match | Why |
   | --- | --- | --- | --- |
   | Result cache, decisions | Firestore, as today | exact key | cheapest, deterministic, replayable; a decision answers the same question, not a similar one |
   | Preferences (user, org) | Agent Platform Memory Bank | exact scope, then by brief field | PRD 13.1 names it; scoped per person or org |
   | Artifact memory: past deliverables and manifests, skills, uploaded and downloaded documents | Firestore native vector search | KNN on a short summary's embedding, pre-filtered by org and owner | finds similar past work; no new database |

2. **Preferences in Memory Bank (MEM30-d).** A `MemoryBankPreferences(MemoryLookup)` adapter, behind the existing
   seam, with `InMemoryPreferenceStore` as the dev and CI fake.
   - **Scope:** `{"org": <org>, "user": <uid>}` for a person, `{"org": <org>}` for the org. Memory Bank
     matches scope exactly, so these are two reads; a person's preference wins over the org's for the same field.
   - **Written by code, never extracted by a model.** Tilo creates memories directly from structured sources:
     the person's own answer to a question (`question.answered` by that person), a setting they change, a triage
     correction they make. It never calls Memory Bank's model-driven generation over sessions, mail or documents:
     that would let untrusted text become a lasting "preference" (stored prompt injection) and adds model cost.
   - **Closed fact shape.** Each memory's fact is canonical JSON `{"v": "1.0", "field", "value", "ref",
     "recorded_at", "source", "origin_cost"}`, where `field` is one of the brief's `applied_preference` fields and
     `value` is at most 300 characters, after the secret redactor. A fact that does not parse into this shape is
     ignored (treated as absent, never repaired). Every hit is cited in `brief.applied_preferences` (FR-INT-05).
   - **Erasure (FR-MEM-09):** the adapter is the erasure registry's `memory_bank` store. Its `records()` lists
     the person's memories by scope, `delete()` deletes one by resource name, and `verify_erasure` re-reads.
     Org-scope memories are nobody's personal records and stay.
   - **Region:** if Memory Bank is not offered in `asia-southeast1`, preferences stay in a Firestore
     implementation of the same seam until the user decides (BQ-MEM30-2). No preference data leaves the region
     by default.
3. **Artifact memory in Firestore vector search (MEM30-b).** One collection, `orgs/{org}/memory_index`, one
   document per indexed item: `owner` (uid, or null for skills), `org`, `kind` (`deliverable`, `skill`,
   `document`), `ref` (an artifact ref with version, or a skill id and version), `label` (at most 120
   characters), `summary` (at most 600 characters), `summary_sha256`, `embed_profile`, `dimensions`,
   `embedding` (a Firestore vector), `screening`, `created_at`. Never raw content, never a recipient, a link
   or a token.
   - **Short summaries, not raw text.** The summary is built from what the run already has: for a deliverable,
     the approved brief's goal, the deliverable's title and format and the artifact label; for a skill, its
     `skill.yaml` name and description; for an uploaded or downloaded document, the summary the unit that read
     it already wrote, cut at 600 characters (never cut inside a word), else its label and media type. No model
     call is made only to feed memory. Every summary passes the secret redactor; an artifact whose `screening`
     is not `clean` is not indexed.
   - **Owner pre-filter before similarity.** Every query is `where(org == org) .where(owner == principal)
     .where(kind in kinds) .where(embed_profile == current)` and then `find_nearest` on `embedding`, served by
     one composite vector index on those fields (skills: `owner == null`). The store's search function takes
     the org and owner as required arguments and refuses a blank, wildcard or missing one; there is no query
     path across owners. After the query, every hit is checked again through the artifact store's Scope (the
     record exists, is not deleted, has this owner and `screening` `clean`); a hit that fails is dropped
     silently. A teammate's deliverables are never offered, even from a shared world (BQ-MEM30-8). Downloaded
     documents are indexed once ADR-0029 gives them an artifact origin; until then only uploads are.
   - **Vectors:** unit-normalised, `DOT_PRODUCT` distance, dimension from config (default 768; Firestore allows
     at most 2048). An entry records `embed_profile` and `dimensions`, and a query compares only entries of the
     current profile: vectors of two models are never compared. Changing the embedding profile is a re-index
     job, never a silent mix.
   - **Lifecycle:** an entry is written when its artifact is stored (`memory.saved`, layer `artifact_memory`,
     `item_count` the number indexed by the run). It is deleted with its artifact, its world or its owner
     (erasure registry `firestore` store), and kept no longer than its artifact (retention, PRD 16.5).
4. **Offered, never silently reused (MEM30-c).** At planning, once per run, and only when the brief names a
   deliverable:
   1. Embed the brief's goal and deliverables (task `query`), within the lookup cap.
   2. Fetch at most `k` (5) nearest entries for the owner.
   3. **Fit check** (one call on a new config role `memory_fit`: the cheapest profile, a dearer fallback for
      NFR-25, at most 200 output tokens; BQ-MEM30-9): the candidates' labels and summaries go in a fenced data
      block marked as data, never instructions. The model answers only `{"fits": [<candidate id>, ...]}`. Code keeps ids from the given
      set, drops anything else and fails closed (offers nothing) on any parse error. No model text reaches a
      card, a prompt for another agent or a store.
   4. **Offer:** at most `offer_max` (3) candidates, on one question card built by code from metadata only
      (label, kind, date): "Start from one of these?" with one option per candidate and "Start fresh"
      (`safe_default`). The offer counts against the run's question cap (BQ-MEM30-6).
   5. **Accepted:** the brief gains `sources[{kind: "memory", ref: <entry id>, label}]`. At use, the planner
      checks again that the entry and its artifact belong to the run's owner (the reuse-time check), then hands
      the artifact to the unit as an input, as data, like any file. The output passes the Verifier as today.
      `memory.hit` is emitted only for a reuse that PRD 13.1 counts: the fit check and the Verifier accepted
      an item that replaces a unit's work as it is. Starting from an old deck and revising it credits nothing
      (BQ-MEM30-7), so credits saved are never overstated.
   6. **Skills** (optional, MEM30-c part 2): the Director gets the top skills for the brief instead of the
      whole list. This changes the plan-stage replay key (B-007), so it ships separately.
5. **Embeddings (MEM30-a): a role, typed, batched, cached, priced by the user.**
   - **Typed interface** in `packages/providers/interfaces.py` (an architect-owned interface; the adapters are
     the builder's): `EmbedRequest(texts: tuple[str, ...], task: Literal["document", "query"], dimensions: int)`
     and `EmbedResponse(vectors: tuple[tuple[float, ...], ...], profile_id: str, usage: dict[str, int] | None)`.
     The google adapter maps `task` and `dimensions` to the API's task type and output dimensionality. The
     openai-compatible adapter maps them to `dimensions` and `input_type`. The fake returns deterministic
     sha256-seeded unit vectors and makes no network call. Replay keeps `embed_recording_key`.
   - **Config only:** an `embed` role and an embedding profile in `config/models.yaml` (and the dev, NIM and
     Gemini variants), with no model id outside `config/` and `packages/providers` (PL-01). The role's
     fallback is the same profile (as the `safety` role does), because a different model's vectors are
     incomparable; when embedding fails, there are no starting points, never an unrelated vector.
   - **Price: needs a user-confirmed price.** The profile's `config/prices.yaml` row is the user's to supply
     from Google's page (PL-06). Until then the loader's start-up rule (every profile priced while `status:
     set`) keeps the live profile out of `config/models.yaml`; only the dev fake (price 0, makes no paid call)
     ships. If Google prices it per 1,000 characters rather than per 1M tokens, it needs ADR-0029's per-unit
     price shape (BQ-MEM30-1).
   - **Batched and cached:** at most `batch_max` (64) texts per call. A document vector is reused when the
     same owner already has an entry with the same `summary_sha256` and profile. A query vector is cached per
     owner by `sha256(profile, dimensions, task, normalised text)` for 7 days (`user_id` on every cache record,
     so erasure finds it).
6. **Cost caps per lookup.** One lookup per run at planning: one query embedding, one vector query (Firestore
   reads), one fit-check call (at most `k` summaries of 600 characters, a small output cap, EFF-03). The quote
   is reserved before the lookup (MT-03) against `lookup.credit_cap` (default 0.5 credits). If it does not fit,
   there is no lookup and the run plans as it does today. Indexing a deliverable costs one embedding per new
   summary and is metered on the run that made it. The lookup's credits are its `lookup_cost` (EV-09) when a
   hit follows.
7. **Config (MEM30-b):** a loader-checked `config/memory.yaml` (no contract, like `config/personal.yaml`):
   `vector: {dimensions: 768, distance: dot_product, k: 5, offer_max: 3, max_distance: null, summary_max_chars:
   600, kinds: [deliverable, skill, document]}`, `embed: {batch_max: 64, query_cache_days: 7}`,
   `lookup: {credit_cap: 0.5, per_run: 1}`. `max_distance` stays null (no threshold) until the recall eval sets
   one (BQ-MEM30-5).
8. **No contract change.** `memory.hit`, `memory.saved` (`artifact_memory`, `preferences`), `brief.sources`
   kind `memory`, `brief.citation` and question cards already carry everything. The index document and the
   preference fact are written and read by `packages/memory` only (the convention: a contract for a shape that
   crosses a service boundary). If the web or another service ever reads them, they get a schema first.

## Security
- **Injection through retrieved text.** Summaries come from documents and web pages, so they are untrusted.
  They are redacted and screened before storage (flagged artifacts are never indexed). They reach only the fit
  check, fenced as data, whose output is a closed set of ids checked in code. The offer card is built from
  metadata by code. An accepted item reaches a unit as an input marked as data, never as instructions. Memory
  Bank never runs model extraction, so no text a person did not choose becomes a preference.
- **Cross-tenant leakage.** The owner pre-filter is inside the vector query, and the Scope re-check comes after
  it. The search API has no owner-less form. Tests: two owners with identical summaries and vectors, where
  owner A at any `k` never sees B's entry. A query with a blank, `*`, or another org's owner is refused before
  Firestore is asked. A deleted or re-owned artifact is dropped at the Scope check. Org preferences and skills
  carry no personal data.
- **Erasure.** Index entries, query-vector cache records and Memory Bank memories are each in the erasure
  registry. `verify_erasure` re-reads all three, and the FR-MEM-09 script covers them (BQ-MEM30-3 for Memory
  Bank's deletion delay).
- **Secrets.** Summaries, facts and queries pass the secret redactor before embedding, storage or a model call
  (FR-MEM-05). An embedding is derived personal data and is deleted like the record it came from.
- **Cost.** Per-lookup cap, one lookup per run, batching, caching, no model call just to summarise, a fake in
  dev and CI (EFF-01).

## Alternatives considered
- *Everything in Memory Bank* (its own similarity search over facts): fits short facts, not artifact manifests
  with versions and Scope checks. Its retrieval cannot express "this owner's artifacts of these kinds that
  still exist".
- *A separate vector database* (Vertex AI Vector Search, pgvector on Cloud SQL): an always-on index endpoint or
  database costs money at zero traffic (PRD 6.6 scale to zero) and adds a store to erase. Firestore vector
  search costs reads and storage only.
- *Embedding raw content or whole documents:* costlier, larger vectors of mostly noise, and the stored vector
  of an email or contract is harder to justify under deletion rules. Short summaries are enough to offer a
  starting point.
- *Silent reuse of the nearest past deliverable:* PRD 13.1 forbids it.
- *Vectors for decisions too:* a decision answers the same question (FR-AGT-07). A similarity match could
  answer a different question with an old owner's answer, which is an authorisation risk. Decisions stay
  exact.

## Consequences
- Tickets (each starts with test-writer tests; reviewers in brackets):
  - **MEM30-a** (intelligence-builder; cost-reviewer): typed `EmbedRequest`/`EmbedResponse`, the three adapters,
    the deterministic fake, replay, the `embed` role and dev profile. The live profile and its price wait for
    the user. Update the NFR-25 role-set pin (`test_PRD_6_4_shipped_config_loads`) and any `x-version` pins
    the merge with ADR-0029 touches.
  - **MEM30-b** (intelligence-builder, reach-builder for `infra/`; security-reviewer): `VectorIndex` with a
    Firestore implementation and an in-memory exact-KNN fake behind one interface; the summary builder; the
    composite vector index in Terraform (`google_firestore_index` with a vector config); erasure and retention
    hooks; `config/memory.yaml` and its loader; emulator tests (BQ-MEM30-4 if the emulator lacks vector
    search).
  - **MEM30-c** (intelligence-builder; security-reviewer, cost-reviewer): planner wiring of steps 4.1 to 4.5, the
    fit-check prompt in `prompts/` with its closed response schema, the `memory_fit` role (and the NFR-25
    role-set pin), the offer card, the reuse-time check, `memory.saved` at run end, the lookup cap. Part 2 (skills to the Director) ships separately with a B-007
    regeneration by the orchestrator or the user.
  - **MEM30-d** (intelligence-builder; security-reviewer): `MemoryBankPreferences` with direct create only,
    scopes, the closed fact shape, the erasure store, and the Firestore fallback if BQ-MEM30-2 needs it. Dev and
    CI use the fake; the first live call needs `LIVE=1` from the user.
  - **MEM30-e** (evidence-builder): a requirement-level eval in `packages/memory/tests/fixtures/memory_recall/`
    (not `evals/bank/`, which is frozen, and not a new eval group, which `evals.schema.json` closes): about 40
    fixture summaries across three owners and 15 queries with labelled relevant items. Vectors are recorded once
    by the user (`LIVE=1`) and replayed in CI. Pass: recall@5 at least 0.8 on replayed vectors (BQ-MEM30-5), and
    cross-owner leakage exactly 0 with replayed and fake vectors alike.
- The user decides: approval of this ADR, the embedding profile and its price, Memory Bank's region (or the
  Firestore fallback), and the recall threshold.
- Open points: BQ-MEM30-1 to BQ-MEM30-9 in `docs/open-questions.md`.
