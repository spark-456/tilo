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

1. The open contract items below (architect), then `tilo_contracts` codegen.
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

## Contract state (BYOK-6: the code follows #977, nothing is activated)

The contracts landed as an inert proposal (`contracts/byok.schema.json`, `org_model_key.schema.json`,
`model_call_rpc.schema.json`, `meeting_host_rpc.schema.json` 1.3.0, `providers.schema.json` 1.4.0 `credential: org`;
rules in `contracts/byok.rules.md`, BQ-BYOKC-1 to BQ-BYOKC-6). The code follows them:

- An openai_compat org profile has `credential: "org"`, a fixed `base_url` and no `api_key_env`; `config.py` refuses
  the three wrong shapes and a Tilo role that names it (BK-12), and a bundle names only such profiles. The interim
  "named by a bundle and by no role" marker (BQ-BYOK-8) remains only for the two Google kinds, which have no contract
  case (BQ-BYOK-RECON-2).
- Answers and audit entries are the schema's: `authz` is `{by: person, ref, at}`, `owner_view.consent_version` is the
  config's current one, no `auth_mode` or `project_id`, 403 is always `owner_only`, a PATCH carries `confirm` and
  `consent_version` together or neither. `ProxyModelProvider` sends no media part and relays only a
  `generate_answer`-shaped reply. Tests judge every body with the JSON Schema itself
  (`test_BYOK_6_reconcile_977.py`, `test_BYOK_6_reconcile_credential_org.py`).

Still needs a decision or a contract change (BQ-BYOK-RECON-1, BQ-BYOKC-3):

1. `org_model_key.schema.json` `owner_view.last_error` lacks `not_configured` (SEC-REVIEW-29 B4); a strict xfail pins it.
2. `event.schema.json` `trace.payer` (the user's yes, as ADR-0022 did): `RouterAttempt.payer` already carries it.
3. The Google modes (BQ-BYOK-2): an additive minor of `byok`, `org_model_key`, `meeting_host_rpc` and `providers`, or
   removal from the code.
## Where the key can be

At rest only in Secret Manager `byok-<digest>-models`, held by connectors (BK-01). In transit only in the owner's
`PUT` body, handed to the vault and dropped; nothing in `tilo-api` stores, logs, echoes or returns it. At runtime it
never reaches `tilo-api`: connectors makes the call. The named tests: `BK_02`/`BK_04` (no key in any answer, reference,
audit entry or log), `BK_22` (a failing unit leaks no key characters; a reply with a key field is refused),
`BK_09` (no credential attribute exists on the proxy provider), `BK_12` (flag off = no behaviour change).
