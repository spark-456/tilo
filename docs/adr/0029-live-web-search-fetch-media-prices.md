# ADR-0029: Live web search, fetch, media input and prices

- Status: Proposed. Written by the architect on 2026-10-08 for the user's approval. Every change is
  additive, but `providers`, `artifact` and `common` are frozen contracts (CP0, 29 Sep), so nothing
  that depends on them merges until the user says yes. **The user should check decisions 1 to 9
  and the price table.** One price question is already answered: on 2026-10-08 the supervisor
  relayed the user's answer to BQ-LW-7, "meter flash at the full 0.825/4.125 (cached 0.0825)
  while Google's 50% net-spend credit runs, and reconcile against the bill net of credits".
- Deciders: user (approval), architect
- Requirements: PL-03, PL-06, FR-MTR-01, EFF-03, EFF-04 (prices and router); PRD 12.2 web search
  (Must), 12.3, FR-CON-10, SEC-05, SEC-09 (search and fetch); FR-INT-01, FR-INT-02 (media);
  FR-AGT-16 (Could, the AppSpec); USER-LIVE-WEB, the user's direction of 8 Oct 2026 that Tilo
  really does jobs like "prepare for GATE 2027: research the web, download past papers, build a
  practice site with timed questions, assess me".
- Questions it answers or opens: BQ-LW-1 to BQ-LW-11 in `docs/open-questions.md`.
- Merge order: PR #649 (ADR-0027, providers 1.2.0, common 1.5.0), then PR #671 (ADR-0028, the
  meeting room), then this PR. #671 touches none of the schemas changed here. After it merges,
  this branch takes it in, regenerates the contract types and regenerates `evals/bank/live/B-007`.

## Context
The job above needs five things the contracts refuse today.
1. **Prices.** `$defs.price` is per token only. Grounded search bills a fee per query on top of
   the tokens, prompt-cache hits bill at their own rate (ADR-0022 records `tokens_cached` but
   nothing prices it), the user's rates are for the `asia-southeast1` regional endpoint, and the
   flash rates are promotional until 2026-12-31. `config/prices.yaml` held a TODO for that last
   date: `$defs.prices` has one `effective_date` for the whole file.
2. **Media.** FR-INT-02 says a PDF is read natively, but `$defs.capability` cannot say that a
   profile reads documents or video, and nothing tells the router how many tokens an image or a
   PDF page costs before it sends one (EFF-03).
3. **Web.** PRD 12.2 makes web search a Must, but `config/connectors.yaml` has no web connector
   and `config/autonomy.yaml` makes every unlisted action T3, so each search would wait for a
   person.
4. **Downloads.** An artifact version is made by a unit (text or JSON only), tilo-render, an
   upload or a restore. A file a unit downloaded fits none of them.
5. **A practice site.** The PRD's home for an app Tilo builds is FR-AGT-16 (AppSpec, Could). The
   `app.*` events are registered, but `appspec.schema.json` was never written.

## Decision 1: a fee per unit and its reservation (providers 1.3.0)
1. `$defs.price.unit_price` is `{unit, per_1k}`. `unit` is `query`, `minute`, `character` or
   `image`; `per_1k` is US dollars per 1,000 units, null only while prices are unset. The fee is
   charged on top of the token rates.
2. A call costs, in US dollars:
   `((input_tokens - cached - audio) * input + cached * cached_input + audio * audio_input
   + output_tokens * output) / 1,000,000 + units * per_1k / 1,000`.
3. For Gemini grounding, `units` is the number of entries in
   `grounding_metadata.web_search_queries`. The adapter reports it as `usage.search_queries`.
4. `$defs.role.reserve_units` (optional, at least 1) is how many units the router reserves under
   the PL-03 budget check before it sends, because Gemini decides how many searches it runs. A
   grounded reply without that metadata is charged the reserved amount. A reply that ran more
   searches than reserved is charged in full, and the overrun is recorded.
5. Loader rules, stated in the `roles` description: a role whose profiles carry a `unit_price`
   states `reserve_units`; the `search` role's profiles declare `grounding` and, while prices are
   set, carry a `unit_price` with unit `query`.

