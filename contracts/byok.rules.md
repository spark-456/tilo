# BYOK rules beyond the schemas (ADR-0041)

Covers `byok.schema.json` 1.0.0, `org_model_key.schema.json` 1.1.0, `model_call_rpc.schema.json` 1.0.0,
`meeting_host_rpc.schema.json` 1.3.0 (the `model_key_*` defs) and `providers.schema.json` 1.4.0 (`credential`).

ADR-0041 is **Proposed**. Until the user accepts it and `config/byok.yaml` `enabled` is true, these files are inert
data: no route, adapter or Router reads them, and the new fields change nothing for a Tilo-keyed unit. The rule ids
`BK-01` to `BK-22` are the ADR's (no other prefix in the repo uses `BK-`); the ADR is the full text, this file says
what each means for a contract and who checks it. Tests: `tests/contracts/test_BYOK_*`, `tests/BYOK-*`.

## Cross-document checks (the loader; reference check in `tests/contracts/test_BYOK_contract.py`)

`fixtures/byok/crossref/{valid,invalid}` hold `{byok, providers}` pairs (`providers` is the Providers root). Each
document validates against its own schema; only these rules compare them, and each invalid case breaks exactly one:

| Rule | Statement |
| --- | --- |
| BK-12 | Every profile a bundle names exists and has `credential: org`; no Tilo role (`primary`, `fallback`, `cascade`) names a profile with `credential: org`, bundle or no bundle. |
| BK-13 | Every role a bundle names is a role of `config/models.yaml` (the schema already refuses `safety`, `search`, `speech`). |
| PL-06 | Every profile a bundle names has a price: `prices.status` is `set` and `input` and `output` are numbers. No price, no metering, no call. |

## Rules

| Rule | What it means for the contracts | Checked by |
| --- | --- | --- |
| BK-01 | Only tilo-connectors holds any Secret Manager role on `byok-*`; no contract field names a secret. | infra test; schema |
| BK-02 | The key is in `put_request.key` and `model_key_put_request.key` only (both `x-no-store`); a refused body answers a fixed `error.detail`, never its input; no other object has a key field. | schema; api |
| BK-03 | The secret is `byok-<24 hex of sha256("tilo/byok/" + org_id)>-models`; it comes from `org_id` and `slot`, never a body field. | connectors |
| BK-04 | `reference`, `member_view`, `owner_view` and `model_key_status_answer` hold no key character, length, hash or last four. | schema |
| BK-05 | Only the org owner (directory `org_role`, PE-17, on a full session) sets, rotates or removes; never `Principal.role`. | api |
| BK-06 | `confirm` is `true` and `consent_version` is the config's; `auth_time` at most 10 minutes old (401 `reauth_required`). | schema (shape); api |
| BK-07 | Set, rotate, bundle, fallback on, a higher cap and resume are T3 person acts (`org_model_key_change`); pause, a lower cap, fallback off and removal are immediate. `audit_entry.authz` is `by: person`, `ref` equals `actor`, `at` equals `at` (validator). | schema; api |
| BK-08 | The org is the principal's, never a body, path or query field; JSON only; 5 widening acts per org per hour (429 `rate_limited`, `Retry-After`). | schema; api |
| BK-09 | One seam, `OrgProviderSource`; variant P (proxy) is `model_call_rpc`; no credential type exists in tilo-api. | providers; tests |
| BK-10 | A bundle's profiles replace a covered role's candidates; generate-only: `request` has no `parts`, no stream, no embed. | schema; providers |
| BK-11 | Custody lasts one call; a removal or rotation takes effect at the next call. | connectors |
| BK-12 | Cross-document check above, plus `profile.credential` (1.4.0): openai_compat only, never with `api_key_env`, needs `base_url`. | schema; loader |
| BK-13 | A bundle names no `safety`, `search` or `speech`; `kind` is `openai_compat` only (the Google modes wait for BQ-BYOK-2 as an additive minor); fallbacks are its own. | schema; loader |
| BK-14 | Spend is tagged `payer: tilo` or `org_key`. **Not applied**: `trace.payer` needs the user's yes (below). | metering |
| BK-15 | An org-key unit touches no Tilo cap and no SEC-16 ledger; MT-02 sums `payer: tilo` only. | metering; api |
| BK-16 | `day_cap_credits` is 1 to `day_cap_credits_max` (the schema checks the 1, the route the ceiling); UTC day; reserve plus 15%. | schema; api |
| BK-17 | Fail-closed order; three refusals then one re-validation; provider text never relayed: `last_error`, `error` are fixed codes. | schema; api; connectors |
| BK-18 | No model decides whether BYOK is on, which key, bundle, cap or fallback, or any tier or gate. | policy tests |
| BK-19 | Fixed https host per profile, no redirect, resolved-address check, 3 s; the org supplies no URL (bundles have no URL field). | schema; connectors |
| BK-20 | A member reads `member_view` only; personal-scope units use Tilo's key (BQ-BYOK-3). | schema; api |
| BK-21 | Variant P is the default; a `lease` route and any credential type in tilo-api need the user's explicit yes (BQ-BYOK-7): none is in these contracts. | schema; tests |
| BK-22 | A leak test over a failing unit and a failing `put` finds no key character anywhere. | tests |

## `owner_view` of a key whose bundle left the config (BQ-BYOK-RECON-1, BQ-BYOKC-7)

When the reference's `bundle_id` is no longer in `config/byok.yaml`, every unit is refused `not_configured` (SEC-REVIEW-29
B4, BQ-BYOK-FIX-2), so the owner's `GET` shows the stored `state`, `active: false` and `last_error: not_configured`.
The schema says what a valid answer is (`owner_last_error`; `active` true exactly when `state` is `active` and
`last_error` is not `not_configured`); the route decides when a bundle has left, because only it reads the config.
The stored `reference.last_error` never holds `not_configured`, and `member_view` has no `last_error` at all.

## Proposed, not applied: `trace.payer` (BK-14, the user's yes needed, BQ-BYOKC-3)

`event.schema.json` is frozen at CP0 and ADR-0041 says it needs the user's yes first (as ADR-0022 did). It is **not**
changed here. If the user says yes, the additive minor (event 1.3.0 or the next free minor) adds to `$defs.trace`:

```json
"payer": {
  "description": "Whose credential and whose meter the model calls behind this event used (ADR-0041 BK-14): tilo or org_key. Left out means tilo; never null.",
  "type": "string",
  "enum": ["tilo", "org_key"]
}
```

It is optional, so no fixture, stream or `EV-xx` rule changes; a fallback unit (BK-17 step 5) records `payer: tilo`.
`RouterAttempt.payer` (PR #962) already carries it; `LedgerEntry.payer` is `packages/metering` code.
