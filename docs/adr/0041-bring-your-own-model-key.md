# ADR-0041: Bring your own model key: an org's own API key on the Tilo harness

- Status: **Proposed** (13 Oct 2026). Nothing is built and nothing is approved. Before any ticket starts it needs the
  user's answers to BQ-BYOK-1 to BQ-BYOK-3 and a security review of decisions 2, 3, 4, 6 and 9. It changes no
  frozen contract by itself: decision 12 lists the additive bumps for a later contract ticket, and
  `event.schema.json` (frozen at CP0) needs the user's yes first, as ADR-0022 did. The merger may renumber
  (ADR-0040 is team-shared worlds, PR #899).
- Deciders: user (BQ-BYOK-1 to BQ-BYOK-3, the contract bumps), architect (proposal), security-reviewer (the review above)
- Requirement: GitHub issue 934; PL-01 to PL-03, PL-05 to PL-07, NFR-25; EFF-01, EFF-03; SEC-01 to SEC-04, SEC-10,
  SEC-11; FR-MTR-02, FR-MTR-04, FR-MTR-08; PRD 6.4, 6.6, 10.1, 10.4, 14.1, 16.1, 16.3, 16.5; PE-01, PE-05, PE-17;
  ADR-0026, ADR-0032, ADR-0035, ADR-0039
- Questions: new BQ-BYOK-1 to BQ-BYOK-6 (listed after the decisions). New rule ids BK-01 to BK-20 (no other prefix
  in the repo uses `BK-`).

## Context
1. **The key is Tilo's today.** The `google` adapter calls with the runtime identity's ADC. The generic
   `openai_compat` adapter reads one key from the process environment, named by the profile's `api_key_env`
   (`providers.schema.json` 1.3.0, PL-02). `deps.router_for_mode(mode)` builds a Router from the request's mode
   alone; no org, person or credential reaches `packages/providers`. The org is the constant `deps.ORG_ID` until
   multi-org sign-in exists.
2. **Every spend control assumes Tilo pays.** SEC-16 (`tilo_api.spend`, `config/spend_caps.yaml`) caps a uid's
   lifetime, a run and the deployment's UTC day in INR minor units, and its `global_day_hard_minor` flips
   replay-only for everyone (NFR-24). The Treasury caps credits per run, user and org and USD per day
   (`config/metering.yaml`, FR-MTR-04); reconciliation compares the ledger with Tilo's billing export (MT-02). The
   Cloud Build gate (`docs/cloud-test-gate.md`) and the live reserve bound Tilo's own build and test spend.
3. **Credential rules already in force.** PRD 16.1: no password fields; secrets never in prompts, logs, traces,
   the raw archive or analytics; platform secrets in Secret Manager. SEC-02 and ADR-0032: `tilo-connectors` is
   the only holder of third-party credentials and `tilo-api` reaches it over the HB-01 OIDC RPC. ADR-0035:
   `tilo-api` holds no secret, KMS or token-store access. ADR-0039: a settings write never takes an owner or org
   from the request.
4. **The ask (issue 934, user, 13 Oct 2026).** Let companies use their own API keys on the Tilo harness "to bring
   out their best models and complete their tasks". The PRD is silent; models are configuration (PL-01) and the key
   is Tilo's. Applying the rules: ADR first, security review before any build, no invented requirement.
5. **The calendar.** The demo is frozen after 15 Oct and the submission is 17 Oct. This feature moves customer
   prompts to a third party and adds a secret class, so it is not a late hotfix (BQ-BYOK-1).

## Decision
1. **What BYOK is.** It changes *whose credential and whose meter* a live model call uses, and nothing else. It
   adds no tool, tier, recipient, route or capability to work. PL-01, the policy engine, the outbox, safety
   screening and the honesty rules (PRD 9.4) are unchanged. It is org-level (one decision by the org owner), one
   slot `models`, one active key. It is **not** a login password (16.1 rule 1 stands), not an OAuth connection,
   not a per-person key, and not an endpoint the customer runs (BQ-BYOK-5).
2. **Where the key lives (BK-01 to BK-04).**

   | Where | Holds |
   | --- | --- |
   | Secret Manager, `byok-<digest>-models`, in `tilo-connectors`' project | the key; one version per rotation; label `org=<digest>` |
   | Firestore `orgs/{org}/model_keys/models` (tilo-api, ADR-0026's door) | the reference and the org's choices: `bundle_id`, `status`, `secret_version` (an integer), `set_by`, `set_at`, `rotated_at`, `day_cap_credits`, `fallback_to_tilo`, `refusals`, `last_error` (fixed code), `last_used_at`, `consent_version`, `rev` |
   | Firestore `orgs/{org}/byok_spend/{utc day}` | that day's reserved and committed credits (decision 6) |
   | Firestore `orgs/{org}/byok_audit/{id}` | one entry per act: id, time, actor user id, action, bundle, version, outcome code, `authz` |

   - **BK-01. One holder.** Only `tilo-connectors` has any Secret Manager role on `byok-*` (create, add version,
     access, disable, destroy), as SEC-02 gives it the only decrypt. `tilo-api`, the harness and every other
     identity have none; the IAM test pins it (decision 12).
   - **BK-02. No key anywhere else.** Never in Firestore, an env var, config, a fixture, a recording, an event, a
     Trace row, the raw archive, analytics, a log line, an error string, a URL, a Cloud Build substitution, the
     repo, or browser storage after the form is submitted. The web clears the field on submit and keeps it in no
     storage.
   - **BK-03. Names.** `<digest>` is the first 24 hex digits of `sha256("tilo/byok/" + org_id)`, so a secret name
     is a valid id and never discloses the org id.
   - **BK-04. The reference holds no key characters.** No length, hash or last four. A person tells keys apart by
     `set_at`, `rotated_at` and `secret_version`.

   The reach is four routes on the existing tilo-api to connectors RPC (additive minor on
   `meeting_host_rpc.schema.json`, as ADR-0035 decision 1 did; HB-01 caller check, closed schemas, fixed error codes):

   | tilo-api (public, signed in) | tilo-connectors (internal) | Request | Answer |
   | --- | --- | --- | --- |
   | `PUT /v1/org/model-key` | `/internal/model-keys/put` | `{org_id, slot, key}` | `{secret_version, validated}` |
   | (the run, once per unit, decision 4) | `/internal/model-keys/lease` | `{org_id, slot, run_id}` | `{key}` or a fixed code |
   | `DELETE /v1/org/model-key` | `/internal/model-keys/remove` | `{org_id, slot}` | `{removed}` |
   | `GET /v1/org/model-key` | `/internal/model-keys/status` | `{org_id, slot}` | `{state, secret_version}` |

   `put` validates the key with the provider's free list-models call, never a paid one (only when the process may
   go live, EFF-01; otherwise `validated: false` and the status is `unverified`, which no run can use). `put` and
   `lease` are the only places on the RPC surface that carry the key; the schema marks both, they are `no-store`,
   and neither side logs, wraps or re-raises a body that contains it (as ADR-0032's join-link is the one place a
   Meet link crosses).
3. **Who may set, rotate and remove it (BK-05 to BK-08).**
   - **BK-05. The org owner only.** The directory record's `org_role` is `owner` (PE-17), on a full Google session
     over web or mobile web. `Principal.role` is `owner` for *every* signed-in person (each owns their own worlds),
     so it must never be the check: the route reads the directory record. Refused: a member, an Approver, a Team
     Lead, a demo session (403), an email link, a channel reply, a schedule tick, the assistant, the Director, an
     agent, a `ui_action`, a skill or an MCP tool (ADR-0031). None of those has a code path to these routes.
   - **BK-06. A fresh, explicit act.** `Principal` gains a server-set `auth_time` from the verified token
     (`firebase_auth` already validates the claim); a write older than 10 minutes is 401 `reauth_required`. The body carries
     `confirm: true` and the `consent_version` of the line the person saw, else 422 `confirm_required`. The web
     shows the consent line from config before the field: this org's prompts, documents and answers will be sent
     to the named provider under that provider's terms, may be processed outside `asia-southeast1` (PRD 16.5), the
     provider's own logs may show them to that account's administrators, Tilo's caps do not apply to this spend, and
     the org carries the provider's bill.
   - **BK-07. Widening is T3, narrowing is immediate.** The policy engine decides (a model never does); T3 always
     needs a person; `config/autonomy.yaml` lists one action, `org_model_key_change`, at T3, pinned by a config
     test so deleting the line cannot pass unnoticed (as `build_handoff` is).

     | Act | Person-act, T3 | Why |
     | --- | --- | --- |
     | Set or rotate the key; choose or change the bundle | yes | sends the org's data somewhere new |
     | Turn `fallback_to_tilo` on | yes | lets work reach Tilo's allowance |
     | Raise `day_cap_credits` | yes | widens what can be spent |
     | Lower the cap; pause BYOK; remove the key; turn fallback off | no, owner, at once | narrowing; a revocation must never be harder than a grant |
   - **BK-08. The org comes from the principal.** `org_id` is the verified principal's directory org (today
     `deps.ORG_ID`), never a body, path or query value (ADR-0039). A closed JSON body; JSON only (415). At most 5
     key acts per org per hour (429 `Retry-After`).