## Decision 2: the cached-input price
`$defs.price.cached_input` (optional) is US dollars per million input tokens served from the
provider's prompt cache (`trace.tokens_cached`, ADR-0022). Left out, cached tokens are priced at
`input`, which overstates and never understates. Cache storage is not priced, because Tilo creates
no explicit caches.

## Decision 3: regional rates
`config/prices.yaml` holds the rates actually charged, and a new optional top-level `region` names
the provider location they were quoted for. The loader refuses live metering of a profile whose
adapter sends to another location: `google` reads `GOOGLE_LOCATION`, `model_armor` reads
`TILO_MODEL_ARMOR_LOCATION`. An adapter with no location (`openai_compat`, `fake`) is not checked,
so `config/models.gemini.yaml` (the Gemini API through `openai_compat`) is metered at these
regional rates, about 10% too high. There is no multiplier field.
PRD 6.5 and D-14 route Gemini through the global endpoint, and `GOOGLE_LOCATION` defaults to
`global`. With this price sheet, live metering therefore needs `GOOGLE_LOCATION=asia-southeast1`
once LW-05 ships the check (BQ-LW-11).

## Decision 4: dated prices
`$defs.price.valid_until` (optional, a calendar date in UTC) is the last day a promotional rate
holds. After it, the price book refuses to quote that profile, and live metering stops until the
file is updated. A replay uses its recorded dates. The loader also refuses a `valid_until` before
the file's `effective_date`. This closes the "dated price entries" TODO in `config/prices.yaml`.
The meter never subtracts promotions or credits (BQ-LW-7, decided).

## Decision 5: free allowances
Free allowances have no field: 5,000 grounded queries a month, Model Armor's 2M tokens, and Cloud
TTS's 1M or 4M characters. They are monthly and shared by every environment, so the meter charges
from the first unit and the allowances are recorded only as comments in `config/prices.yaml`. How
the FR-MTR-08 reconciliation treats them is BQ-LW-6.

## Decision 6: media capabilities and token sizes
1. `$defs.capability` gains `video` and `documents` (a PDF read natively, FR-INT-02).
   `tilo_providers.interfaces.Capability` gains the same two members.
2. `$defs.profile.media_tokens` is `{image, pdf_page, audio_per_second, video_per_second}`, each an
   integer of at least 1. They are upper bounds, used only for the pre-flight estimate and the
   EFF-03 cap check before a media part is sent; billing uses the reported usage. A profile
   without `media_tokens` gets no media part: the router refuses it before sending.
3. In `config/models.yaml`, flash-38, flash-37 and lite-31 get `{1120, 1120, 25, 258}` (1,120 is the
   stated maximum for an image). All three declare `vision`, `audio`, `video` and `documents`:
   lite-31 gains all four, and the flash profiles gain `video` and `documents`, since the same
   model family reads them.

## Decision 7: the web connector, its tiers and the search role
1. `config/connectors.yaml` gets `web` (island "The Web", icon `globe`, `auth: none`, no scopes,
   data class `public`). It has two actions, both T1, `gate_type: none` and reversible:
   - `web_search` (capability `search`) goes through the SearchProvider;
   - `fetch_url` (capability `read`) downloads one public page or file through tilo-browser.
   `config/autonomy.yaml` lists both as T1, so a search never falls to the unlisted-is-T3 default.
   The SEC-11 test excludes them from the outbox set only while they stay ungated reads.
2. `config/models.yaml` gets a `search` role on a new `search-google` profile: gemini-3.8-flash
   with caps `json` and `grounding` and its own price row. The role's fallback is the same
   profile, because a fallback without grounding would answer from memory (NFR-25 still holds).
   `reserve_units: 5` (BQ-LW-10), `max_input_tokens: 8000`, and `max_output_tokens: 4096` so that
   the router's default of 1,024 (BQ-63) does not cut a cited answer.
3. The search adapter sends only Gemini's `google_search` tool. It refuses the URL-context tool:
   that fetch would happen on Google's side, outside SEC-09 egress control, robots.txt and the
   raw archive. Every fetch goes through tilo-browser (LW-08).
