# Meeting voice meter rules beyond the schema (meeting_voice_meter.schema.json 1.0.0, ADR-0042)

ADR-0042 is **Proposed** and waits on the user's answer to BQ-M2-5 (two new public routes on tilo-api). Until that
answer, this file and the schema are inert data: they add no route, no auth path and no event, and nothing reads
them. The schema checks one request or answer body; the rules below need tilo-api's attend claim, the ledger, the
config and the clock. tilo-api (ticket T2) checks MV-01, MV-02, MV-04 to MV-06, MV-08 to MV-11, MV-13 to MV-17; the
meet bot (T3) checks MV-07, MV-12 and its half of MV-10 and MV-16; the schema checks MV-03 and the shapes in MV-16
and MV-15's bound. `MV-` is this file's prefix; ids are stable. Tests: `tests/MV-*`.

## The attend header

The one value that is not in a body: tilo-api sends `X-Tilo-Meeting-Claim: <nonce>` on its own attend call to the
bot (`POST /internal/meetings/{meeting_id}/attend`, `MeetingBotRpc.attend`), a new `secrets.token_urlsafe(24)` for
that attend and nothing else. Its shape is `$defs.claim` (32 to 64 characters of `A-Za-z0-9_-`). It is not a field
of `MeetingJoin`, which stays 1.0.0 and is the owner's browser answer, and not in the attend body, which the bot
validates closed. The bot echoes it as `claim` in every call to the two routes and never logs or writes it.

## Answers and status codes

| Status | Body | When |
| --- | --- | --- |
| 200 | `reserve_answer` or `close_answer` | `live`, or `replay` with a `reason` (MV-07); `settled` or `released` |
| 401 | `error` `unauthenticated` | no Google ID token (MV-01) |
| 403 | `error` `forbidden` | any account but the bot's runtime account, or `email_verified` false (MV-01) |
| 409 | `error` `not_attending` | no claim, an expired claim or a wrong nonce, one answer and one timing (MV-14, MV-16) |
| 409 | `error` `no_hold`, `key_used` | a close with no open hold under this claim and key; a reserve of a closed key (MV-05) |
| 422 | `error` `invalid_request` | a body over 2 KiB, not JSON, not the schema, an extra field, `usage` above 16384 (MV-03, MV-06, MV-15) |
| 503 | `error` `not_configured` | a `TILO_VOICE_METER_*` setting missing or malformed, no ledger, the unit too small (MV-01, MV-15) |

## Rules

| Rule | Statement | Checked by |
| --- | --- | --- |
| MV-01 | Both routes verify a Google ID token (iss, aud = `TILO_VOICE_METER_AUDIENCE`, email = `TILO_VOICE_METER_CALLER`, verified) before reading the body; 401, 403, 503 as above. The caller pin is its own variable and differs from `TILO_SCHEDULE_TICK_CALLER` and `TILO_TASKS_CALLER`; the audience is the service URL only; equal or malformed is 503. | api |
| MV-02 | A claim exists only between the attend route's `joining` commit and its `finally`; its uid and org are the principal's. | api |
| MV-03 | A body holds only `meeting_id`, `claim`, `key` and, on close, `outcome` and `usage`; an extra field is 422. | schema; api |
| MV-04 | The hold amount is `unit_reserve_minor`; no request can change an amount, a cap, a price or the switch. | api |
| MV-05 | A close needs an open hold under the same claim and key; it is idempotent; a key is never reopened. | api |
| MV-06 | One open hold per claim, at most `max_speech_calls` reserves per claim, 2 KiB bodies. | api |
| MV-07 | Anything but 200 `live` is replay for that reply; the bot never speaks Live on its own word. | meet-bot |
| MV-08 | When a claim closes, open holds settle at the whole unit. | api |
| MV-09 | `usage` is priced in tilo-api from config only (the profile `voice.live.profile` names); unpriced or empty is the whole unit. | api |
| MV-10 | No log line, error or trace carries a token, a key's value or `usage`; access lines name route, status and reason. | api; meet-bot |
| MV-11 | No event, outbox entry or world write; no model call in the route. | api |
| MV-12 | The bot holds no ledger credential and imports no ledger code. | meet-bot |
| MV-13 | The two routes are exact entries of `access.PUBLIC_ROUTES` and `appcheck.EXEMPT_ROUTES` and nothing wider. | api |
| MV-14 | Without a claim in this process the answer is 409; there is no fallback that guesses a uid. | api |
| MV-15 | One reply books at most `unit_reserve_minor` (K = 1): a count above `max(8 x voice.live.max_output_tokens, 4 x voice.max_chars)` (a total above twice it) books the whole unit, a priced figure above the unit books the unit, a settle never exceeds its hold; a ceiling-sized reply priced above the unit is 503 `not_configured`. The schema's own bound of 16384 per count is 422. | schema; api |
| MV-16 | The attend route makes a random nonce per attend and hands it to the bot in `X-Tilo-Meeting-Claim`; reserve and close carry it as `claim` and compare it in constant time; a wrong nonce is the same 409 as no claim. | schema; api; meet-bot |
| MV-17 | A hold open longer than `hold_ttl_s` (3 x `voice.live.timeout_s`) is settled at the whole unit; a ledger hold carries `expires_at` and an expired one is settled at its amount. | api |