4. **How `packages/providers` resolves a credential per org, with no model id outside config (BK-09 to BK-12).**
   - **BK-09. A credential is an opaque value.** `tilo_providers.Credential` redacts its `repr` and `str`, refuses
     to pickle or JSON-encode, and exposes `reveal()` only to an adapter. `CredentialSource` is a Protocol,
     `lease(org_id, slot, run_id) -> Credential`, raising a fixed `CredentialRefused(code)`. A
     `FakeCredentialSource` ships in `packages/providers` for tests and dev. The production source,
     `ConnectorsCredentialSource` (the RPC client), lives in `services/api` beside `ConnectorRpcStub`; the harness
     has none and builds no BYOK Router.
   - **BK-10. One injected path.** `Router(..., credentials=, org_id=)`. For a role the leased bundle covers,
     `_candidates` lists the bundle's profiles instead of the role's own, and `build_provider(..., credential=)`
     passes the value to `OpenAICompatModelProvider`, which takes `credential=` *or* `api_key_env`, never both and
     never the environment for an org. Its clean-token check and `redact()` apply to it unchanged. `Router._candidate`
     stays the one choke point (no new one).
   - **BK-11. A lease lasts one unit.** The run leases at each unit start, holds the value in that unit's Router
     only, never caches it across units, and drops it at the unit's end. A removal or rotation therefore takes
     effect at the next unit boundary; an HTTP call already in flight may complete (the settings copy tells the
     owner to revoke at the provider as well).
   - **BK-12. Profiles are config, and org-only.** A BYOK profile is an ordinary entry in `config/models*.yaml`
     (a fixed `base_url`, a model id, caps, a price row) with `credential: org` in place of `api_key_env`
     (`providers.schema.json` 1.4.0). The loader refuses a Tilo role that names one, a bundle that names a profile
     without `credential: org`, and an unpriced one (PL-06: no invented price, so no metering, so no call). A
     profile used in a bundle needs a PL-05 conformance result; the user produces it with their own test key,
     live, outside CI. `lint_model_ids.py` is unchanged: ids appear only in `config/` and `packages/providers`.
