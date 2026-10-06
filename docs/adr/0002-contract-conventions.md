# ADR-0002: Contract conventions, fixtures and code generation

- Status: Accepted (2026-09-25, architect; ticket P0-02). Amended 2026-09-25 by ticket P0-03
  (decisions 1, 8 and 10), by ticket CC-SH (decision 12), by ticket CC-SE (decision 13) and by ticket CC-SP-64
  (decision 14, 2026-10-02). The contract set freezes at CP0 on 29 Sep; `manifest.schema.json` freezes on 1 Oct.
- Deciders: architect, orchestrator
- Requirement: FR-WLD-02 (PRD 15.2); FR-WLD-03 for the P0-03 amendment; FR-INT-08 for decision 14

## Context
PRD 15.2 makes versioned JSON Schemas in `contracts/` the single source of truth for every
structure crossing a service boundary, with Python and TypeScript types generated from them and
CI failing on drift. Ticket P0-02 delivers the CP0 set except the event contract (P0-03):
common, brief, plan, layout, card, policy, handoff, envelope, skill, connector and providers.
The PRD fixes the fields but not the file conventions, and it is silent or cut off in a few
places (BQ-01, BQ-02 and the gaps listed under decision 9).

## Decision
1. **Files and ids.** One file per contract, directly in `contracts/` (PRD 15.2 lists bare file
   names; `contracts/schemas/` is not used). Draft 2020-12, `$id`
   `https://contracts.tilo.example/<name>.schema.json` on a reserved, non-resolving domain, so
   `$id`s are names and never fetched; `title` is the PascalCase name. Cross-file `$ref`s are
   relative (`common.schema.json#/$defs/timestamp`) and resolve by `$id` through a registry.
   The event contract (P0-03) adds the only nested files PRD 15.2 names: `events/registry.schema.json`
   and `events/data/<type>.schema.json`. Their `$id` follows the path
   (`https://contracts.tilo.example/events/data/building.completed.schema.json`), their `title`
   is the generated name (`EventRegistry`, `BuildingCompletedData`) and their refs are relative
   to that path (`../../common.schema.json#/$defs/ulid`).
2. **Versioning.** A top-level `"x-version"` semantic version per schema, 1.0.0 at CP0.
   Additive change is minor; breaking change is major plus a migration, an ADR and the user's
   approval once frozen. The generated files list each schema's version and content hash.
3. **Shared shapes** live in `common.schema.json` `$defs`: prefixed ids (`w_` world, `r_` run,
   `u_` user, `org_`, `A_` agent, `pol_` policy, `tl_` Team Lead, `art_` artifact; `D`, `L`,
   `B`, `U`, `G`, `I` plus digits for district, level, building, plan unit, gate and island),
   upper-case ULIDs, timestamps in RFC 3339 UTC with exactly three fractional digits, calendar
   dates, credits (number >= 0), severity, risk tier T1-T3, autonomy level L0-L3, tier, channel,
   data class and the rest. Its root is a sampler with one optional property per definition so
   that fixtures and generated types cover every definition; nothing sends a `Common` document.
4. **authz (BQ-01).** `{by: "person" | "policy" | "team_lead", ref: string, at: timestamp}`, all
   required, from PRD 10.4 "Audit" and the glossary. `ref` is the id of the authority and the
   schema binds it to `by`: a `u_` user id for a person, a `pol_` policy id for a policy, a `tl_`
   Team Lead id for a Team Lead. There is no value for a model: a model never authorises.
