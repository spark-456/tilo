# ADR-0027: Speech role and audio price, `team_rule.changed`, skill `tool_access`

- Status: Proposed. Written by the architect on 2026-10-08 for the user's approval. Every change
  here is additive, but `providers`, the event registry, `skill` and `common` are frozen
  contracts (CP0, 29 Sep), so nothing that depends on them merges until the user says yes.
  **The user should check the three Decision sections below.**
- Deciders: user (approval), architect
- Requirements: FR-MTG-17 (Should), FR-MTG-11 (Must by CP4), PL-03, PL-06 (speech);
  FR-TEAM-04 (Must), FR-ACC-01 (Must) (team rule event); FR-ACC-02 (Should) (skill level).
  FR-TEAM-* and FR-ACC-* are in `docs/prd-supplement-design-2026-10-06.md`; FR-MTG-* in
  `docs/prd-addendum-people-agents.md`.
- Questions it answers: BQ-MTG17-3, BQ-TEAMACC-1, BQ-TEAMRT-4, BQ-ACC02-1 (open PRs #641, #619,
  #642, #630). New questions: BQ-ADR27-1 to BQ-ADR27-4.

## Context
1. **Speech.** PRD 6.4 sends every speech call through the provider layer and lets business code
   ask only for a role. PR #641 (FR-MTG-17) ships `SpeechProvider` as a seam on its own
   `config/speech.yaml` (vendor, profile, model, caps). So the speech call has no role: the
   router's fallback (NFR-25) does not serve it and nothing meters it, because
   `config/prices.yaml` has no price for it (PL-06). `providers.schema.json` already accepts any
   role name and any provider slug. What it cannot express is the price. Gemini lists a separate
   rate for audio input tokens, apart from text input for the same model, and `$defs.price` has
   only `input` and `output`. The audio rates for Tilo's profiles were not checked here
   (BQ-ADR27-1).
2. **Team rules.** FR-TEAM-04 says every change to the five stop-and-ask switches is logged.
   PR #642 serves the switches and the per-connector tool levels (FR-ACC-01) from tilo-api, but
   no registered event fits. `policy.changed` belongs to a covering policy and is a side effect,
   so #642 writes a logger line only (BQ-TEAMACC-1).
3. **Per-skill level.** FR-ACC-02: a skill may use a tool at a lower level than the team, never a
   higher one. `tilo_policy.access_levels.effective_level(team, skill)` already takes the lower
   of the two (#619, #630). But `skill.schema.json` has no field for a skill's level, so
   `skill_level` is always None (BQ-TEAMRT-4).

## Decision 1: the `speech` role and `audio_input` (providers 1.2.0)
1. **Role.** `speech` is the role every `SpeechProvider` call asks for: recording upload
   (FR-MTG-17), voice notes (FR-INT-14, FR-CHN-16) and FR-MTG-11's speech calls. It lives in
   `config/models*.yaml` like every role and uses the existing `role` shape. There is no new
   "profile kind". The role picks the interface (`SpeechProvider`) and the profile's `provider`
   picks the adapter (`google` gives Gemini audio, `fake` the dev fake), as `safety` already does
   with `model_armor`.
2. **Loader rules** (stated in the `roles` description and enforced by the provider loader):
   - the role states `max_output_tokens`. A transcript is long, and the router's default of 1024
     (BQ-63) would cut it;
   - every profile it names (primary, fallback, cascade) declares the `audio` capability;
   - while prices are `set`, each of those profiles has an `audio_input` price.
   The NFR-25 fallback rule applies as for any role.
3. **Price.** `$defs.price` gains `audio_input`, optional: US dollars per million audio input
   tokens. It is null only while prices are `unset`, like the other two fields. A speech call
   costs audio tokens times `audio_input`, plus the call's other input tokens times `input`,
   plus output tokens times `output`. If the provider does not report the audio share, all
   input is priced at the higher of the two input rates. That overstates the cost, never
   understates it, as ADR-0022 decision 7 does. One price row per model keeps one profile for
   both text and audio roles.
4. **What `config/speech.yaml` keeps.** Only the upload caps, `max_bytes` and `max_duration_ms`.
   They are checked before any request and have no token equivalent. `vendor`, `profile` and
   `model` move to the role, so model ids live only in `config/models*.yaml` (PL-01) and the
   PL-07 deny rules apply without a second check.
5. **Not covered.** Per-minute pricing (Google Cloud Speech-to-Text). D-1 chose Gemini audio. A
   per-minute vendor would need its own additive field later. Gemini Live and Cloud TTS
   (FR-MTG-16) are also not covered; this role is `transcribe` only.

## Decision 2: `team_rule.changed` (registry 1.2.0, a new family `team_rule`)
1. **One event per changed rule.** `data` is `{rule, key, from, to}`:
   - `rule: switch`: `key` is one of `spend`, `share`, `undo`, `tools`, `weekend` (a closed enum,
     the Team page's five switches) and `from`/`to` are `on` or `off`;
   - `rule: tool_access`: `key` is a connector id and `from`/`to` are `off`, `read`, `draft` or
     `act` (`common` 1.5.0 `tool_access_level`).
   `from` is the value in force before the change: an unset tool is `act` and an unset switch
   has its configured default.
2. **Must-ask switches.** `spend`, `share` and `undo` are PRD 8.3 Must-ask rules. The schema
   refuses `to: off` for them (FR-TEAM-04: "can't be switched off"). `from: off` stays valid, so
   the event can record a tampered store being repaired (BQ-TEAMRT-3).
3. **Writer and place.** The writer is tilo-api's team routes, after the team store's
   compare-and-set succeeds. An agent or a model never writes it. The event goes in the Desk
   world of the person who made the change (PE-12):
   - `actor` and `target` are that person's user id. Only the Owner may change a rule
     (BQ-TEAMACC-2).
   - `district`, `level` and `item` are null.
   - `vis` is `[]`, owner-only (ADR-0009).
   - `authz` is null.
   Registry: pillar P4, priority must, severity info, `side_effect: false`.
4. **Why not a side effect.** A switch or a tool level only narrows what reaches the policy
   engine. `tilo_api.team_access.tool_check` refuses and never authorises, and an unset tool
   was already `act`, so raising a level back to `act` never goes past the baseline. Every send
   still needs its gate or policy (`authz`). So the event records a governance change, not an
   authorisation (EV-05 keeps `authz` null).
5. **Not team rules.** Role changes, spend limits, invites and removals are not covered. #642
   logs them as logger lines (BQ-ADR27-3).
6. **Checks.** The schema enforces the rule kinds, the key sets, the value sets and the Must-ask
   rule. The writer rules in 3 (person actor equal to target, Desk world, `vis: []`) are in the
   data schema's description, but no validator checks them yet (BQ-ADR27-2).

## Decision 3: skill `tool_access` (skill 1.1.0, common 1.5.0)
1. `skill.yaml` gains an optional `tool_access`: a map from connector id
   (`config/connectors.yaml` or `config/mcp.yaml`) to `tool_access_level`.
2. The level in force is `effective_level(team, skill)`, the lower of the two. So a skill's
   value can only lower the team's level. `act` sets no further limit. A connector the skill
   leaves out uses the team's level.
3. The field is part of the signed-off, version-pinned skill (PRD 8.2: the expert approves
   changes, a run pins versions). Changing it is a new skill version, and the Trace shows
   which version, and so which levels, a run used.
4. A per-team override edited at run time on the Skills page is not covered (BQ-ADR27-4).

## Consequences
- **Versions.** `providers` 1.1.0 to 1.2.0, `common` 1.4.0 to 1.5.0, `skill` 1.0.0 to 1.1.0, and
  `events/registry` (schema and yaml) 1.1.0 to 1.2.0; new `events/data/team_rule.changed` 1.0.0.
  Every shipped config file, skill and event stays valid. Generated Python and TypeScript types
  and `apps/web/src/world/registry.generated.ts` are regenerated.
- **Tests.** Two tests that pinned an exact version now check a floor: `test_CC_PEOPLE_FR_WLD_03`
  (registry 1.1.0) and `test_PL_02_providers_schema_version_bumped_to_minor_1_1_0` (providers
  1.1.0). New: `tests/contracts/test_ADR_0027_speech_team_rule_tool_access.py`.
- **Builder follow-ups** (after the user's yes; none merge before it):
  - FR-MTG-17 / #641 (intelligence-builder):
    - the provider loader enforces decision 1.2;
    - the speech layer resolves the `speech` role (primary, then fallback on a provider error)
      and meters with decision 1.3;
    - `config/speech.yaml` loses `vendor`, `profile` and `model`;
    - `config/models.dev.yaml` gets a `speech` role on a fake profile, and `prices.dev.yaml`
      gives it `audio_input: 0`;
    - `test_NFR_25`'s role-set pin gains `speech`;
    - the production `config/models.yaml` gets the role only once the user has confirmed the
      audio prices (BQ-ADR27-1).
  - TEAM-ROUTES / #642 (reach-builder): `put_switch` and `put_tool` emit `team_rule.changed`
    through the Desk-world writer after a successful compare-and-set (the `_audit` logger line
    can stay). A test that tries `spend` to `off` is refused before any event is written.
  - FR-ACC-02 / #630 and #642: the skill loader reads `tool_access` into `skill_level`, and
    `runs.Run.gate` passes it to `effective_level`.

## Alternatives considered
- **A separate audio-only profile priced at the audio rate, with no schema change.** Rejected:
  the same model would have two profiles, and the prompt's text tokens would be priced at the
  audio rate. A 30-second voice note is about 960 audio tokens beside a few hundred prompt
  tokens, so the cost could be overstated past FR-MTR-01's 10% reconciliation tolerance.
- **Moving the upload caps onto the role.** Rejected: a byte or duration cap is not a token cap.
  It would add a speech-only field to every role.
- **Making `team_rule.changed` a side effect with `authz_by: [person]`.** Rejected: it would claim
  an authorisation that never happens, and it would pull the event into the side-effect checks
  (EV-03, EV-04, SEC-11) that are meant for sends and their approvals.
- **Booleans for switch values.** Rejected: one string enum keeps `from`/`to` a single type in
  both generated languages, and the Story line reads "weekend is now on".