5. **Which provider and model: an allow-list in config (BK-13).** The owner picks a **bundle** by id from
   `config/byok.yaml` (new shape, `example: true`, the user chooses final models); the web shows its `label`. The
   owner never types a model id, a role or a URL.

   ```yaml
   example: true
   enabled: false                 # master switch; BYOK is closed while false
   day_cap_credits_max: 10000     # the most an org may set (credits; 1 credit = US$0.005); BQ-BYOK-4
   consent_version: 1
   bundles:
     openai-compat-example:
       label: "OpenAI-compatible endpoint (example)"
       kind: openai_compat
       roles:                     # role -> profiles in config/models.yaml with `credential: org`
         director: { primary: byok-oa-large, fallback: byok-oa-small }
         writer: { primary: byok-oa-large, fallback: byok-oa-small }
   ```

   - **BK-13.** A bundle may name only roles that generate or verify work. It never names `safety`, `search` or
     `speech`, and its fallbacks are its own profiles (NFR-25 holds inside the bundle; a Tilo profile is never in
     a BYOK cascade). Every role a bundle leaves out, and every embedding call, stays on Tilo's profile and Tilo's
     meter. The first slice supports `kind: openai_compat` only: the `google` adapter is Vertex on ADC and takes no
     key, and a service-account JSON key is refused always (BQ-BYOK-2).
