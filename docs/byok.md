# Bring your own model key (ADR-0041, issue 934): build state, flag and contract asks

Status: built INERT behind a config flag, variant P (the proxy). Nothing here is live and nothing is deployed. This page
is the operator's and the reviewers' map; the decisions are in `docs/adr/0041-bring-your-own-model-key.md`.

## The flag

`config/byok.yaml` key `enabled`, shipped `false`. While it is false:

- every `/v1/org/model-key` route (GET, PUT, PATCH, DELETE) answers 503 `not_configured` before it looks at the
  principal, the directory, the body or any store;
- `load_byok_config` returns the off config with no bundle, so no Router is given an `org=` binding;
- no code path reads a key, a secret name or a bundle, and `config/models*.yaml` and `config/prices.yaml` are
  unchanged (the shipped `bundles` is empty: the user chooses the models and their prices).

A missing, unreadable or malformed `config/byok.yaml` is the same off state (fail closed, the ADR failure table).
Only the user turns it on, after the credential-handling review, the answers to BQ-BYOK-1 to BQ-BYOK-3 and BQ-BYOK-7,
and a deployed connectors `generate` route (BYOK-4). `LIVE` is a separate switch and stays the user's.

## What is built (this stack)

| Piece | Where | ADR rules |
| --- | --- | --- |
| Org provider seam: `OrgProviderSource`, `OrgBinding`, `ProxyModelProvider`, fakes, config loader | `packages/providers/src/tilo_providers/byok.py` | BK-09, BK-10, BK-12, BK-13, BK-22 |
| `Router(org=)`: bundle candidates, `payer` on every attempt, `RouterCredentialError` (no fallback) | `packages/providers/src/tilo_providers/router.py` | BK-10, BK-14, BK-17 |
| Key reference, audit, act limiter, in-memory vault (the connectors double) | `services/api/src/tilo_api/byok_store.py` | BK-01 to BK-04, BK-08 |
| `GET/PUT/PATCH/DELETE /v1/org/model-key` | `services/api/src/tilo_api/byok_routes.py` | BK-02, BK-05 to BK-08, BK-16, BQ-BYOK-2 |
| `Principal.auth_time` (server-set, from the verified token) | `deps.py`, `firebase_auth.py` | BK-06 |
| `org_model_key_change: T3`, pinned | `config/autonomy.yaml` | BK-07 |
| Unit order and the org's own day cap: `plan_unit`, `ByokSpend` | `services/api/src/tilo_api/byok_unit.py` | BK-14 to BK-17, BQ-BYOK-3, BQ-BYOK-6 |

Variant L (the lease, a key in `tilo-api` memory) is NOT built: it needs the user's explicit yes (BQ-BYOK-7). There is
no `lease` route and no credential type in `tilo-api`; a test pins both.

