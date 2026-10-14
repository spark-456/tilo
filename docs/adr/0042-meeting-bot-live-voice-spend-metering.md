# ADR-0042: The meeting bot meters its Gemini Live voice on the SEC-16 ledger through tilo-api, naming only the meeting

- Status: **Proposed** (13 Oct 2026; revised the same day for SEC-REVIEW-21: blocker B1, the bound on what one reply
  may book, and follow-ups 1 to 4, the claim nonce, hold expiry and the env pins). Nothing is built. It needs the
  user's answer to BQ-M2-5 (two new public routes on tilo-api) and a security re-check of decisions 2 to 9 and 14
  before any ticket starts. It changes no frozen contract: decision 10 adds one new file and leaves
  `meeting_join.schema.json`, `meeting_host_rpc.schema.json`, `spend_caps.schema.json` and the event registry
  untouched. (Next free number on `origin/phase0-stack`, every `origin/*` branch and every open PR at 13 Oct: 0040 is
  team-shared worlds, PR #899 and #915; 0041 is bring-your-own model key, PR #936. The merger may renumber.)
- Deciders: user (BQ-M2-5, the env sitting in "What the user must do"), architect (proposal), security-reviewer
  (decisions 2 to 9 and 14)
- Requirement: FR-MTG-11 (M2, M2b), FR-MTG-09; SEC-16, SEC-02, SEC-10, SEC-12; NFR-24; EFF-01; PL-01, PL-06; PRD 6.5,
  6.6, 16.1 (rules 2 and 4); ADR-0024, ADR-0026, ADR-0032 (HB-01, HB-02), ADR-0035
- Questions: closes the three needs of BQ-M2-4 (the owner's uid and org reaching the bot; the bot reaching the ledger;
  the worker building the hook). New BQ-M2-5 to BQ-M2-8. New rule ids MV-01 to MV-17 (no other prefix in the repo or
  on an open branch uses `MV-`).

## Context
1. **What is built and what is not (13 Oct).** The Gemini Live adapter is merged (PR #943, `GeminiLiveVoiceProvider`).
   PR #945 (open, `feat/M2b-live-voice-spend-gate`) adds the hook, `tilo_providers.voice.LiveVoiceMeter` (`reserve`,
   `settle(hold, usage)`, `release`; refusing or raising is a refusal), and `tilo_api.spend_voice.LiveVoiceSpend`, the
   hook over `SpendGuard`. PR #938 (`feat/GOLIVE-935-spend-ledger`, open) is the durable ledger
   `FirestoreSpendLedger` under `orgs/{org}/spend_ledger`, and PR #942 meters the API's own calls on it. Without a
   meter the adapter refuses to build the live factory and Chirp speaks, so nothing here can overspend today.
2. **The bot process cannot meter.** `meet-bot/bot/cloud_run.py` serves `POST /internal/meetings/{id}/attend` behind
   one OIDC caller check (tilo-api's account, `TILO_MEET_BOT_CALLER`). Its body is `MeetingJoin` (`join_url`,
   `expires_at`). `cloud_worker.attend_meeting(meeting_id, join_url)` builds a `LiveSession` whose
   `make_tts()` (`session.py`) takes no meter. The service runs as its own account with two project roles (Vertex
   generate, service usage consumer), ingress internal only, no Firestore, no OAuth tokens (`docs/CLOUD_RUN.md`;
   `meet_bot.tftest.hcl` pins "no data role"). It has no uid, no org and no ledger.
3. **`MeetingJoin` is not the bot's contract.** It is the answer of `GET /v1/meetings/{id}/join` to the owner's
   browser (ADR-0024 amendment 4, MJ-01 to MJ-10, 21 invalid fixtures), reused as the launch capability. Fields added
   to it would also reach every owner's browser.
4. **Where the identity already is.** `POST /v1/meetings/{id}/attend` runs inside tilo-api
   (`meeting_bot.attend_meeting`). It proves the signed-in principal is the meeting's owner and the world's owner
   (`_mine`, `owned_receipt`, MJ-01), claims the meeting `joining`, then holds the request open until the bot answers
   (`MeetingBotRpc.attend`, read timeout 3500 s). `w.actor` is the uid and `w.org` the org. The API is one instance
   (`max_instance_count` 1, ADR-0026) and is public (`INGRESS_TRAFFIC_ALL`).
5. **What a ledger can and cannot do about a hostile bot.** The bot's account holds Vertex generate, so a bot that is
   fully compromised can call Vertex without asking any ledger. No design below changes that. What it must not be able
   to do is affect another person's accounting, a cap, the kill switch or any data in tilo-api's database. The
   control is therefore on an honest bot that is faulty or prompt-injected through a meeting, and on attribution.
   The bound for a hostile one is project quota and the budget alert (the user's, outside this ADR). Inside the
   ledger a bot's word is never believed past what the reserve already admitted: a reply books at most its hold
   (decision 9).

## Decision
1. **The bot is never given a uid or an org (MV-03).** `MeetingJoin` stays 1.0.0. The bot names only the meeting id
   it already has (it came in the attend path), the claim nonce of decision 2 and a key of its own per spoken reply.
   Everything else is derived in tilo-api. A process that renders other people's words and writes Cloud Logging holds
   no identifier of a person it could be tricked into using elsewhere.
2. **An attend claim, made by the attend route and nothing else (MV-02, MV-16).** After the `joining` claim commits
   and before `bot.attend`, `meeting_bot.attend_meeting` registers one in a process-local `AttendClaims`:
   `meeting_id -> {uid: w.actor, org: w.org, run_id: meeting_id, nonce, expires_at: opened + 3500 s,
   holds: {key: (plan, reserved_at)}, reserves: n}`. It is closed in the existing `finally` (completion, failure,
   owner deletion, the caller's disconnect and the deadline all pass through it; an expired claim is refused before it
   is swept). The uid is the one the routes above already proved is the meeting's, world's and receipt's owner:
   derived from the stored records and the verified session, never from a body. There is no way to make a claim from
   the meter routes. `nonce` is `secrets.token_urlsafe(24)`, made for this one attend. It goes to the bot as the
   request header `X-Tilo-Meeting-Claim` of the attend call (not in `MeetingJoin`, not in the body the bot validates
   closed) and the bot echoes it as `claim` in every meter call. The ID token says "the bot process"; the nonce says
   "the process serving this meeting right now", so a bot bug or an injected meeting id cannot reach another claim's
   key space without a value only this attend's bot holds. The bot never logs it.
3. **Two routes on tilo-api, not on the bot's side (MV-01, MV-13).**

   | Route | Body (closed, 2 KiB at most, refused before parsing) | 200 answer |
   | --- | --- | --- |
   | `POST /internal/meeting-voice/reserve` | `{meeting_id, claim, key}` | `{decision: "live"}` or `{decision: "replay", reason}` |
   | `POST /internal/meeting-voice/close` | `{meeting_id, claim, key, outcome: "settled", usage}` or `{meeting_id, claim, key, outcome: "released"}` | `{outcome}` |

   `claim` is the attend header's value, 32 to 64 characters of `[A-Za-z0-9_-]`. `key` is 16 to 64 characters of the
   same alphabet, new for each reply. `usage` is the adapter's own whole-number counts (`prompt_token_count`,
   `response_token_count`, `total_token_count`, each optional, 0 to 16384, decision 9). `reason` is one of
   `capped`, `replay_only`, `unavailable`, `hold_open`, `meeting_limit`. Errors are a fixed code, nothing else
   (401 `unauthenticated`, 403 `forbidden`, 409 `not_attending`, 409 `no_hold`, 409 `key_used`, 422
   `invalid_request`, 503 `not_configured`). Ids travel in the body (ADR-0032), the path is fixed.
4. **Caller identity (MV-01)** is the schedule tick's pattern (`schedules.GoogleOidcVerifier`, one shared certificate
   cache), reversed in direction: a Google-signed ID token, `iss` Google, `aud` equal to `TILO_VOICE_METER_AUDIENCE`
   (tilo-api's own URL), `email` equal to `TILO_VOICE_METER_CALLER` (the bot's runtime account), `email_verified`
   true; a token that is not a Google JWT for this audience is refused from its header and claims before any
   certificate fetch. Both values are read per request from tilo-api's environment, never from the request, and they
   are variables of their own, never the schedule tick's or the Tasks one's: `TILO_VOICE_METER_CALLER` must differ from
   `TILO_SCHEDULE_TICK_CALLER` and `TILO_TASKS_CALLER` (equal or unset is 503 `not_configured`, so one setting can
   never open two doors), and `TILO_VOICE_METER_AUDIENCE` is the service URL only (`https`, a host, no path, query
   or fragment; anything else is 503). No token is 401, any other account 403 (tilo-api's own, the harness's, Cloud
   Scheduler's and Cloud Tasks' accounts included; and the bot's account gets 403 on the tick), either value unset
   503. There is no shared secret. Identity says "this is the bot process"; whose spend it is comes only from the
   claim, and which attend it serves only from the nonce.
5. **What the bot cannot name (MV-03, MV-04).** No uid, org, run id, hold id, amount, cap, price or time appears in
   either body, so the closed schema refuses them (422) and the code has nothing to read them from. The amount of a
   hold is `unit_reserve_minor` from `config/spend_caps.yaml`, set in tilo-api. `reset_replay_only` has no route and
   no guard method that a route reaches. A close cannot create a hold, and cannot book more than its hold (decision
   9).
6. **Reserve, in this order, all before the ledger is touched (MV-05, MV-06, MV-16).** Verify the caller; parse the
   closed body; find the claim by `meeting_id`, compare `claim` to its nonce with `hmac.compare_digest` and refuse an
   absent claim, a wrong nonce, an expired claim and a malformed id alike, as the same 409 `not_attending` from the
   same in-process lookup, so the bodies and the timing have one shape (SEC-REVIEW-21 follow-up 3); settle any hold
   of the claim older than `hold_ttl_s` (decision 14); a known `key` with an open hold answers the same `live`
   again, a closed one is 409 `key_used`; a different key while a hold is open is 200 `replay` `hold_open` (one
   spoken reply at a time); more than `max_speech_calls` (`config/meeting.yaml`) reserves in one claim is 200
   `replay` `meeting_limit`. Only then
   `LiveVoiceSpend(guard, uid=claim.uid, run_id=claim.run_id, org_id=claim.org, unit_minor=unit_reserve_minor,
   price=...)`: it refuses a capped uid, the replay-only switch in either store, less than one unit of headroom and
   an unreadable ledger, and each is 200 `replay`. The idempotency scope is the claim (an in-memory map from `key` to
   the `UnitPlan`); `FirestoreSpendLedger.reserve`'s optional `unit_id` is not needed.
7. **Close (MV-05, MV-08, MV-15).** The caller and the claim and nonce are checked as in decision 6. A `key` with no
   open hold in the claim is 409 `no_hold`: a settle without a reserve, a settle of another meeting's key and a
   second settle after a release all land there. The same close repeated answers as the first did and counts
   nothing twice. `settled` books the bounded charge of decision 9 and calls `settle_unit`; `released` calls
   `abort_unit` (the adapter sends it only when no model was reached). When the claim closes, every hold still open
   is **settled at the whole unit, not released**: a reply the bot never closed may have reached the model, and the
   count then can only be too high (BQ-GOLIVE935-3 (b)'s direction).
8. **Fail closed, everywhere (MV-07).** Any answer that is not a 200 `live` is no Live voice for that reply: the
   bot's hook returns None, the adapter raises `NotConfigured`, and the local voice speaks (BQ-M2-4's behaviour). A
   settle or release that fails is retried once with the same key and then dropped, never raised into the voice,
   and the sweep in decision 7 closes it.

   | Condition | Answer | The bot |
   | --- | --- | --- |
   | No claim, expired claim, tilo-api restarted mid-meeting, a second API instance | 409 `not_attending` | local voice |
   | uid at its lifetime cap, under one unit left, replay-only in either store, ledger unreadable | 200 `replay` | local voice |
   | `TILO_VOICE_METER_*` unset on tilo-api, the caller pin equal to the tick's, no ledger wired, or the unit too small for the price (decision 9) | 503 `not_configured` | local voice |
   | Bot has no `TILO_API_URL`, no claim header (an older image), no ID token, a timeout (2 s), a redirect, an answer over 1 KiB or off-contract | no call or error | local voice |
   | A wrong nonce, or the nonce of another attend | 409 `not_attending` | local voice |
   | A lost `settle`, or a hold the bot never closed | sweep at `hold_ttl_s` or at claim end | one unit counted |
9. **What one reply can book is bounded by config, never by the body (MV-09, MV-15).** `usage` comes from the least
   trusted process, so tilo-api never books what it says past the hold the reserve already put under every cap.
   - **K = 1.** A settle books at most `unit_reserve_minor`, the amount of the hold. The totals therefore never pass
     what the reserve admitted: the cap tests at reserve stay exact, and no close, however it lies, moves a uid past
     its lifetime cap, a run past its cap or the day past its hard cap (a uid with one unit left can still spend that
     unit and nothing more). This is the one place the meter departs from MT-03's "an overrun is recorded in full",
     which is for figures tilo-api measures itself; here the figure is the bot's.
   - **The ceiling.** `ceiling = max(8 x voice.live.max_output_tokens, 4 x voice.max_chars)` tokens, from
     `config/voice.yaml` (shipped: max(8 x 256, 4 x 400) = 2048). The first term is a generous multiple of the model's
     own cap for one reply; the second is the UTF-8 bytes of the longest text a reply may carry (a token never
     covers less than a byte). Any one count above the ceiling (`total_token_count` above twice it, being the sum
     of the other two) is not believed: the reply books the whole `unit_reserve_minor`, never the priced amount.
   - **The price.** A count at or under the ceiling is priced from `config/prices.yaml` for the profile
     `voice.live.profile` names (read from config, so no model id in code, PL-01) at
     `spend_units.INR_MINOR_PER_USD`, rounded up, at least 1 paisa, then `min(priced, unit_reserve_minor)`. A profile
     with no row, or empty `usage`, books the whole unit (BQ-SEC16-1). The bot reports counts, never money.
   - **Start-up invariant.** The first request after a settings or config change prices a ceiling-sized reply; above
     `unit_reserve_minor` the routes answer 503 `not_configured` (a Live profile priced so high that one unit would
     under-book it: the user raises the unit or fixes the row) rather than book less than the truth in silence.
   - **The contract.** Each count is 0 to 16384, which is 8 times the loader's own maximum for `max_output_tokens`
     (2048): the schema is as wide as the widest valid config's ceiling and no wider, so an oversize count is a 422
     before any code runs (the bot's settle then fails and the sweep books the unit, the same figure). A count
     between the config ceiling and 16384 passes the schema and books the unit.
   - Approving a current regional Live quote (`voice.live.price_approved`, PL-06) and adding that price row are one
     user step (BQ-M2-8).
10. **One new contract file, and nothing else changes (MV-03).** `contracts/meeting_voice_meter.schema.json` 1.0.0
    (`MeetingVoiceMeter`): the two requests, the two answers and the error, every object closed, no null, valid and
    invalid fixtures, generated Python and TypeScript. It is a new file because the direction (bot to tilo-api) and
    the callee differ from `meeting_host_rpc` (tilo-api to connectors), and because ADR-0041 also proposes an
    additive bump of that file. Exact diffs are under "Contract changes".
11. **The bot side (MV-12).** A `RemoteLiveVoiceMeter` in `meet-bot/bot/` implements `LiveVoiceMeter` with `urllib`
    or `httpx`, no redirects, 2 s timeouts, an ID token minted from the metadata server for audience `TILO_API_URL`
    (google-auth, cached by the library), the contract's request built from `meeting_id`, the `claim` it read from
    the attend call's `X-Tilo-Meeting-Claim` header and a fresh `secrets.token_urlsafe(24)` key. It is built only when
    `LIVE=1`, `TILO_API_URL` is set and the header was present (an older image or caller has none, so it stays on
    Chirp); `cloud_worker.attend_meeting` takes the claim beside `meeting_id` and `join_url` and passes the meter
    through `LiveSession` to `make_tts(meter=...)`. The claim is held in memory only and never logged or written to
    `out/` or `debug/`. The bot gets no Firestore client, no `tilo_api` import,
    no new role: `meet_bot.tftest.hcl`'s "no data role" assertion stays true and a repo test pins that `meet-bot/`
    imports neither `google.cloud.firestore` nor `tilo_api`.
12. **Not a side effect, not an event (MV-11).** The meter authorises nothing the bot says (FR-MTG-11's safety rules
    are unchanged) and writes no event, outbox entry, card or world change; nothing animates (HR-1). The ledger is
    the SEC-16 record, not the event stream. A model decides none of it (SEC-16: deterministic code).
13. **Single instance, stated (MV-14).** The claim is in the API process, like the attend request itself. A second
    instance would answer 409 `not_attending` and the bot would stay on Chirp, never unmetered. Moving the claim and
    its nonce into the meeting record (`joining`) is the follow-up if the API ever scales past one instance.
14. **Holds expire (MV-17).** (a) In the claim: a hold carries its reserve time; one open longer than
    `hold_ttl_s = 3 x voice.live.timeout_s` (shipped 20 s, so 60 s; the loader's maximum for the timeout is 60 s, so
    180 s) is settled at the whole unit by the next reserve, close or sweep of that claim, and is then not open. A bot
    that dies in the middle of a reply therefore does not hold the meeting's Live voice until the claim ends (fail
    closed, one unit counted). (b) In the ledger: SEC-REVIEW-15 and BQ-GOLIVE935-3 (b) leave a hold nobody closed (an
    API restart, a lost claim) held for good, with no sweeper. The ledger's `hold:{unit id}` document gains
    `expires_at` (reserve time plus one hour, above any claim's 3500 s), and an expired `held` hold is settled at its
    own amount by the next reserve of that uid and by the schedule tick: the count is what it already was and only its
    status closes. That is a change to PR #938's module (ticket T5), and not a precondition of T2 and T3: at most one
    stranded unit per meeting, counted too high.

## Rules (for `meeting_voice_meter.rules.md` and the tests)
| Rule | Statement |
| --- | --- |
| MV-01 | Both routes verify a Google ID token (iss, aud = `TILO_VOICE_METER_AUDIENCE`, email = `TILO_VOICE_METER_CALLER`, verified) before reading the body; 401, 403, 503 as above. The caller pin is its own variable and differs from `TILO_SCHEDULE_TICK_CALLER` and `TILO_TASKS_CALLER`; the audience is the service URL only; equal or malformed is 503. |
| MV-02 | A claim exists only between the attend route's `joining` commit and its `finally`; its uid and org are the principal's. |
| MV-03 | A body holds only `meeting_id`, `claim`, `key` and, on close, `outcome` and `usage`; an extra field is 422. |
| MV-04 | The hold amount is `unit_reserve_minor`; no request can change an amount, a cap, a price or the switch. |
| MV-05 | A close needs an open hold under the same claim and key; it is idempotent; a key is never reopened. |
| MV-06 | One open hold per claim, at most `max_speech_calls` reserves per claim, 2 KiB bodies. |
| MV-07 | Anything but 200 `live` is replay for that reply; the bot never speaks Live on its own word. |
| MV-08 | When a claim closes, open holds settle at the whole unit. |
| MV-09 | `usage` is priced in tilo-api from config only (the profile `voice.live.profile` names); unpriced or empty is the whole unit. |
| MV-10 | No log line, error or trace carries a token, a key's value or `usage`; access lines name route, status and reason. |
| MV-11 | No event, outbox entry or world write; no model call in the route. |
| MV-12 | The bot holds no ledger credential and imports no ledger code. |
| MV-13 | The two routes are exact entries of `access.PUBLIC_ROUTES` and `appcheck.EXEMPT_ROUTES` and nothing wider. |
| MV-14 | Without a claim in this process the answer is 409; there is no fallback that guesses a uid. |
| MV-15 | One reply books at most `unit_reserve_minor` (K = 1): a count above `max(8 x voice.live.max_output_tokens, 4 x voice.max_chars)` (a total above twice it) books the whole unit, a priced figure above the unit books the unit, a settle never exceeds its hold; a ceiling-sized reply priced above the unit is 503 `not_configured`. |
| MV-16 | The attend route makes a random nonce per attend and hands it to the bot in `X-Tilo-Meeting-Claim`; reserve and close carry it as `claim` and compare it in constant time; a wrong nonce is the same 409 as no claim. |
| MV-17 | A hold open longer than `hold_ttl_s` (3 x `voice.live.timeout_s`) is settled at the whole unit; a ledger hold carries `expires_at` and an expired one is settled at its amount. |

## Options considered
**How the bot gets the uid and org**

| Option | Why not (or why) |
| --- | --- |
| Add optional `owner_id` and `org_id` to `MeetingJoin` | Contract change to a response the browser also receives; the bot would then assert them back to the ledger route, so tilo-api would trust a body, which the brief forbids; ids sit in a process that logs other people's words. |
| A signed capability (HMAC of uid, org, meeting) in the attend body | Closes the trust gap but needs a signing key in two services and still hands the bot identifiers. More machinery than the claim. |
| **The bot names the meeting; tilo-api resolves it from its own state (chosen)** | The lookup is the attend claim, which the attend route made from the verified session, bound to this attend by a random nonce the bot echoes (no key to manage: tilo-api keeps the claim and compares). No contract change to `MeetingJoin`, no person's id in the bot. |

**How the bot meters**

| Option | Why not (or why) |
| --- | --- |
| Bot's account gets `roles/datastore.user` and writes `orgs/{org}/spend_ledger` | IAM conditions name a database, never a collection, so the bot could read and write every world, person and meeting. The ledger's keys carry the uid, so IAM cannot stop it naming another person's, zeroing a counter or resetting the switch. A separate `tilo-spend` database (as `tilo-tokens` was) fixes only the first half. It also needs `tilo_api` or a shared spend package in the bot image and breaks the pinned "the guest bot holds no data role" assertion of `meet_bot.tftest.hcl`. Rejected. |
| A budget lease: tilo-api reserves N units at attend start and sends N to the bot; usage comes back in the response | No inbound route and no new public path, but the kill switch (NFR-24) would be read once at attend start, up to 45 minutes before the last reply; N holds count against the uid for the whole meeting; a crash settles all N; it needs a new attend body or header. Kept as the fallback if the user answers no to BQ-M2-5. |
| **A per-reply reserve and close route on tilo-api (chosen)** | The switch, the uid cap and the day cap are read for every reply; only holds that began are counted; the bot holds no ledger code or credential. Cost: two public routes (BQ-M2-5) and one in-region round trip before a reply's first audio. |

## Contract changes (exact; for the contracts PR that follows)
- **New** `contracts/meeting_voice_meter.schema.json`, `$id` `https://contracts.tilo.example/meeting_voice_meter.schema.json`,
  `x-version` 1.0.0, `title` `MeetingVoiceMeter`, root `anyOf` of the `$defs` below (as `meeting_host_rpc` does).
  - `claim`: string, `pattern` `^[A-Za-z0-9_-]{32,64}$` (the attend call's `X-Tilo-Meeting-Claim` value; the
    description names the header, which is not otherwise a contract).
  - `key`: string, `pattern` `^[A-Za-z0-9_-]{16,64}$`.
  - `usage`: object, `additionalProperties` false, optional `prompt_token_count`, `response_token_count`,
    `total_token_count`, each integer 0 to 16384 (`maximum`: 8 times the loader's own maximum for
    `voice.live.max_output_tokens`, decision 9; not 10^8).
  - `reserve_request`: closed, required `meeting_id` (`common.schema.json#/$defs/meeting_id`), `claim`, `key`.
  - `reserve_answer`: closed, required `decision` (`live` or `replay`); `reason` (`capped`, `replay_only`,
    `unavailable`, `hold_open`, `meeting_limit`) required when `decision` is `replay` and absent when `live`
    (`if`/`then`, so the generated type stays a plain object and no null is needed, ADR-0011).
  - `close_request`: closed, required `meeting_id`, `claim`, `key`, `outcome` (`settled` or `released`); `usage`
    required when `settled` and absent when `released`.
  - `close_answer`: closed, required `outcome` (`settled` or `released`).
  - `error`: closed, required `error` in `unauthenticated`, `forbidden`, `invalid_request`, `not_configured`,
    `not_attending`, `no_hold`, `key_used`.
- **New** `contracts/meeting_voice_meter.rules.md` carrying MV-01 to MV-17 above and the header's name and shape,
  and a `contracts/README.md` row.
- **New fixtures** `contracts/fixtures/meeting_voice_meter[.<def>]/valid|invalid/`. Valid: a reserve request; a `live`
  answer; a `replay` answer per reason; a settled close with full, partial, empty and exactly-16384 `usage`; a
  released close; both close answers; each error code. Invalid, one rule each: a reserve request with `user_id`,
  `org_id`, `run_id`, `amount_minor` or `hold` (each its own file); a request without `claim`; a `claim` of 31 and of
  65 characters, with a space, with a newline; a `key` of 15 and of 65 characters, with a space, with a newline; a
  `meeting_id` without `mt_`; a `live` answer with a `reason`; a `replay` answer without one; a settled close
  without `usage`; a released close with `usage`; `usage` with a negative, a float, a string, an unknown key and a
  count of 16385 or 100000000 (the old bound); an `outcome` of `closed`; an error with an unknown code or an extra
  field.
- **Unchanged:** `meeting_join` 1.0.0, `meeting_host_rpc` 1.2.0, `spend_caps` 1.1.1, `meeting` 1.2.0, `common` and
  the event registry. No new event type, so no registry, no web registry file and no event fixture.
- **Not contracts:** `config/` gains no key (`voice.live.*`, `spend_caps.yaml`, `meeting.yaml` are used as they are).
  The two env pairs are settings, listed below. Registry-style pins to touch: the `PUBLIC_ROUTES` and
  `EXEMPT_ROUTES` pins in `services/api/tests` (MV-13).

## Test plan
Acceptance tests are written first (`tests/MV-*`), names carry `FR_MTG_11_SEC_16_BQ_M2_4`. No paid call and no
`LIVE=1`: a fake verifier, `InMemorySpendLedger` and the Firestore emulator suite, the replay Live provider.
- **tilo-api, caller (MV-01):** no token 401; a token for another audience, another account (tilo-api's, the
  Scheduler's, the Tasks account) and `email_verified` false are 403; either env unset 503; the caller pin equal to
  `TILO_SCHEDULE_TICK_CALLER` or `TILO_TASKS_CALLER`, or an audience with a path or query, 503; a body over 2 KiB or
  not the schema 422, and an extra `user_id`, `org_id`, `run_id` or `amount_minor` 422; a malformed token fetches no
  certificate.
- **tilo-api, claim, nonce and uid (MV-02, MV-16):** a reserve with no claim is 409; a claim for meeting A never
  meters meeting B; a wrong nonce, the nonce of an earlier attend of the same meeting and a nonce of another meeting
  are the same 409 with the same body as no claim; the nonce is compared with `hmac.compare_digest`; a claim closes
  on success, failure, cancellation and the deadline, and a reserve after it is 409; two owners attending one after
  the other leave spend on their own uid only (ledger read-back).
- **tilo-api, the bound on a reply (MV-15, SEC-REVIEW-21 B1):** a close with a count above the config ceiling books
  `unit_reserve_minor` and not the price; a priced charge above the unit books the unit; a close of 16384 in every
  field cannot move a uid that has exactly one unit left past its lifetime cap, a run past `run_minor` or the day
  past its hard cap in one call (ledger read-back after the close); a count of 16385 is 422 and the sweep books the
  unit; the ceiling follows `max_output_tokens` and `max_chars` when the config changes; a ceiling-sized reply priced
  above the unit makes both routes 503 `not_configured`.
- **tilo-api, ledger:** a capped uid, less than one unit left, the switch in the flag store and in the ledger, an
  unreadable ledger and a trip of the day's hard cap in the middle of a meeting each give 200 `replay` for the next
  reply; the hold equals `unit_reserve_minor` whatever the body says; a repeated reserve and a repeated close count
  once; a close with no reserve, a second settle after a release and a reopened key are 409; one open hold at a time;
  the sweep settles an open hold at the whole unit; unpriced and empty `usage` charge the unit; priced `usage` within
  the ceiling rounds up to at least 1 paisa.
- **tilo-api, hold expiry (MV-17):** a hold open past `hold_ttl_s` is settled at the unit by the next reserve and
  that reserve may go live; a ledger hold carries `expires_at` and an expired `held` hold is settled at its amount
  with the totals unchanged (the emulator suite, ticket T5).
- **tilo-api, privacy (MV-10):** no log line, error body or exception text contains the token, the nonce, a key or
  `usage` (caplog).
- **Pins:** `PUBLIC_ROUTES` and `EXEMPT_ROUTES` hold exactly two new entries; the bot's account still holds only the
  two roles in `meet_bot.tftest.hcl`; `meet-bot/` imports neither `google.cloud.firestore` nor `tilo_api`.
- **meet-bot:** a 200 `live` gives a hold; a non-200, a timeout, a redirect, a bad body, a missing env, a missing
  token and a missing claim header each return None and the voice is Chirp; a failed settle never raises into the
  voice; the request body's keys are exactly the contract's and `claim` is the header's value; the claim is in no
  log line, `out/` or `debug/` file; the ID token's audience is `TILO_API_URL`.
- **End to end (in process):** the bot's meter over the API app by ASGI transport, a claim made by the real attend
  route with a fake bot, a replay Live reply, ledger read-back. The user's X4 probe records the real round trip.

## What the user must do
1. **Answer BQ-M2-5:** may tilo-api gain two public routes, `POST /internal/meeting-voice/reserve` and `.../close`,
   each checking its own Google ID token like the schedule tick (default: yes). On no, the lease option above is the
   fallback and decisions 2 to 9 are redone.
2. **No new IAM role, no Terraform change** is needed (the bot already mints ID tokens from its metadata server and
   tilo-api is `allUsers`-invokable). After the build tickets are deployed, set, with `gcloud ... update-env-vars` as
   `docs/CLOUD_RUN.md` does: on tilo-api `TILO_VOICE_METER_AUDIENCE` (its own URL) and `TILO_VOICE_METER_CALLER` (the
   bot's runtime account email, which must not be the Scheduler's or the Tasks account); on the bot `TILO_API_URL`
   (the same URL). The bot's environment is Terraform-managed, so a later apply resets it, which only turns the Live
   voice off.
3. **Keep the gates that already exist:** `LIVE=1` on the bot and tilo-api (yours alone), a ledger on tilo-api
   (`TILO_FIRESTORE_PROJECT`, GOLIVE-935), `voice.live.price_approved: true` once you approve a current regional Live
   quote and its price row (PL-06), then `voice.live.enabled: true`.
4. **Merge order:** #938, #942 and #945 first (this ADR's tickets import their code); then T2 and T3 below.
5. **Know the unit price:** until the Live profile has a price row, a spoken reply that reaches the model costs the
   whole 10 INR unit; at the shipped caps that is 15 replies per meeting (150 INR run cap) and 50 in a uid's life
   (500 INR), shared with every other live call. Approving the quote in step 3 removes this. A reply never books more
   than that one unit (K = 1, decision 9), so a lying bot cannot cost a person more than 10 INR a reply.

## Consequences
- The bot never learns who owns a meeting and holds no ledger access; the pinned "no data role" assertion of
  `meet_bot.tftest.hcl` stays true as it is.
- The Live voice becomes meterable and killable per reply: a tripped switch or a capped uid stops the next reply at
  once, and the bot degrades to its local voice as it already does.
- tilo-api gains two public routes and one process-local registry. Both are small; the registry is why the API stays
  one instance for this feature (decision 13).
- One extra in-region HTTPS call (reserve) sits before a Live reply's first audio. BQ-MTG11-13's target is about 1 s to
  first audio; the budget for the call is 150 ms and the X4 probe measures it. If it is too slow, the reserve for the
  next reply can be asked while the current one plays; that changes no contract.
- Residual trust: tilo-api believes the bot's `usage` and its `released` only downward. A bot can under-report (a
  reply books as little as 1 paisa when priced, or claim `released`), never over-report: no reply books more than
  its hold, so a lying close cannot lock a person out past the cap their reserve already admitted. A bot that lies
  or calls Vertex directly is not stopped by the ledger; the project quota and the budget alert are its bound
  (Context 5). The count is a lower bound for such a bot and exact for an honest one.
- Out of scope, and unchanged: the bot's other paid calls (the `meeting` and `meeting_fast` roles, speech to text,
  Chirp) stay bounded by `config/meeting.yaml` counts (BQ-MTG11-9). The meter carries one Live reply per unit; more
  unit kinds would be a minor bump of the new file (BQ-M2-7).

## Tickets (small, in this order; each under 400 hand-written lines, acceptance tests first)
- **T1 (architect, S).** The contract file, rules, fixtures, README row, codegen (decision 10 and "Contract
  changes"). Additive. No Opus.
- **T2 (reach-builder, api, M).** `AttendClaims` with the nonce and `hold_ttl_s` and its registration in
  `meeting_bot.attend_meeting` (the header on `MeetingBotRpc.attend`); the two routes with MV-01 and MV-13; the
  bounded price hook and the start-up invariant (MV-15); the sweep. Security review. Split the routes from the claim
  registry if it passes 400 hand-written lines.
- **T3 (reach-builder, meet-bot, S).** `cloud_run.launch` reads `X-Tilo-Meeting-Claim`; `RemoteLiveVoiceMeter`, the
  `LiveSession` and `cloud_worker` wiring, the import pin.
- **T4 (reach-builder, docs and infra, S).** `docs/CLOUD_RUN.md`, `infra/ACCESS.md` and, if the user wants the two
  env pairs in Terraform, the variables (a plan with no destroy; the user applies).
- **T5 (reach-builder, api, S).** The ledger's hold `expires_at` and the expired-hold settle in
  `FirestoreSpendLedger` (PR #938's module, after it merges), emulator suite (MV-17(b)). Not a precondition of T2/T3.
- **Then the user:** BQ-M2-5, the env, the price approval and flip, the X4 probe, one live meeting with
  `tilotesting@gmail.com`.