6. **Metering and caps (BK-14 to BK-16).**
   - **BK-14. Spend is tagged.** Every ledger row and `trace` gets `payer`: `tilo` (the default; absent reads as
     `tilo`) or `org_key`. An org-key unit's credits are the provider-reported tokens at list price from
     `config/prices.yaml`: an estimate, labelled so, because the provider's bill governs.
   - **BK-15. What counts against what.**

     | Control | Tilo-key unit | Org-key unit |
     | --- | --- | --- |
     | SEC-16 INR ledger (uid lifetime, `run_minor`, `org_day_minor`, `global_day_hard_minor`) | counts | not touched |
     | `caps.user_day_credits`, `caps.org_day_credits`, `spend.daily_usd_soft` and `_hard` | counts | not counted |
     | MT-02 reconciliation against Tilo's billing export | included | excluded |
     | The run budget the person approved (MT-03) and `caps.run_credits`; EFF-03 token caps | applies | applies |
     | `replay_only` (NFR-24), `LIVE`/`TILO_JUDGE_LIVE`, the visitor/judge declaration (SEC-15), demo sessions | applies | applies |
     | The org's own day cap, below | not applicable | counts |
     | Cloud Build gate and live reserve (`docs/cloud-test-gate.md`) | n/a | n/a: a test never holds a customer key |

     So an org-key unit never consumes a Tilo cap and never trips the deployment's replay-only switch. That one
     shared switch (the operator's incident switch, also set by the daily hard cap on Tilo-key spend) still stops
     both payers (BQ-BYOK-6). BYOK opens no new way to go live: a unit is live only where it already would be.
   - **BK-16. The org's cap.** `day_cap_credits` is an integer from 1 to `day_cap_credits_max`, set by the owner
     and required before BYOK can be enabled (never null: the issue asks for a cap the org sets). A day is the UTC
     day (BQ-44). Units reserve estimate plus 15% and commit actuals (MT-03) against
     `orgs/{org}/byok_spend/{day}` in one transaction with the ledger row. At the cap a unit is refused at its
     start with 403 `byok_cap_reached`: no call is made and Tilo's key is not tried (decision 7).
     Tilo-paid ancillary calls inside a BYOK run (safety screening, search, speech, embeddings) stay
     `payer: tilo` and are unchanged. A per-member share of the cap is a follow-up.
7. **Fail closed (BK-17).** The order for a model unit, in code, never a model:

   | Step | Test | Result |
   | --- | --- | --- |
   | 1 | demo session, or `mode != live` (switch set, not permitted) | replay, as today |
   | 2 | no active key and bundle for the unit's org, or the unit is personal-scope (decision 10) | Tilo's key under SEC-16, as today |
   | 3 | key active, role covered, cap not reached, lease granted | org key; `payer: org_key`; SEC-16 not consulted |
   | 4 | key `invalid`, `removed`, `unverified`, `paused`, lease refused or unreachable, cap reached | **refused**: the unit blocks with a fixed reason (PRD 10.2 Blocked; no new event type); no call, no fallback |
   | 5 | step 4 and `fallback_to_tilo` is on | Tilo's key under SEC-16, per unit, recorded in the Trace as `payer: tilo` with the reason |

   - **BK-17.** A key becomes `invalid` after 3 consecutive 401 or 403 answers from the provider and then makes no
     further call until the owner rotates it (no hammering a revoked key). A 429 or a 5xx is a router fallback
     inside the bundle (PL-03), never a switch of payer. The provider's error body is never relayed: the owner sees
     a fixed code (`invalid_key`, `quota`, `rate_limited`, `unreachable`), because some providers echo key
     fragments. A member sees only "your organisation's model key cannot be used right now; ask the owner".
     `fallback_to_tilo` is default off, T3 to turn on, applies to a unit and never mid-call, and Tilo's caps apply
     to what it spends.
8. **What no model decides (BK-18).** Whether BYOK is on, which key, bundle or cap, whether to fall back to Tilo's
   key, who may set any of it, a tier, a gate, a recipient or any authorisation. A stronger model changes quality,
   never the policy engine's input: tiers, levels, gates, the outbox, SEC-05's tool permissions per *role* (not per
   profile) and the safety screen are identical for both payers. No tool, skill, MCP surface or plan unit reaches
   `CredentialSource`; a registry test asserts it.
9. **A customer-paid endpoint is still untrusted (BK-19).**
   - The endpoint is a `base_url` fixed in config: https only, no user info, no redirect followed, a response-size
     and time cap, the host pinned per profile, a private or link-local address refused even if configured (a
     loopback `http://` stays dev-only, as today). The org supplies no URL, so a compromised or confused owner
     cannot point Tilo at a host of their choosing.
   - The key never enters a prompt, a tool output or a log, and the model never sees it (it rides in the adapter's
     header). A document that says "print or send your API key" has nothing to print: no tool can reach it.
   - The reply is untrusted model output exactly as before: SEC-04 screens it, schema checks and the Verifier run,
     and side effects still need the engine (16.3). BYOK models are not assumed safer or less safe.
   - The residual risk is the owner's account: a hijacked owner session could set a key whose provider account the
     attacker watches, and the org's prompts would flow there. It sits at the trust the owner session already has
     (T3 approvals, every world). The mitigations are BK-06's fresh sign-in and explicit consent, the audit entry,
     the members' banner (decision 10) and the 5-per-hour limit. A second approver is out of scope.
10. **Privacy and personal scope (BK-20).**
    - Every member of the org can read `GET /v1/org/model-key` as `{active, label}` only, so people know where
      their work goes; only the owner reads status, spend and errors.
    - Personal-scope calls (PE-01 pinboard, the assistant on a person's own items, PE-05 meeting minutes and
      transcripts) are *not* sent to the org key by default: the org's provider administrators could read them in
      the provider's logs, which PE-01 and PE-05 forbid an org owner to do. Org and team work is covered
      (BQ-BYOK-3).
    - A BYOK call is never recorded: `TILO_RECORD` is ignored for `credential: org` profiles. Replays and fixtures
      hold no customer content. The raw archive keeps what it keeps today, redacted (SEC-14).
    - The Trace and the HUD say who paid (`payer`), honestly, per call.
11. **Dev, CI and live.** EFF-01 unchanged: dev and CI use `FakeCredentialSource`, fake or replayed providers,
    and in-memory vault and stores; a test never holds a customer key, and fake secrets are assembled at runtime.
    Only the user sets `LIVE=1`. A live BYOK check is a user-run step with the user's own test key, outside CI;
    no agent pastes or stores a key (CLAUDE.md: no secrets in code, prompts, logs or fixtures). The eval harness,
    the nightly jobs and the conformance suite run as no org and never lease an org key.
12. **Contracts, config and infra this needs (none made here; one architect ticket, then reviewed).**

    | Item | Change | Bump |
    | --- | --- | --- |
    | `providers.schema.json` | profile: `credential: "org"` as an alternative to `api_key_env`, openai_compat only | 1.4.0 |
    | `byok.schema.json` (new) and `config/byok.yaml` | bundles, ceiling, `consent_version`, loader rules BK-12, BK-13 | 1.0.0 |
    | `org_model_key.schema.json` (new) | the reference record, the audit entry, the four RPC bodies, the route bodies, rules BK-01 to BK-20 | 1.0.0 |
    | `meeting_host_rpc.schema.json` | the four routes of decision 2 | minor |
    | `event.schema.json` | `trace.payer` optional (`tilo` or `org_key`); absent means `tilo` | 1.x minor, **user's yes** |
    | `metering.rules.md` | MT rules: BK-15 exclusions; MT-02 sums `payer: tilo` only (`LedgerEntry.payer` is builder code in `packages/metering`) | rules |
    | `config/autonomy.yaml` | `org_model_key_change: T3`, pinned by a config test | data |
    | `config/models*.yaml`, `prices.yaml` | BYOK example profiles and price rows (no id outside config) | data |
    | `infra/` | `tilo-connectors`: Secret Manager roles on `byok-*` only; `security_iam.tftest.hcl`: no other identity; ACCESS.md | user applies |

13. **The slice buildable in two days (proves the rules; not live).**

    | Ticket | Who | Size | Done when |
    | --- | --- | --- | --- |
    | BYOK-1 contracts and config (decision 12) | architect | S | schemas, fixtures and codegen green; `just contracts-check` clean |
    | BYOK-2 providers (BK-09 to BK-13) | intelligence-builder | M | fake-transport tests: per-org candidates, no env read for an org, the key absent from `repr`, errors, recordings and logs |
    | BYOK-3a api store and routes (BK-05 to BK-08) | reach-builder | M | owner-only, fresh sign-in, T3 pin, no key in any answer; in-memory vault |
    | BYOK-3b unit order and metering (BK-14 to BK-17) | reach-builder | M | the table of decision 7 and BK-15 as tests; cap refusal; a revoked key blocks and never falls back |

    After the slice, separate tickets: BYOK-4 connectors routes and the Secret Manager adapter with its IAM test
    (reach-builder, then the user applies; a new Secret Manager client library goes in `docs/licences.md`); BYOK-5 the
    Settings section in `apps/web` (world-builder, security review of the form); BYOK-6 the Google variant
    (BQ-BYOK-2); BYOK-7 the user's live acceptance.

## Open questions (BQ-BYOK-1 to BQ-BYOK-6, also in `docs/open-questions.md`)
| ID | Question | Default until answered |
| --- | --- | --- |
| BQ-BYOK-1 | Build before or after the 17 Oct submission? | After. The ADR and its review now; BYOK-1 to BYOK-3 after the first live run is verified; BYOK-4 to BYOK-7 only when the user applies the IAM. The demo is frozen after 15 Oct and this adds a secret class and a third-party data flow. |
| BQ-BYOK-2 | Which "Google"? (a) the org's Gemini API key, a secret in the vault with a new adapter auth mode; or (b) the org's own Vertex project through an IAM grant to Tilo's service account (no secret; the org's project is billed; an org-side admin step and a cross-project permission). | `openai_compat` first (BYOK-1 to BYOK-5). Google as (a) in BYOK-6 unless the user prefers (b). A service-account JSON key is never accepted. |
| BQ-BYOK-3 | May personal-scope calls (PE-01 pinboard, the assistant on a person's own items, PE-05 meeting minutes) use the org key? The org's provider administrators could read them in the provider's logs. | No. Org and team work only (BK-20); including them needs a stronger consent line and the user's say. |
| BQ-BYOK-4 | What is `day_cap_credits_max`, the most an org may set? | 10,000 credits (about US$50 a day) as an example in `config/byok.yaml`; the user sets the number. |
| BQ-BYOK-5 | Custom endpoints (a self-hosted gateway, a per-tenant URL)? | Out of v1. Later only as an operator-approved entry in config with a private-address block, never an owner-typed URL. |
| BQ-BYOK-6 | Should the automatic replay-only trip from Tilo-key spend (the daily hard cap) also stop org-key units? | Yes: one shared switch, as today. The operator's manual switch must stop everything; exempting org-key units from the automatic trip only would need the flag store to tell the two apart. |

## Failure modes
| Condition | Result |
| --- | --- |
| Not the org owner, or a demo session | 403 `owner_only`; nothing written |
| Sign-in older than 10 minutes | 401 `reauth_required`; nothing written |
| No `confirm`, or a stale `consent_version` | 422 `confirm_required` |
| Provider refuses the key at `put` | 422 `key_refused`; no secret version kept, the old key stays active |
| Connectors or Secret Manager unreachable at `put` or `lease` | 503 `unavailable`; a unit blocks (step 4), never falls back unless opted in |
| Key invalid, removed, paused, unverified | units blocked with a fixed reason; the owner's status says why |
| Day cap reached | 403 `byok_cap_reached` at unit start; nothing sent |
| Profile unpriced | unit blocked (PL-06); no call |
| `config/byok.yaml` missing or `enabled: false` | every route 503 `not_configured`; nothing is Tilo-keyed by accident |
| Removal during a run | next unit refused; an in-flight call may finish |
| Process restarts | no key in memory; the next unit leases again |

## What the user decides and does
- BQ-BYOK-1 to BQ-BYOK-3 (above), the `event.schema.json` additive minor and the ceiling in BQ-BYOK-4.
- Chooses the bundles' final models and their price rows, and produces PL-05 conformance with their own test key.
- Applies the connectors IAM roles. Sets `LIVE=1` when they choose. Enters no key into chat or a file.

## Consequences
- An org pays for its own models and gets better ones without changing a single policy, tier or gate.
- No Tilo cap or kill switch is weakened for Tilo's own spend, and none can be tripped by an org's spend.
- Cost: four connectors routes, one providers seam, one config file, Secret Manager roles for connectors, and a
  consent line the web must show. The key crosses into `tilo-api` memory for one unit at a time; the proxy
  alternative below removes that.
- `tilo-api` stays free of Secret Manager roles; ACCESS.md's "no secret in tilo-api" holds at rest.

## Alternatives not chosen
- **Connectors makes the model call (a proxy).** The key never leaves connectors, which is stronger. Not chosen for
  now: HB-01's 64 KiB closed-schema routes cannot carry prompts, a second Router would duplicate budgets, cascades
  and recordings, and streaming would be lost. The `Credential`/`CredentialSource` seam is the same, so the
  security review may swap the source without touching the rest.
- **`tilo-api` reads and writes Secret Manager itself.** One hop fewer, but it gives the public service secret
  roles, and creating a secret is a project-level permission, so the role would be broad. Rejected for BK-01.
- **A Firestore field under KMS (as OAuth tokens).** Issue 934 and PRD 16.1 rule 5 say Secret Manager; the token
  store is OAuth-specific and its decryptor is connectors.
- **An org-supplied base URL.** Self-service SSRF and exfiltration; deferred (BQ-BYOK-5).
- **Per-person keys.** A different privacy and billing model; not asked for.
