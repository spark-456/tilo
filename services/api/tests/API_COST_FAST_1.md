# COST-FAST-1: Quick / Thinking mode of `POST /intake` (what the acceptance tests pin)

Source: user decision, 8 Oct 2026. The person picks the mode on the website. **Quick** is a direct answer: the existing
`assistant` role (config/models.yaml: the lite tier, at most 8000 tokens in and 1000 out), no Director, low thinking,
at most 0.5 credits for a one-line question. **Thinking** is the full Director flow exactly as today (FR-INT-06:
approaches are not skipped for work). Today every ask runs intake, approaches and plan (about a 4.3-credit floor).

Tests: `services/api/tests/test_COST_FAST_1_*.py` (helpers `_costfast1_lib.py`, fixture `quick_rig` in `conftest.py`). No
frozen contract changes: **no new event type, no contract field** (see "Honesty"). New defaults are `BQ-COSTFAST-1..6` in
`docs/open-questions.md`.

## Request

`POST /intake` stays multipart (or urlencoded) with `text`, `files`, optional `scenario`. New optional form field
`mode`: exactly `quick` or `thinking` (lowercase, nothing around it). Absent means `thinking`, so nothing existing
changes.

| Case | Answer |
| --- | --- |
| no `mode`, or `mode=thinking` | today's 201 body plus `"mode": "thinking"`. The Director is the only role called; `GET /tasks/{id}/approaches` still returns 2 or 3 approaches. Always, even for a trivial question. |
| `mode=quick`, `mode` anything else (`Quick`, ` quick`, empty, `fast`, a long or hostile string), or two `mode` fields | 422 `{"error": <sentence>}` for a bad value, like a bad `scenario`; nothing stored, no model call, the value never echoed. Two `mode` fields are refused, never resolved silently. |
| `?mode=quick` in the query string | ignored: the form decides, so no form field is Thinking. |

Order (as today): sign-in (401), `replay_only` (503), a bad `scenario` or `mode` (422), limits and file types (422), the
safety screen on the text and the file names (422 flagged, 503 outage or no provider), then Quick's own rules.

## Quick answer: 200

```json
{"mode": "quick", "outcome": "answered", "text": "<the model's reply>", "cost": {"model_calls": 1, "credits": 0.04, "saved_credits": 0.0}}
```

Exactly those keys (`cost` is the panel's `_model_cost` shape). `text` is the model's plain reply, verbatim, bounded to
8000 characters (longer is cut or refused 502); it is never parsed, so a reply that looks like a typed response is still
only text. An empty reply is a 502. One call on role `assistant`: `tools` none, not JSON mode, `thinking_level` none,
`minimal` or `low`, `max_output_tokens` at most the role's 1000, a router `budget` of at most 0.5 credits (PL-03: a call
priced over it is never sent). Control and bidi/format characters are removed from the question before a model sees it.

## Switch offer: 200

```json
{"mode": "quick", "outcome": "switch_to_thinking", "reason": "<code>"}
```

Exactly those keys. Nothing is created or stored (no task, world, artifact, policy, event, desk), no model is called, no
ledger is touched: the cost of the rules classifier is zero. It is an offer, never a silent run as Thinking.

### Reasons (closed set)

`attachments` (any file with Quick, and the file is never read or stored), `side_effect` (send, post, delete, book...),
`deliverable` (a deck, report, PDF or spreadsheet to produce), `needs_tools` (search the web, read the inbox or calendar,
anything that needs a tool), `multi_step` (a long ask in several ordered steps), `too_long` (more characters than
`config/assistant.yaml` `question.max_chars`, 500: FR-PA-19, judged on the raw length), `scenario` (a valid `scenario` id
with Quick), `unclear` (the model fallback gave no valid verdict). Pinned exactly: the email, post and delete asks are
`side_effect`; the 12-slide deck, PDF report and spreadsheet are `deliverable`; the "first..., then..., then..." ask is
`multi_step`; a file is `attachments`; 501 characters is `too_long`; SC-01 is `scenario`. The other work asks only need a
reason from the set.

## The classifier

Deterministic and rules-first, in code, no model for a text a rule reads. It only suggests: Thinking chosen is always
Thinking, Quick chosen plus work is the offer, Quick chosen plus a simple question is the answer.

Model fallback, only for a text no rule decides, after the safety screen: one call on role `assistant`, `json_mode`
true. The reply is the closed shape `{"kind": "simple"}` or `{"kind": "work", "reason": <a reason of the set>}`, exact
keys, exact JSON types, no duplicate keys, no NaN, nothing before or after. A valid `simple` goes on to the answer call
(a plain, non-JSON call on `assistant`); a valid `work` is the offer with that reason; **anything else is no verdict and
is the offer with reason `unclear`** (no answer is written on the strength of a bad verdict). The classifier call and the
answer call share one half-credit budget. A model verdict can never override a rules verdict. Authorisation is never
asked of a model.

## What the Quick model sees

The `assistant` role elsewhere (the panel's `ModelDecider`) is shown the question, the screen name, the selected record
and the signed-in person's own plate rows (up to 40, gated by the PPL-10 oracle). Quick is shown **the question alone**:
no plate, no context, no store, no memory, no tools, no other person's data, no ids. One person's answer is never served
to another (no cross-person cache). The question and the answer are not logged and not archived.

## Honesty (PRD 9.4)

A Quick answer creates no world and animates nothing, so there is no Story line, no meter change in a world and no event
to cause one (HR-1). It writes no event: `assistant.replied` cannot carry it (`answered` needs at least one `sources`
record and a `message_ref` in the raw archive; a Quick answer cites no record), and nothing needs one. Its credits are
recorded in two places: the person's FR-PA-19 daily allowance (`deps.get_spend_ledger()`, reserve the budget before the
call, commit the actual after, release when the call fails; a day whose allowance cannot cover a call is 429
`{"error": ...}` before any model is called) and, deployed and live, the SEC-16 uid ledger. If the web must tick a meter
for Quick, that needs an event and is a contract change (BQ-COSTFAST-3).

## Limits

* NFR-24: `replay_only` set is 503 `replay_only: true` for Quick, answer or offer (before any work).
* NFR-22: every candidate failing on quota or availability is 503 `replay_only: true`, `code: model_unavailable`, for this
  request only. A rejected request or a bad reply is 502, no provider text echoed.
* No `assistant` role (for example `config/models.dev.yaml`): 503 `not_configured`, never a fallback to the Director.
* SEC-16, deployed and live: before the call one unit (`caps.unit_reserve_minor`, BQ-SEC16-1) is reserved on the uid
  ledger, after it settled, on failure released; a switch offer and a replay-mode judge never touch the ledger. At the
  cap, or when one more unit would pass it, Quick and Thinking are refused 403 `spend_cap_reached` before any model call.
  The per-uid rate limit counts Quick asks (429 `rate_limited`).
* Idempotency: optional `Idempotency-Key` header on a Quick ask (people_limits' rule). The same principal, key and body
  again is the first answer byte for byte, with one model call and one charge (also on the SEC-16 ledger); the same key
  with another question is 422; another principal's key is its own; a bad key (over 64 characters or outside
  `[A-Za-z0-9._-]`) is 422 and never echoed; a failed first attempt leaves the key free; racing retries make one call.

## What no test can settle

* Which texts the rules leave to the model fallback. The fallback tests apply to whatever the builder's rules leave
  undecided (the example texts `hmm`, `help`, `tell me about Q3` and the property test), so they are vacuous if the rules
  decide every text. The builder must say which texts go to the model.
* The exact rule words: the test corpus is the contract for the reasons above, not the PRD.