4. A unit that has read fetched content gets no side-effect tool (SEC-05). Every tool result goes
   through `SafetyProvider.check` and is fenced before a model sees it (LW-07).

## Decision 8: the `fetch` artifact origin (artifact 1.1.0, common 1.6.0)
1. `origin.kind` gains `fetch`: a file that a unit's worker agent downloaded through tilo-browser
   for a `fetch_url` call. `unit` and `agent` are set. The store sets the origin from the run,
   never the runner.
2. A fetch keeps only the six file types: PDF, PNG, JPEG, DOCX, PPTX and XLSX. It never keeps
   HTML, SVG, a bare archive or a program. Code sets the media type from the file's leading bytes
   (the Office types by their ZIP container and main part), never from the URL, an extension, a
   `Content-Type` header or a model. `common`'s `media_type` description says so (1.6.0). A
   fetched HTML page never becomes an artifact: its cleaned text is the tool result in the raw
   archive.
3. `sources` holds exactly one entry: the fetch's own raw-archive record of the same run, whose
   payload's `source.ref` is the cleaned URL (BQ-101, BQ-104).
4. The idempotency key ends in `f0` to `f9`, the file's position among the unit's fetched files
   (at most 10, FR-INT-01). A unit or render output keeps `0` to `9`, so the two never share a key.
5. The bytes are screened like an upload (AR-07).
6. A fetched file reaches only its owner, through the owner-scoped content route (LW-13). Every
   path that sends or shares a file is already T3 (`attachments`, `share_file`,
   `external_sharing`). Tilo never republishes a fetched file (BQ-LW-5).
   Rule AR-09 in `artifact.rules.md` holds all of this.

## Decision 9: the AppSpec quiz (appspec 1.0.0, common 1.6.0)
1. `contracts/appspec.schema.json` (`AppSpec`) has one kind, `quiz`. Its fields are `v`, `kind`,
   `title`, `theme` (a theme slug), `timer.seconds` (60 to 21,600) and 1 to 200 `questions`.
   Each question has an `id` (q1 to q999), a `stem`, two to six `options` keyed `a` to `f`, the
   `answer` (an option id it actually has), an optional `topic` tag, and a `source`: the stored
   version it came from (a fetch or an upload) and, for a PDF, the page.
   The spec holds no HTML, script, style, link or URL field.
2. The spec is a unit's `application/json` output (origin `unit`), so a model writes JSON only,
   as ADR-0018 requires. Fixed web code renders every string as plain text at an owner-only route.
   The publisher line comes from the cited version's manifest, server side. Rules AS-01 to AS-04
   are in `appspec.rules.md`.
3. `deliverable_format` gains `app` (common 1.6.0).
4. Events reuse the `app` family. `app.spec` names the stored spec, `app.tested` records the
   Verifier's answer-key check, and `app.deployed` is written when the owner-only route first
   serves the version. No new event type is added. Feedback on each attempt would need an
   `app.submitted` event (phase 2, BQ-LW-4).
5. Sharing a quiz beyond the owner is T3. FR-AGT-16 is a Could; promoting it to Must is the
   user's call (BQ-LW-3).

## Prices (`config/prices.yaml`, draft)
The sheet has status `set`, effective date 2026-10-08 and region `asia-southeast1`. Its source is
"user-supplied 2026-10-08, Google price pages, asia-southeast1 regional endpoint, paid Standard
tier". All rates are US dollars per million tokens unless the row says otherwise.

| Profile | input | output | cached_input | Other |
| --- | --- | --- | --- | --- |
| flash-38, flash-37 | 0.825 | 4.125 | 0.0825 | `valid_until` 2026-12-31 |
| lite-31 | 0.275 | 1.65 | 0.0275 | `audio_input` 0.55; no promotion |
| search-google | 0.825 | 4.125 | 0.0825 | `unit_price` {query, 14 per 1,000} (2.8 credits a query); `valid_until` 2026-12-31 |
| tts-flash (Gemini 3.8 Flash TTS) | 0.50 | 9.00 (audio output tokens, about 25 a second) | none | `valid_until` 2026-12-31; 1.00 / 18.00 from 2027-01-01 |
| armor-default | 0.10 | 0 | none | unchanged |

