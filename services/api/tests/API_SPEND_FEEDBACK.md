# SPEND-CAPS-FEEDBACK: beta spend caps and the lifetime-cap pop-up with a feedback box (what the acceptance tests pin)

Sources: the user, 8 Oct 2026 (relayed by the supervisor). Part 1 is "user approved 8 Oct", part 2 is "user request
8 Oct"; neither is in the PRD (BQ rows `BQ-SEC16-3` and `BQ-FEEDBACK-1` go at the END of `docs/open-questions.md`).
Builds on SEC-16 (`API_SEC_16.md`), SEC-15 (`API_SEC_15.md`), the web error seam of NFR-22 (`replayOnly.NFR-22.test.tsx`).

Tests: `services/api/tests/test_SEC_16_FEEDBACK_caps_config.py`, `test_SEC_16_FEEDBACK_route.py` (helper
`_feedback_lib.py`), `tests/repo/test_SEC_16_FEEDBACK_open_questions_rows.py`, and in `apps/web`:
`src/api/http.SPEND_CAPS_FEEDBACK.test.ts`, `src/components/LifetimeCapDialog.SPEND_CAPS_FEEDBACK.test.tsx`,
`src/screens/lifetimeCap.SPEND_CAPS_FEEDBACK.test.tsx`, `src/park/shell/LifetimeCap.SPEND_CAPS_FEEDBACK.test.tsx`
(support `test-support/lifetimeCap.ts`, which holds the exact copy). Test names carry `SEC_16` and `FEEDBACK`.

