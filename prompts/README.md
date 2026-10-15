# prompts/

Prompt templates per agent role (PL-04, PRD 6.4): templates in `prompts/`, optional
per-provider overrides, no prompt text in code. Loaded by
`tilo_providers.prompts.load_prompt`.

```
prompts/
  <role>/
    <template>.md                    # base template
    <template-stem>.<provider>.md    # optional per-provider override
```

`<role>` matches a role in `config/models.yaml`. Substitution: stdlib
`string.Template` (`$name` / `${name}`, no `eval`), filled in strictly.

Provider-layer templates (`router/` EFF-02 repair, `conformance/` PL-05 probe) and the `director/`
brief extraction (FR-INT-03: `brief_system.md` instructions, with the FR-INT-12 category list as `$categories`, the FR-INT-15 gap list as `$gaps` and the connected services as `$services`; `brief_task.md` the delimited task data).
`autopilot/` is Email Autopilot triage (FR-CHN-09: `triage_system.md` instructions, `triage_task.md` the
delimited, untrusted mail data) and drafting (FR-CHN-10: `draft_system.md` instructions, `draft_task.md` the
delimited thread data). `specialist/must_ask_*.md` is the must-ask check before a unit starts (FR-AGT-05:
`must_ask_system.md` instructions, `must_ask_task.md` the delimited unit data). `verifier/claim_*.md` judges
one claim against its cited sources (FR-AGT-12: `claim_system.md` instructions, `claim_task.md` the delimited,
untrusted claim and source text).
`writer/build_handoff.md` is the framing paragraph of a build handoff (FR-CON-16): `$requirements` is
`tilo_connectors.handoff.writer_brief(...)` run through `neutralise_marker(..., "REQUIREMENTS")`, the only data the writer
sees, and `$max_framing_chars` comes from `config/build_partners.yaml`. Code checks the reply before it is used (BH-03).
`assistant/` is the panel's model fallback (FR-PA-14, FR-PA-17): `route_system.md` instructions with the fact intents and routes of `config/assistant.yaml` as `$intents` and `$routes`, `route_task.md` the delimited, untrusted question (`$question`, run through `neutralise_marker(..., "QUESTION")`) with `$screen` and `$context`. The person's plate rows are not in the template: `tilo_api.assistant.model` hands them to the Router as one tool output (`<<<ROWS ... ROWS>>>`, titles through `neutralise_marker`) so the Router compacts the rows, never the question. The reply is one JSON object that code parses and the core vets.
`search/ground.md` is the system instruction of a grounded web search (LW-05, `tilo_providers.google_search_adapter`); it takes no variables, and the query is sent as the user turn after the secret redactor ran on it.
`assistant/quick_*.md` is Quick mode of `POST /intake` (COST-FAST-1): `quick_answer_*` the plain one-call answer, `quick_classify_*` the JSON verdict for a text no rule reads (`$reasons`); in both the question (`$question`) is delimited, untrusted data run through `neutralise_marker(..., "QUESTION")`.

Dates (INTAKE-QUALITY-1, FR-INT-03/06/09, FR-AGT-12): every template that plans or checks a schedule takes `$today`, `$deadline` and `$days_to_deadline`, calendar facts that code fills from `tilo_providers.clock.time_facts` (the `director/` brief, approaches and plan templates and their repairs, and the `specialist/`, `writer/`, `verifier/` and `lead/` unit templates through `tilo_harness.unit_prompt.request_variables`). A model is never left to guess the date.
`specialist/tools.md` and `tools_read_only.md` frame the tool loop of `ToolUnitRunner` (LW-07) for every worker role: `$base` is the unit prompt, `$tools` the tools now allowed, `$results` the fenced tool results (data, not instructions).

Questions (INTAKE-QUALITY-1 slice 2, FR-INT-04): `director/brief_system.md` also asks for an optional `questions` list (up to 3, each a label, a question, one to three suggested answers and an expected_change). Code vets and ranks it (`tilo_planning.brief.topic_questions`); the model's text is untrusted and never reaches a prompt except as a cleaned `Label: value` constraint.

`skill_describe/` is capture by describing (SKILLS-4, FR-SKL-01/02), run on the role in `tilo_api.skills_capture.CAPTURE_ROLE`: `capture_*` turns the delimited, untrusted description (`neutralise_marker(..., "DESCRIPTION")`) into steps; `version_*` turns the captured steps (`STEPS` block) into plan steps from the closed list of `config/connectors.yaml` actions (`$actions`) and at most one question. Code checks every reply; the model never sets must_ask, ask_first or an estimate.

`meeting_analyst/meeting_brief.md` is the owner's meeting brief (ADR-0047, MB-03, `tilo_api.meeting_brief`): the system instruction (`$max_points`, `$max_chars`) for talk points over the delimited, untrusted agenda lines and prior-minutes items in the user turn (`<<<DATA ... DATA>>>`, each with a source id `a<n>` or `p<n>`). Code copies the agenda and carry-over and keeps a point only if its text is a clean line and every source id was offered (MB-04, MB-05).

`speech/live_read_aloud.md` is the system instruction of the optional Gemini Live voice (FR-MTG-11, M2, `tilo_providers.gemini_live_voice_adapter`): read the reply aloud, once, as written; it takes no variables, and the reply text is the user turn (data, never instructions).