5. **Strictness.** `additionalProperties: false` everywhere except explicitly open shapes
   (a skill's embedded input and output schemas). Enums are closed. Rules one document can
   express use `if`/`then`/`else` and `contains` (a gate card's safe default is `hold`, a T3
   gate has no policy, deletes are T3, exactly one suggested option, only a gate offers an
   irreversible option). Rules that compare values or span documents or need config (every
   irreversible action has a gate, roads equal dependencies, a card's safe default names one of
   its options) are numbered in `contracts/plan.rules.md` (PG-01..), `contracts/layout.rules.md`
   (WE-01..) and `contracts/card.rules.md` (CR-01..) for the deterministic validators; each file
   marks which rules the schema already enforces.
6. **One named type per document.** Every object shape is a named `$defs` entry, and the card
   and providers roots are single objects rather than unions, so both generators emit one type
   with the contract's name: a card carries nullable `gate` and `consent` detail objects whose
   presence follows `kind`; `Providers` is `{models, prices}`, the two config files as the
   provider layer loads them.
7. **Fixtures.** `contracts/fixtures/<name>/valid|invalid/*.json` for each schema root and
   `contracts/fixtures/<name>.<def>/` for a `$defs` entry used on its own (the risk-tier table).
   At least one valid fixture and one invalid fixture per rule that matters; an invalid file's
   name says which rule it breaks. No secrets, real people or real model ids: example.com and
   example.org addresses, fake provider profiles.
8. **Code generation.** `scripts/contracts_codegen.py` bundles the schemas into one document
   whose `$defs` names cannot collide (common definitions keep their name, such as `RiskTier`;
   other definitions get their contract as prefix, such as `PlanGate`; each root takes the
   contract name, such as `Plan`). datamodel-code-generator writes pydantic v2 models to
   `packages/contracts-py/src/tilo_contracts/__init__.py` (Literal enums, type aliases instead of
   root models); json-schema-to-typescript writes `packages/contracts-ts/src/index.ts`. Generated
   files are committed, marked `linguist-generated`, excluded from ruff and Biome, and checked by
   mypy and tsc. `just contracts-gen` writes them; `just contracts-check` validates every schema
   and fixture, round-trips every valid fixture through the generated models, regenerates in
   memory and fails on any byte difference. `just check` runs it first, so CI fails on drift.
   If json-schema-to-typescript is not installed (a fresh copy of the repo) the check runs
   `pnpm install --frozen-lockfile --offline`, which cannot change the lockfile.
   Since P0-03 the generator reads every `contracts/**/*.schema.json` and
   `contracts/events/registry.yaml`, appends the registry constants to both packages
   (`EVENT_TYPES`, `SIDE_EFFECT_EVENT_TYPES`, `EVENT_DATA_MODELS`, `EVENT_REGISTRY`; in TypeScript
   also `EventDataByType` and `RegisteredEvent`, a union discriminated on `type`), and checks
   the registry, the event fixtures and the fixture streams against rules EV-01 to EV-14
   (`scripts/contracts_events.py`, `contracts/event.rules.md`). Conditionals stay in one root
   `if`/`then`/`else`, because json-schema-to-typescript turns a root `allOf` into an open
   intersection type.
9. **Defaults where the PRD is silent** (logged in `docs/open-questions.md`):
   - brief `sensitivity` uses the PRD 12.1 data classes `personal | business | public` (BQ-12);
   - connector `gate_type` is `none` (no side effect) or `approval` (a person, or a matching
     policy below T3, opens it), and write, send, share and delete actions must be `approval`;
     a `none` action is T1 or T2 and reversible, so a T3 or irreversible action is always gated
     and reaches a person (BQ-13);
   - policy `limits.credits` caps credits per day spent under the policy (BQ-14);
   - policy `conditions` are each fixed `true`, and the risk-tier table must list all six PRD
     10.4 T3 modifiers exactly once, so neither a policy nor `config/autonomy.yaml` can drop new
     recipients, attachments, external sharing, deletion, money or legal terms, or
     injection-flagged content below T3 (BQ-16);
   - only a gate card offers an irreversible option; every card's safe default names one of its
     options and is reversible, because it applies at timeout with no person (card rules CR-01 to
     CR-05, BQ-15);
   - card answer channels per kind: email answers questions (needs-you) only; gates and
     meetings are answered on web, mobile web or WhatsApp; consent only on the web; gates have
     no "Delegate to Director" action because a model never authorises, and neither do consent
     cards, since granting a connection is also an authorisation. A consent card, like a gate,
     offers a `hold` option and defaults to `hold` ("That connection waits", PRD 10.2), so a
     timeout never grants a connection; every `hold` option is reversible (BQ-15);
   - a gate card's buttons have fixed labels (Approve, Edit first, Hold), because the person's
     tap on a label is the authorisation. The deterministic card builder writes the gate details
     from the plan gate, the connector action and the held outbox entry, never a model, and the
     card validator rejects a gate id, action type, irreversible flag, risk tier or recipient
     list that does not match them (CR-07, CR-09 to CR-12, BQ-17);
   - WorldLayout geometry is integer grid units: level plates, district plots with tints
     `district.1`-`district.6`, building footprints, island plots, roads as building-to-building
     edges with paths, bridges and gate cells, stamped with the solver version;
   - `config/models.yaml` copies the PRD 6.4 example profiles with `example: true`; a profile
     has no cost field, because PRD 6.6's cost ranking is derived from `config/prices.yaml`
     (one source of truth). `config/prices.yaml` has `status: unset` and null prices until the
     user sets them; `just contracts-check` validates both files;
   - a card holds the request, not its answer: the answer and who gave it are recorded by the
     answering event (P0-03) and as a Decision (PRD 15.1, CARD records DECISION). A gate card
     always offers an option with id `hold`, so its safe default resolves;
   - a layout gate's `between` is the pair `[building id, island id]` in that order.
10. **providers 1.1.0 (additive, 2026-09-25, ticket P0-02b, PL-02, BQ-33).** `$defs.profile` gains
    two optional fields for the generic OpenAI-compatible adapter (ADR-0003 decision 2):
    `base_url` (https only, with no user info, query or fragment, so a credential cannot sit in
    the URL, PRD 16.1 rule 4; `format: uri`, at most 512 characters) and `api_key_env` (the
    name of an environment variable, `^[A-Z][A-Z0-9_]{2,63}$`, never the key). An `if`/`else`
    allows them only when `provider` is `openai_compat`; other profiles, `google` included,
    must not carry them. Both are optional and independent. `format: uri` is documentation;
    the pattern is what validators enforce. Each field also has `not: {pattern: "\n"}`,
    because a Python JSON Schema validator's `$` matches before a final line break. The Python generator maps `string` + `uri` to `str`
    (`--type-mappings`), so the generated field keeps its pattern and length instead of
    becoming pydantic `AnyUrl`, which would drop both.
11. **The outbox is a contract (P0-03).** PRD 15 says every structure that crosses a service
    boundary is a contract, and an outbox entry crosses from the harness to `tilo-connectors`,
    so `outbox.schema.json` joins the CP0 set although PRD 15.2's table does not list it. An
    entry exists only once authorised, so `authz` is required; T3 needs a person; any modifier
    means T3 (rules OB-01 to OB-05 in `contracts/outbox.rules.md`). The entry names everything
    it sends: the draft or file as a pinned `item` (artifact id and version) and the
    `destination` (the thread a reply goes into, the folder a file is saved in), so a connector
    never takes content from outside the contract. Card rule CR-12 requires the gate card's
    recipients, item and destination to equal the entry's, and OB-05 requires the entry's item
    to equal the one `approval.requested` reserved or `policy.applied` assessed, and an outgoing
    `data.transfer`'s artifact to equal it. OB-01 requires the entry's `authz`, and its outgoing
    `data.transfer`'s, to equal the `authz` of the `approval.resolved` that answered `approve`
    on its gate or of the `policy.applied` that opened it, so a gate nobody approved writes
    nothing and a policy action is never stamped as a person's (HR-7). A policy send has no gate
    card, so `policy.applied` records the connector, destination and district the engine
    checked, besides tier, undo window and item; the entry equals them, the named policy's scope
    covers its connector, recipients and district, and an L2 window is at least 1 s (OB-01,
    OB-05). A `destination` is an
    opaque connector id of letters, digits, `_` and `-`, never a URL, domain or path. A redraft is a new version and so a new proposal;
    it never goes out under an earlier authorisation (BQ-27). The modifier names moved to
    `policy.schema.json#/$defs/tier_condition` so that the risk-tier table and the outbox share
    one list. Consent cards get closed option ids `connect` and `hold` with fixed labels, like
    gates (CR-13). Changes made before the CP0 freeze keep version 1.0.0. The event contract's
    own decisions are in ADR-0005.
12. **Contracts SH asked for (ticket CC-SH, issues #3 to #5), all additive.**
    `agents.schema.json` (named `AgentsConfig` through the generator's `ROOT_NAMES`) shapes
    `config/agents.yaml`, which ships the PRD defaults. What the PRD fixes is `const`: one
    Director per world and one Lead per district, depth 3, `handoff_at` 0.70 (D-08). A schema
    cannot compare two fields, so `compact_at` < `handoff_at` becomes `compact_at` in (0, 0.70);
    `handoff_at` repeats its `const` as `minimum` and `maximum` because the Python generator drops
    a float `const`. `max_attempts` includes the first attempt and is at most 3 (BQ-58).
    `decision.schema.json` is the PRD 15.1 Decision; `answered_by` is `authz` narrowed to a person
    or a Team Lead, and a Team Lead's Decision names its domain. A Team Lead's `answered_by` also
    carries `user`, the person who held the Team Lead id and answered (required for a Team Lead,
    absent for a person, whose `ref` is already the user), because a `tl_` id is a mutable
    indirection: the owner can put another person behind it without a new assignment stamp.
    Reuse rules DC-01 to DC-04; a
    gate is never opened from a Decision (BQ-60). Only the source world's owner or a Team Lead
    gives a Decision (PRD 13.1; an Approver's answer makes none), a Decision's scope stays within
    the worlds where its answerer has that authority, and reuse checks the answerer again in the
    reusing world at the event's time, as OB-01 does for gates: the person is that world's owner,
    or the Team Lead's record still exists with the same domain and the same `user`, assigned by
    that world's owner no later than the answer. Cases are in `fixtures/decision/crossref/` with
    the reference check in `test_FR_AGT_07_decision_crossref.py`. `manifest.schema.json` is the
    PRD 13.3 manifest: lower-case SHA-256 hashes, a verified claim has a source; rules MF-01 to
    MF-06 (BQ-59). A source `ref` is an allowlist of four closed shapes (an http or https URL of
    host, port and a path without `;` or `=`; an artifact ref with a cell of letters, digits and
    `. _ ~ ! : $ -`; a connector ref; a plain file name), because a denylist of user-info
    spellings missed `//u@host`, `https:\u@host`, a leading space and query-string tokens (PRD
    16.1 rule 4, 16.2); a web `ref` therefore carries no query, fragment or path parameters. A
    bare token still fits a file name or an item id, so shapes are not the guarantee: the secret
    redactor that guards the raw archive checks every manifest before it is written and before it
    is exported, and a manifest it would change is refused (MF-06).
    `question.answered` data 1.1.0 adds `decision_id`, set exactly when `answered_by` is
    `decision`. A further valid case of an event type may sit next to the registry fixture as
    `fixtures/events/valid/<type>--<case>.json` (`question.answered--from_decision.json` cites a
    Decision fixture). `config/teams.yaml` is an example list of `team_lead.schema.json`
    entries; a trailing `[]` in `CONFIG_SHAPES` marks such a list file, and
    `just contracts-check` validates both new config files when present.
13. **Contracts SE asked for (ticket CC-SE, issues #7 to #12), all additive.** Five new
    contracts, each 1.0.0, with rules MT-01 to MT-14 in `contracts/metering.rules.md`:
    `metering.schema.json` shapes `config/metering.yaml` and `evals.schema.json` shapes
    `config/evals.yaml`; both files ship and `just contracts-check` validates them. As in decision
    12, what the PRD states as a rule is `const`, with a float `const` repeated as `minimum` and
    `maximum`: the 15% reserve and the budget request at 80% (14.1), the reconciliation tolerance of
    10% (14.4), the 20% cost-regression threshold (EFF-06) and three deploy-gate repeats (19.2).
    What the PRD calls a default or leaves to config is bounded only by sign: the per-run and
    per-user daily credit caps are required numbers above zero and never null, because PRD 14.1
    and FR-MTR-04 require both from config; only the per-org daily cap is above zero or null for
    none (BQ-42), its key still required. This keeps the PRD shape where issue #7 and SE's
    stand-in allowed every cap to be null. Rules MT-03 and MT-05 follow SE's merged Treasury
    (P8-01b): an actual cost above its reservation is recorded in full and halts the run, a day
    cap counts a commit on its reservation's UTC day (BQ-44), and every reservation waits while
    the kill switch is on. A grant never lifts a run above `caps.run_credits`, which PRD 17.3
    calls a ceiling; the Treasury's `grant` does not check this yet (issue #7). Daily spend caps are above zero (MT-01 keeps hard at least soft), eval pass caps above zero (BQ-43), and case
    counts for exactly the eight PRD 19.2 groups, whose rows sum to 160 although the heading says
    170 (BQ-67). `meter.schema.json` is the HUD meter's state for one run: `last_seq` lets a client
    drop a stale state, time saved may be negative and is never clamped, `steering_measured` says
    whether any attention was measured, and `method_url` is an https URL with no user info, query
    or fragment. `attention.schema.json` is one measured span of a person's steering or review
    time, holding ids and times only; its `ref` is a card ULID, an artifact id or null (BQ-65).
    `pilot.schema.json` follows `common`'s sampler convention (decision 3), since each pilot record
    is written on its own: a pseudonymous `tester_id` (`t_` and 6 to 32 lower-case letters or
    digits, never an email address or a name), consent to study `EV-G3` with `delete_after`,
    run and card tags, diary entries and survey responses with bounded free text; a survey `quote`
    is null unless `quote_consent` is true, and withdrawing consent deletes the tester's records
    (BQ-66, PRD 2.4, 16.5). `budget.requested` data 1.1.0 adds `remaining_units` (plan unit id and
    title, at most 200, in plan order) and `estimate` (a `credit_range`), both required, so the
    budget card can show the remaining plan and a new estimate (FR-MTR-03). A new required field
    counts as minor here because nothing emits `budget.requested` yet and the contract set is not
    frozen until CP0; after the freeze it would be major. The eval case file shape stays in
    `evals/case.schema.json`, because only the eval harness reads it and it crosses no service
    boundary.
14. **`grant_budget` and connector-less actions (ticket CC-SP-64, issue #64, FR-INT-08), config
    and documentation only.** `config/autonomy.yaml` maps `grant_budget` to T1, PRD 10.4's example
    "spend credits under the run budget". A budget grant goes through the deterministic policy
    engine like any other side effect, so an L3 policy such as "auto-approve under 100 credits"
    can approve one (FR-INT-08). Before this change an unlisted action type failed closed to T3
    (BQ-44), and so did every grant. The table holds no credit amounts and its six modifiers are
    fixed (BQ-16), so "under the run budget" is not a tier. The Treasury must never raise a run's
    budget above `caps.run_credits` (MT-03, PRD 17.3), whoever approves the grant, but
    `Treasury.grant` does not enforce that ceiling yet (issue #51, decision 13). A policy grant
    also stays within the policy's `limits.per_day` and `limits.credits` (BQ-14, BQ-52).
    `limits.credits` keeps its BQ-14 meaning, a daily total, which also bounds each grant: under
    "auto-approve under 100 credits" an 80-credit grant runs and a second one that day waits.
    `limits.credits` is optional in policy.schema.json, so an L3 `grant_budget` policy with
    `limits.credits: null` has no credit bound at all today. Until `budget.py` gates a policy grant
    when `limits.credits` is null or the grant would exceed `caps.run_credits` (issue #106 item 1),
    nothing may call `request_budget_grant` without a person's own approval (for example FR-MTR-03
    top-ups or a harness auto-start). Any active modifier makes a grant T3 in the table (PI-07),
    but `request_budget_grant` does not pass a world's facts yet, so a modifier such as an
    injection-flagged intake does not reach a grant until it does.
    A grant goes through no `tilo-connectors` connector. A policy's `scope.connectors` still needs
    at least one id, and the engine's proposal, `policy.applied` and an outbox entry each name a
    connector. For an action that goes through no connector, that id is the reserved `internal`.
    It is a valid `connector_id` that `config/connectors.yaml` never declares, so a policy scoped
    to it covers no real connector; a budget policy's scope is `connectors: [internal]`. A policy
    grant is recorded as one `budget.granted` whose `authz` is by the policy and names it (BQ-23).
    A grant has no gate and no outbox entry, so the FR-INT-08 path writes no `policy.applied`
    (OB-01 ties that event to an outbox entry it opened).
    `fixtures/events/valid/policy.applied--grant_budget.json` shows the value in a schema-valid
    `policy.applied`; its gate and outbox ids are sample values, not an emitted flow. No schema
    changes: `connector_id` already admits `internal`, and only its meaning gains a reserved value
    (BQ-75, overridable).
15. **`common` 1.2.0 (additive, 2026-10-05, merge housekeeping).** Two parallel branches each bumped
    `common.schema.json` to 1.1.0 with different content: ADR-0018 added `media_type` (artifact
    media types) and ADR-0016 (CC-PEOPLE) added the people ids, `opaque_ref`, `maker` and
    `record_ref`. After both merged, one version number named two contents. 1.2.0 is the merged
    file: nothing is removed or changed, so it is additive. Two tests that pinned `== "1.1.0"` now
    check "1.2.0 or later". **Rule for parallel contract branches:** before merging a branch that
    bumps a schema, compare its `x-version` with the base's and take the next free minor.
16. **`spend_caps.schema.json` 1.0.0 (additive, 2026-10-06, ticket SEC-16, FR-MTR-04).** A new
    contract, named `SpendCapsConfig` through `ROOT_NAMES` (tilo-api's loaded value is its own
    six-field `SpendCaps`), shapes `config/spend_caps.yaml`, which `CONFIG_SHAPES` adds to
    `just contracts-check`. It is a new file because `metering.schema.json` is closed and counts
    credits and US dollars, while SEC-16's cap is 1,000 INR per uid. Money is an integer in INR
    minor units (paise) and `currency` is `const` INR. As in decision 13, every key is required, no
    other key is allowed, and every cap is above zero and never null except the per-org daily cap
    (`org_day_minor`, null for no separate cap). JSON Schema reads 1000.0 as the integer 1000, so
    refusing a whole float is the loader's job, and so is the shipped file's `run_minor <=
    uid_lifetime_minor <= global_day_hard_minor` (checked by the SEC-16 config test). The shipped
    values convert PRD 17.3's US dollar figures at 80 INR per US$, below the market rate, so no INR
    cap exceeds its US$ counterpart: `run_minor` 12000 for 300 credits (US$1.50) and
    `global_day_hard_minor` 200000 for US$25 a day. The rate limit is 240 requests per uid per 60 s,
    because the web polls a run's events every second. This INR daily cap and `metering.yaml`'s
    `spend.daily_usd_hard` both trip NFR-24; the first one reached wins and neither replaces the
    other. How a live unit is priced in INR is BQ-SEC16-1 (a flat `unit_reserve_minor` until PL-06
    and a rate exist); that key waits until the SEC-16 tests admit it.

## Consequences
- Builders import `tilo_contracts` or `@tilo/contracts` and never hand-write these shapes.
  Generated types check shapes, not conditional or cross-reference rules: services validate
  incoming documents against the JSON Schema and run the rule validators.
- A schema edit without regeneration fails `just check`; so does a hand edit of generated code.
- The code generators and their versions are pinned by `uv.lock` and `pnpm-lock.yaml`;
  upgrading either may change generated output and is reviewed like any contract change.
- P0-03 added `event.schema.json`, the event registry, the per-type data schemas and
  `outbox.schema.json` under the same conventions; the generator picks up any new
  `contracts/**/*.schema.json` automatically, and a new event type also needs a registry entry
  and a fixture or `just contracts-check` fails.
