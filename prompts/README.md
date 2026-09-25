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

Provider-layer templates (not agent roles): `router/schema_repair.md` (EFF-02 repair) and
`conformance/safety_probe.md` (PL-05 safety check). No agent-role prompts yet — scaffolding until the agent roles that need them (P2+) land.