Both "Google" modes of BQ-BYOK-2 are modelled: `google_api_key` (the org's Gemini API key, a vaulted secret) and
`google_vertex_iam` (the org's own Vertex project by an IAM grant: the body carries a `project_id` and never a key).
A service-account JSON key is refused by the key charset check. The Google adapter side, which runs in connectors, is
BYOK-4/BYOK-6.

## Fail-closed rules of the unit order (SEC-REVIEW-29)

- The org's day cap has no zero-cost loophole: a unit holds at least one credit (a zero, negative or non-finite estimate
  holds the minimum), and `ByokSpend.reserve` refuses a hold under one credit or one that does not fit, so a day that
  has reached its cap refuses every unit at its start and parallel units cannot all pass (BK-16).
- A key whose bundle is no longer in `config/byok.yaml` (flag on) is step 4, `not_configured`: the unit is refused, or
  runs on Tilo's key only when the owner turned `fallback_to_tilo` on, with that reason. Which roles the vanished
  bundle covered is unknown, so every org-scope unit of that org is refused until the owner rotates to a bundle that
  exists or removes the key; personal-scope units stay on Tilo's key as always. `GET /v1/org/model-key` says
  `active: false` and `last_error: not_configured` to the owner and `active: false, label: null` to members.
- A `google_vertex_iam` bundle is refused on `PUT` (422 `key_refused`) until `byok_routes.VERTEX_GRANT_CHECKED` is
  turned on by the ticket that proves the project is the org's (BQ-BYOK-2, BYOK-4/6): an owner-typed project would be
  called with Tilo's own identity.
- A pause is accepted only from `active`; a resume restores only a key that was verified when paused.

## Not built (left, in order)

1. Contract changes below (architect), then `tilo_contracts` codegen.
2. BYOK-4: tilo-connectors `model-keys/put|remove|status|generate` routes, the Secret Manager adapter, the HTTP
   `ModelKeyVault` and `ModelCallTransport` in tilo-api, the IAM test, connectors scaled past one instance
   (CON-D9). New client library goes in `docs/licences.md`.
3. The Firestore `OrgKeyStore` and `ByokSpend` (transactions with the ledger row); today deployed = 503
   `not_configured`, never memory.
4. Wiring `plan_unit` into the live run paths (Director answer, intake screen, plan, runs). It waits for the SEC-16
   wiring of issue 935 on the same code; `deps.router_for_mode(mode, org=...)` is the additive seam. The uid
   lifetime cap must not turn an org-key unit into replay (BK-15), so the caller computes the unit's mode without it.
5. `LedgerEntry.payer` in `packages/metering`, MT-02 summing `payer: tilo` only, `trace.payer` on the event.
6. BYOK-3c members' banner and BYOK-5 owner form in `apps/web`; BYOK-7 the user's live acceptance with their own key.

## Needs a contract change (contracts/ is architect-only; nothing here edits it)

The code uses plain Python types where a schema should be; each is a seam, so the architect ticket replaces them.

1. `providers.schema.json` 1.4.0, `$defs.profile` (BK-12). Until then an org profile is "named by a bundle and by no
   role, with a fixed `base_url` and no `api_key_env`" (BQ-BYOK-8). Exact diff of lines 88 to 93 (`credential` is
   allowed on `openai_compat` and, for BQ-BYOK-2's Google modes, on `google`; never with `api_key_env`):

   ```diff
            "pattern": "^[A-Z][A-Z0-9_]{2,63}$",
            "not": { "pattern": "\n" }
   -        }
   +        },
   +        "credential": {
   +          "description": "ADR-0041 BK-12: \"org\" marks a profile that only an org's own key serves and that no Tilo role may name. Replaces api_key_env.",
   +          "const": "org"
   +        }
          },
   +      "allOf": [
   +        { "not": { "required": ["api_key_env", "credential"] } },
   +        { "if": { "required": ["credential"] },
   +          "then": { "properties": { "provider": { "enum": ["openai_compat", "google"] } } } }
   +      ],
          "if": { "properties": { "provider": { "const": "openai_compat" } } },
   ```
   plus, in `config.py`, the loader rules BK-12 (a Tilo role naming a `credential: org` profile, a bundle naming one
   without it, an unpriced one) replacing the interim "named by no role" check in `tilo_providers.byok`.

2. `event.schema.json`, `trace` event `data` (user's yes needed, as ADR-0022 did): optional `payer`, enum `tilo` |
   `org_key`, absent reads `tilo`. `RouterAttempt.payer` already carries it.
3. `byok.schema.json` (new): the shape of `config/byok.yaml` exactly as `load_byok_config` checks it: `version`,
   `example`, `enabled` (boolean, required), `day_cap_credits_max`, `calls_per_org_per_minute`, `consent_version`
   (positive integers), `bundles` of `{label, kind in [openai_compat, google_api_key, google_vertex_iam], roles:
   {role: {primary, fallback}}}`; closed, no key or secret name field.
4. `org_model_key.schema.json` (new): the reference (`KeyReference` fields: `bundle_id`, `auth_mode`, `project_id`,
   `status` in [unverified, active, paused, invalid], `secret_version`, `set_by`, `set_at`, `rotated_at`,
   `day_cap_credits`, `fallback_to_tilo`, `consent_version`, `refusals`, `last_error`, `last_used_at`, `rev`; no key
   character, length, hash or last four), the audit entry (`id`, `at`, `actor`, `action`, `bundle`, `version`,
   `outcome`, `authz`), and the route bodies `PutIn`/`PatchIn` and answers (closed; codes `owner_only`,
   `reauth_required`, `confirm_required`, `key_refused`, `invalid_body`, `rate_limited`, `not_configured`,
   `unavailable`). `auth_mode`, `project_id` and the PATCH route extend the ADR's field list (BQ-BYOK-8, BQ-BYOK-9).
5. `model_call_rpc.schema.json` (new, variant P): `generate` request `{org_id, slot, run_id, profile_id, request}` where
   `request` is a closed subset of `GenerateRequest` (prompt, system, max_output_tokens, tools, json_mode,
   response_schema, thinking_level; no media parts in v1), reply `{text, tool_calls, usage}`, its own body cap from
   the roles' `max_input_tokens`, and no key field in either direction (`ProxyModelProvider` already refuses a
   reply with any other field).
6. `meeting_host_rpc.schema.json` additive minor: `put {org_id, slot, mode, key?, project_id?}` ->
   `{secret_version, validated}`, `remove {org_id, slot, secret_version?}` -> `{removed}`, `status {org_id, slot}` ->
   `{state, secret_version}`; the `key` field of `put` is the one place a key crosses, marked `no-store`.

## Where the key can be

At rest only in Secret Manager `byok-<digest>-models`, held by connectors (BK-01). In transit only in the owner's
`PUT` body, handed to the vault and dropped; nothing in `tilo-api` stores, logs, echoes or returns it. At runtime it
never reaches `tilo-api`: connectors makes the call. The named tests: `BK_02`/`BK_04` (no key in any answer, reference,
audit entry or log), `BK_22` (a failing unit leaks no key characters; a reply with a key field is refused),
`BK_09` (no credential attribute exists on the proxy provider), `BK_12` (flag off = no behaviour change).
