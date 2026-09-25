# ADR-0002: Contract conventions, fixtures and code generation

- Status: Accepted (2026-09-25, architect; ticket P0-02). Amended 2026-09-25 by ticket P0-03
  (decisions 1, 8 and 10). The contract set freezes at CP0 on 29 Sep.
- Deciders: architect, orchestrator
- Requirement: FR-WLD-02 (PRD 15.2); FR-WLD-03 for the P0-03 amendment

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
10. **The outbox is a contract (P0-03).** PRD 15 says every structure that crosses a service
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
    nothing and a policy action is never stamped as a person's (HR-7). A `destination` is an
    opaque connector id of letters, digits, `_` and `-`, never a URL, domain or path. A redraft is a new version and so a new proposal;
    it never goes out under an earlier authorisation (BQ-27). The modifier names moved to
    `policy.schema.json#/$defs/tier_condition` so that the risk-tier table and the outbox share
    one list. Consent cards get closed option ids `connect` and `hold` with fixed labels, like
    gates (CR-13). Changes made before the CP0 freeze keep version 1.0.0. The event contract's
    own decisions are in ADR-0005.

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
