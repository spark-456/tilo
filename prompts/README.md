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
brief extraction (FR-INT-03: `brief_system.md` instructions, `brief_task.md` the delimited task data).
`autopilot/` is Email Autopilot triage (FR-CHN-09: `triage_system.md` instructions, `triage_task.md` the
delimited, untrusted mail data) and drafting (FR-CHN-10: `draft_system.md` instructions, `draft_task.md` the
delimited thread data). `specialist/must_ask_*.md` is the must-ask check before a unit starts (FR-AGT-05:
`must_ask_system.md` instructions, `must_ask_task.md` the delimited unit data). `verifier/claim_*.md` judges
one claim against its cited sources (FR-AGT-12: `claim_system.md` instructions, `claim_task.md` the delimited,
untrusted claim and source text).
