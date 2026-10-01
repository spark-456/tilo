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