- `tts-flash` has a price row but no profile yet, so it is inert until FR-MTG-16 adds one.
- Gemini 3.8 Flash-Lite TTS (audio output 6.00, 12.00 from 2027) has no row: its text input rate
  was not supplied, and a set file holds no null (BQ-LW-9).
- Cloud TTS, Speech-to-Text V2 and Imagen 4 are recorded as comments only, since no profile uses
  them.
- Flash's audio input rate was not supplied, so audio input stays on lite-31. Until it is
  supplied, the `speech` role that ADR-0027's FR-MTG-17 follow-up adds names lite-31 as both
  primary and fallback (BQ-LW-8).

## Tickets (builders can start on fakes; nothing goes live without the user's `LIVE=1`)
Lanes: A architect, B providers, C browser and sandbox-web, D harness, E API and web. The
supervisor assigns lanes to sessions.

| Ticket | Lane | Scope | Needs | Review |
| --- | --- | --- | --- | --- |
| LW-05 | B | `GoogleSearchProvider` over Gemini grounding, with typed request and result (answer, cited sources with cleaned URLs, queries run, the search suggestions), a fake and record-and-replay. The secret redactor runs on the query. Grounding redirect URLs are resolved only through LW-08. Loader and price-book rules from decisions 1 to 4 (`unit_price`, `cached_input`, `valid_until`, `region`, `reserve_units`, the search role), in `tilo_providers.config` and `tilo_metering.PriceBook`. The adapter refuses URL context. `models.dev.yaml` gets a fake `search` role, priced 0 in `prices.dev.yaml`. | this ADR | cost |
| LW-06 | B | `GenerateRequest.parts` (MIME type, bytes or URI, sha256). The Google adapter sends `inline_data`; the openai_compat adapter takes images only, and anything else is a missing capability that falls back. The router picks by each part's capability, checks `media_tokens` against EFF-03 caps, and keys recordings on sha256, never the bytes. Large files go by GCS URI (needs ADR-0018 T8). | this ADR | cost |
| LW-07 | D | A shared `ToolUnitRunner` replaces `DefaultUnitRunner` and the evals copy. It passes upstream inputs and runs a tool loop limited to the skill's `tools_allowed` intersected with the role's tools, with step and credit caps per unit. Every tool result goes through `SafetyProvider.check`, `neutralise` and a fenced block. SEC-05: a unit that read fetched content gets no side-effect tool. One Trace `tool` row per call; results go to the archive and cache. `tilo_memory.artifacts` accepts origin `fetch` (AR-04, AR-05 with the `f` key, AR-09). | LW-05 and LW-08 fakes | security |
| LW-08 | C | `POST /fetch` on tilo-browser: HTTPS GET only, no cookies, `EgressPolicy` plus the task allowlist (BQ-LW-1). SSRF: resolve DNS and refuse private, loopback, link-local, metadata and ULA addresses; pin the IP; re-check every redirect (at most 5). robots.txt (BQ-LW-5), timeouts, 25 MiB a file and 10 files / 50 MB a unit, type by leading bytes (AR-09), a reason logged for every block (SEC-09). | LW-09 | security |
| LW-09 | C | Fictional sandbox-web fixtures: past-paper-style PDFs and an answer key, robots.txt, a planted injection, wrong leading bytes, an oversize stream, a zip, and a redirect to 169.254.169.254. | none | code |
| LW-10 | D, render | Writer emits `DeliverableSpec` JSON; `render_pdf` runs in-process and stores origin `render`. For `app`: the writer emits an AppSpec checked against the schema and AS-01, then `app.spec`. | LW-07 | code |
| LW-11 | C | `POST /render` on tilo-render with service-to-service auth. | LW-10 | security |
| LW-12 | B | Uploaded and fetched PDFs and images reach the Director and units as `parts`. Questions are extracted as JSON, and the Verifier checks each against its source page (AS-02, FR-AGT-12), then writes `app.tested`. | LW-06, LW-07 | code |
| LW-13 | E | `GET /worlds/{w}/artifacts/{a}/versions/{v}/content` (owner and SEC-07 scope, attachment only, `nosniff`, CSP sandbox, source host shown), the S-12 Download button, and the spec read for the player, which writes `app.deployed` on first serve (AS-04). | this ADR | security |
| LW-14 | E | Quiz player at `/world/:id/app/:artifactId`: text-only rendering (AS-03), timer with pause, scoring, topic filter, attempts in localStorage in phase 1. It uses the generated `AppSpec` type. | LW-13 | security, design |
| LW-15 | E | Sources panel, including the Google Search Suggestions the grounding terms require. | LW-05 | code, design |
| LW-16 | D | A GATE-style replay case in E-RES on the LW-09 fixtures. `live_e2e` moves to `ToolUnitRunner` and its FAKED list is trimmed. A live run happens only when the user sets `LIVE=1`. | LW-07, LW-08, LW-10 | cost |
| LW-17 | any | Skills: web-research (one of the v0 ten), question-bank extraction and quiz assessment (content, not code), with golden tests. | LW-07 | code |
| LW-18 | A, then planning | Audio and video task intake (BQ-LW-2), phase 2; large files need T8. | ADR | security |