No contract change is needed: no new event type (nothing animates), no schema (the request body is a tilo-api pydantic
model like `DeclarationIn`; the record is tilo-api's own). If you want the body as a contract, that is a later ADR.

## Part 1: the caps (`config/spend_caps.yaml`)

| Key | Was | Now |
| --- | --- | --- |
| `run_minor` | 12000 (INR 120) | **50000** (INR 500) |
| `uid_lifetime_minor` | 100000 (INR 1,000) | **300000** (INR 3,000) |
| `global_day_hard_minor` | 200000 (INR 2,000) | **500000** (INR 5,000) |

Unchanged: `org_day_minor: null`, `unit_reserve_minor: 1000`, 240 requests per 60 s, and the replay-only fallback at the
daily cap (settling the UTC day to `>=` the hard cap, or a reserve that would exceed it, flips the durable switch; new
work is 503 `replay_only`). Update the comment on each line (INR amounts, "the user, 8 Oct"); the daily line keeps
"replay-only (NFR-24)". INR 5,000 a day is above PRD 17.3's US$25 at the 80 INR per US$ default: say so in
`BQ-SEC16-3`, which also says it supersedes the shipped values in `BQ-SEC16-1`.

No number is written anywhere but the config: not in `tilo_api` (tokenised scan for the old and new values) and not in
the web source (no amount in the pop-up: it says the allowance is used up, never how much).

Stale places the builder updates or the architect decides (the tests do not pin them, except where noted):

- `test_SEC_16_config.py::test_SEC_16_the_shipped_config_gives_each_uid_a_lifetime_cap_of_1000_inr_in_minor_units`
  asserts `100_000`: change it to `300_000` (the name too). Its `test_SEC_16_no_cap_number_is_written_in_code` scans for
  `100_000` only: the new test covers the new values.
- `API_SEC_16.md` ("The 1,000 INR cap is `uid_lifetime_minor: 100000`", the config table's "shipped: 100000", the
  literal `100000`): update (pinned by `test_SEC_16_FEEDBACK_the_api_doc_names_the_new_lifetime_cap`: it must contain
  `300000` and `3,000 INR`, and not `shipped: 100000`, `uid_lifetime_minor: 100000` or `1,000 INR cap is`).
- `contracts/fixtures/spend_caps/valid/shipped_defaults.json` (12000 / 100000 / 200000), the descriptions "SEC-16: 1,000
  INR" in `contracts/spend_caps.schema.json` and the generated `packages/contracts-py` and `contracts-ts` docstrings,
  `docs/adr/0002-contract-conventions.md` decision 16 ("`run_minor` 12000 ... `global_day_hard_minor` 200000"), the
  shipped values in `docs/open-questions.md` `BQ-SEC16-1`, and `docs/prd-supplement-2026-10-05.md` SEC-16 ("1,000 INR").
  These are contracts or read-only history: needs contract change (architect); the builder does not edit `contracts/`.
- `config/metering.yaml` run and daily caps are in credits and US dollars (FR-MTR-04, a different ledger) and are not
  part of this change; `packages/metering` NFR-27 alert thresholds take their cap as a parameter.

## The reason code (already exists)

The lifetime cap answers **403** with JSON `{"detail": <sentence>, "code": "spend_cap_reached"}` (`tilo_api.spend.
SpendCapReached`, handled in `tilo_api/__init__.py`; no new code is invented). It is the only 4xx the web keys the
pop-up on. The other limits keep their own answers and never carry it: the daily hard cap is the NFR-24 replay-only 503
`{"replay_only": true}`; a run at its per-run cap runs that unit as replay (`UnitPlan` reason `run`); the per-uid
request limit is 429 `rate_limited`; SEC-15's refusals are 403 `under_construction` and `declaration_required`.
The `detail` sentence carries no amount, no uid and is at most 200 characters (the web never shows it anyway).

## Part 2a: the web

`apps/web/src/api/http.ts`:

- `export function isLifetimeCap(error: unknown): boolean`: true only for a `TiloApiError` whose `status === 403` and
  `code === "spend_cap_reached"`. A look-alike object, a 409/422/500 with that code, or any other code is false.
- `HttpClient.submitFeedback(text: string): Promise<void>` (also on the `TiloClient` interface): `POST {base}/v1/feedback`,
  JSON `{"text": text, "context": "lifetime_cap"}` and no other key (the API takes the uid from the Bearer token), via
  the same `request` path (auth and App Check headers, `write` true). It resolves only for a 2xx whose JSON is
  `{"received": true}`; anything else rejects with a `TiloApiError` (a 204, `{}`, `received: false` or a non-JSON 2xx is
  `BAD_REPLY`, retryable). No automatic retry.
- Park `Api` (`park/api/index.ts`): a new method `submitFeedback(text: string): R<Ack>` in `API_METHODS` (so `noting`
  wraps it). Live: `http.submitFeedback`, answering `{data: {ok: true}, source: "live"}`. Fixture: any answer whose
  `source` is not `"live"` (the fixture world has no server, so it must never read as a confirmation). The method-list
  pins change with it: `park/api/liveApi.test.ts` (`READS`/`WRITES` lists, `toHaveLength(23)`, the call table),
  `liveApi.wire1.test.ts` and `liveApi.wire2.test.ts` (their `API_METHODS.filter(...)` not-built sweeps),
  `fixtureApi.test.ts`, `test-support/park/apiCalls.ts`, and `park/CLAUDE.md` ("23 methods"): 24.

`apps/web/src/components/LifetimeCapDialog.tsx` (beside `ReplayBanner`, so neither tree imports the other):
`export function LifetimeCapDialog({ submit, onClose }: { submit: (text: string) => Promise<void>; onClose: () => void })`.

Copy (exact; also `test-support/lifetimeCap.ts`):

- Title (the dialog's accessible name): **Beta allowance used**
- Body, three sentences in this order: "You have used your beta allowance for live models." "New plans and subscriptions
  come after beta testing ends." "If you liked Tilo, you can help by giving honest feedback and critique."
- Textarea label: **Your feedback**; buttons **Send feedback** (while sending: **Sending…**) and **Close**.
- After the server confirmed: "Thanks. Your feedback was received." in a `role="status"`.
- On any failure: "Your feedback was not sent. Your text is still here, so you can try again." in a `role="alert"`
  (never the server's words).

Behaviour: `role="dialog"`, `aria-modal="true"`, named by the title; focus moves inside on open; Escape and Close call
`onClose` and never send; a `<textarea maxLength={2000}>` of plain text (never `dangerouslySetInnerHTML`; markup typed
in is neither parsed nor escaped, and is sent byte for byte); Send is disabled for empty or blank text; "Thanks" shows
**only after `submit` resolves**, never while it is pending or after a rejection; a rejection keeps the text and lets the
person try again; a second tap while sending sends nothing more. Plain role tokens only: no colour literal, no
`rgb()/hsl()`, no inline colour, no image (checked by a source scan of `LifetimeCapDialog.*`). It names no amount, code or
server text. It owns no timer and no animation (HR-1).

Where it shows:

- **Kept flow screens**: `remote.ts` `useAction` returns `lifetimeCap: boolean` and the `useRemote` error state carries
  `lifetimeCap?: boolean`, both `isLifetimeCap(error)`. `Primary` (action) and `Loaded` (remote) render the dialog in the
  place of the generic error (no alert, no "Could not ...", no replay banner); its `submit` is `useClient().submitFeedback`.
  Close hides it; the next failure shows it again. Every other failure keeps today's alert, banner and retry.
- **Park**: `store.startWorld` (a `TiloApiError` that is `isLifetimeCap`) resolves `false`, adds no world, offers no
  Open, sets no toast, and the shell (`AppShell`) draws the dialog; its `submit` is `api.submitFeedback`, which counts as
  a confirmation only for `source === "live"`. The composer keeps the text and the plan card. Every other failure keeps
  its toast. (The state field and `dismiss` method names are the builder's.)

## Part 2b: `POST /v1/feedback`

Module `tilo_api/feedback.py` (`router`, included in `tilo_api.app`; dev mode and the tests use the same router),
`tilo_api/feedback_firestore.py`, seam `deps.get_feedback_store()`.

Request (application/json only, else 415; `extra="forbid"`): `{"text": str, "context": "lifetime_cap"}`. Both required.
`uid` is always `principal.user_id`; a body field, header or query named like a uid is refused (422) or ignored.
Answer **201** `{"received": true}` and nothing else (the text is never echoed). Record:
`{"uid", "text", "created_at", "context": "lifetime_cap"}`, `created_at` read once from `deps.get_clock()`
(a `common#timestamp`).

Text rules (the numbers are this spec's; the PRD names none): a string; at most **8000 raw characters** (422 before any
cleaning, so a 1 MB field of U+FDFA costs no NFKC or regex work: under 2 s of CPU); cleaned by removing control
characters (Cc, except newline and tab), format characters (Cf: zero-width, bidi, BOM) and the blank-looking
U+3164, then trimming; **1 to 2000 characters after cleaning** (empty or invisible-only is 422; 2001 is 422). No NFKC:
the stored text is what the person wrote minus the noise, so it cannot grow. Markup, quotes and template syntax are
stored unchanged (plain text; the web shows it only in a textarea or as text nodes). An invalid request uses no quota.

Who and how often: signed in (401), and deployed a declared judge (the access gate's 403s). The route is not in
`PUBLIC_ROUTES`; it counts toward the SEC-16 per-uid request limiter like every gated route. It is **not** a model
call: no router, no safety provider, no ledger write; a uid at its lifetime spend cap, or with the replay-only switch
set, can still send feedback. Limits per uid (constants in `tilo_api.feedback`): **5 per rolling hour** (a record
leaves the window exactly 3600 s after its `created_at`) and **20 in a lifetime**, checked lifetime first, atomically
with the write:

- hourly: 429 `{"detail", "code": "rate_limited"}` with `Retry-After` = whole seconds until the oldest counted record
  leaves the window (1 to 3600);
- lifetime: 429 `{"detail", "code": "feedback_limit_reached"}`, no `Retry-After`.

`FeedbackStore` protocol (one atomic method; a Firestore store does it in one transaction):
`add(*, uid, text, context, created_at, hourly_limit, lifetime_limit) -> AddResult`, with `AddResult.status` one of
`"stored" | "hourly_limit" | "lifetime_limit"` and `AddResult.retry_after_s: int | None` (set for `hourly_limit`).
`InMemoryFeedbackStore` implements it and has `records() -> list[dict]` (copies, insertion order, exactly the four
keys). `FirestoreFeedbackStore(client, *, org_id=deps.ORG_ID)` writes only under `orgs/{org_id}/feedback` (a per-uid
subcollection such as `orgs/org_tilo/feedback/{uid}/items/{id}` is fine); the test fake (`_ppl11c_fs_fake.FakeFirestore`)
serves `collection(path).stream()`, `document(path).get/create/set` and real transactions, and no `where` queries, so
count a uid's records by streaming its own collection (at most 20 documents). Seam: `deps.get_feedback_store()` opens
Firestore through `store_door` (`TILO_API_STORE=firestore`, ADR-0026) and otherwise raises 503 `not_configured`; dev mode
(`tilo_api.dev.install`) overrides it with an `InMemoryFeedbackStore`. Never log the text (a count of characters is fine).

Reading it back: there is **no read route for ordinary users**, and none at all in this ticket. `POST /v1/feedback` is
the only route whose path mentions feedback; no GET route returns the text (probed as two judges); only the feedback
modules, `deps.py`, `dev.py` and `__init__.py` mention it. The owner or admin read path is **deferred** (no admin
convention exists in `tilo_api`; the founder gate `TILO_PEOPLE_BOOTSTRAP_UID` is for the org, not for reading). Until it
exists the owner reads the collection in the Firebase console. `BQ-FEEDBACK-1` says so.

## Ambiguities resolved (stated defaults, also in the report)

1. The PRD has none of this. Reason code: the existing `spend_cap_reached` is reused (no new code).
2. Title and the sentences of the pop-up: the user's three ideas in plain words; "Beta allowance used" is the title.
3. Limits 5 an hour and 20 in a lifetime, 2000 characters, 8000 raw: picked here; the hourly refusal reuses the code
   `rate_limited` (the web treats every failed send alike), the lifetime refusal has its own code.
4. `context` is required, not optional, so a later second context is an addition, not a change.
5. Capped plus replay-only both set: the existing order stands (the switch is checked first: 503 replay-only); this
   ticket does not pin which of the two a person in both states sees.
6. Fixture mode never shows the pop-up (only a server 403 does) and never says Thanks.

## Hardening (security review r1; tests `test_SEC_16_FEEDBACK_hardening.py`)

- Body: 415 unless JSON; 413 over 65536 bytes before it is read; parsed from bytes; a 422 answers `{"detail": [{"loc": ...}]}` only.
- Invisible-only text (marks, separators, U+2800, fillers) is 422. Only a full (Google) sign-in may post: an anonymous demo session
  (`Principal.demo_session`) gets 403 `full_session_required`. A busy store is 503 `busy`.
- Firestore: slots `items/00..19` written with `create`; the read is bounded to `lifetime_limit + 1`.