- **Order.** First, LW-05, -06, -07, -08, -09 and -13 run in parallel on fakes. Then LW-10, -12,
  -14 and -17. Then LW-16 goes green on replay. The critical path is LW-05, LW-07, LW-16.
- **Fallback if this ADR waits.** Keep downloads in the raw archive only, cite them, and deliver
  the PDF report and the quiz.
- **tilo-dev** also needs ADR-0018 T8 and FR-MEM-05 (the production artifact store and redactor).

## Consequences
- **Versions.** `providers` goes from 1.2.0 to 1.3.0, `artifact` from 1.0.0 to 1.1.0 and `common`
  from 1.5.0 to 1.6.0, and `appspec` 1.0.0 is new. Every shipped config file and older fixture
  stays valid. The Python and TypeScript types are regenerated, and `scripts/contracts_codegen.py`
  names the root `AppSpec`.
- **Tests changed.** Pins on the old prices, version, role set or enum size moved:
  - `test_FR_MTR_01_repo_prices_yaml...` and `tests/contracts/test_PRD_6_4_providers_config.py`
    (shipped prices);
  - `test_FR_MEM_12_...` (artifact version floor, origin set, AR-03 for fetch);
  - `test_NFR_25` (role set gains `search`);
  - `test_PL_02_director_exact_request` (the longest enum is 12, with `app`);
  - SEC-11 (the two web reads are excluded from the outbox set only while they stay ungated
    reads).
  New: `tests/contracts/test_ADR_0029_live_web_media_prices.py`. `evals/bank/live/B-007` was
  regenerated with the fake, with no switch, because the connector catalogue and the brief schema
  changed the Director's replay keys.
- **Known gaps until the tickets land.**
  - The Director may choose `app` as soon as this merges, but nothing writes an AppSpec until
    LW-10, so such a run still delivers Markdown.
  - The region and `valid_until` refusals start when LW-05 ships, not with this PR.
  - `GOOGLE_LOCATION` must then be `asia-southeast1`, or the sheet must carry global rates
    (BQ-LW-11).

## Alternatives considered
- **A regional multiplier on the global rates.** Rejected: it is a second number to keep in step,
  and the user supplied the charged regional rates directly.
- **Per-query pricing as a separate "tool" price table.** Rejected: the fee belongs to the profile
  that runs the searches, and one price row per profile keeps the router's cost function in one
  place.
- **Letting Gemini fetch pages (URL context).** Rejected: the fetch would skip egress control,
  robots.txt and the raw archive, so provenance (FR-CON-10) could not cite what the model read.
- **Model-written HTML for the practice site.** Rejected: `media_type` has no HTML, a model writes
  only text and JSON (ADR-0018), and code a model wrote would have to be sandboxed and reviewed. A
  declarative spec rendered by fixed code needs neither.
- **Storing fetched HTML pages as artifacts.** Rejected: it would reopen the closed media types
  for little gain, since the cleaned text already sits in the raw archive and is cited.
