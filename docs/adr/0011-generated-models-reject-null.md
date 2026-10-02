# ADR-0011: Generated Python models reject null where the schema does

- Status: Proposed — awaiting user approval (2026-10-02, architect; issue #56). No schema changes.
  It changes the generated contract types that every service imports
  (`packages/contracts-py`) and the drift check, so it waits for the user's approval with the
  other contract proposals.
- Deciders: user (approval), architect (proposal)
- Requirement: FR-WLD-02 (CI fails if generated types drift from schemas), FR-INT-03

## Context
`contracts/brief.schema.json` makes `$defs.source.label` optional, and when present it must be a
string. The generated pydantic model is:

```python
label: Annotated[str | None, Field(max_length=120, min_length=1)] = None
```

So `{"kind": "web", "ref": "q", "label": null}` passes `tilo_contracts.BriefSource` and fails
the JSON Schema. datamodel-code-generator types every optional property as `X | None = None`.
The codegen already passes `--strict-nullable`, but that flag only reads OpenAPI's `nullable`
and has no effect on JSON Schema input. The FR-WLD-02 check compares the generated text and
round-trips the valid fixtures, so nothing notices a model that is looser than its schema.

SP strips `label: null` from model output before validating
(`packages/planning/src/tilo_planning/brief.py`). The same gap exists for every optional
property whose schema does not allow null. Besides the sampler roots of `common` and `pilot`,
that is about 20 properties in real documents:
- brief `source.label` and card `option.reason`;
- common `artifact_ref.label`;
- the seven connector `scopes` actions;
- decision `answerer.user` and the registry entry's `authz_by`;
- layout building `common_type` and `kit`, and agent `team_lead`;
- providers profile `base_url` and `api_key_env`, and role `fallback`, `cascade`, `thinking`,
  `max_input_tokens` and `max_output_tokens`.

TypeScript already matches the schema: json-schema-to-typescript emits `label?: string`, which
refuses null.

## Decision (proposed)
1. **Codegen post-processing** (`scripts/contracts_codegen.py`, after `generate_python`). From the
   bundled schema, compute each generated model's optional properties whose schema does not
   admit null, by their JSON names (and field names where an alias differs). Then:
   - emit one base class in the generated module;
   - give each affected model a class variable listing those properties.

   A `before` validator refuses an explicit null. A property that is left out still reads as
   `None`, so the annotation stays `X | None = None` and readers stay type-safe.
2. **Drift check.** `check_models` gains a null probe. For every valid fixture, it walks the
   instance alongside its schema. For each object node with an optional, non-nullable property,
   it sets that property to null and requires the root model to refuse the result, as the JSON
   Schema does. A model that accepts it fails `just contracts-check` (FR-WLD-02).
3. **No schema changes and no version bumps.** The generated header's content hashes are
   unchanged because the schemas are. Only the generated code differs.

Sketch of the generated output (checked against pydantic 2 in the workspace: left out passes,
set passes, null is refused, both nested and through the constructor):

```diff
 packages/contracts-py/src/tilo_contracts/__init__.py  (generated)
+class ContractModel(BaseModel):
+    """Optional properties the contract does not allow to be null may be left out, never null (ADR-0011)."""
+
+    _not_null: ClassVar[frozenset[str]] = frozenset()
+
+    @model_validator(mode="before")
+    @classmethod
+    def _optional_is_never_null(cls, data: Any) -> Any:
+        if isinstance(data, dict):
+            nulls = sorted(name for name in cls._not_null if name in data and data[name] is None)
+            if nulls:
+                raise ValueError(f"{', '.join(nulls)} may be left out but never null")
+        return data
+
+
-class BriefSource(BaseModel):
+class BriefSource(ContractModel):
     model_config = ConfigDict(
         extra="forbid",
     )
+    _not_null: ClassVar[frozenset[str]] = frozenset({"label"})
     kind: Literal["file", "url", "connector", "web", "memory"]
     ref: Annotated[str, Field(max_length=2000, min_length=1)]
     label: Annotated[str | None, Field(max_length=120, min_length=1)] = None
```

```diff
 scripts/contracts_codegen.py
     python = generate_python(bundled, head) + events.python_constants(registry, data_model)
+    python = forbid_explicit_null(python, bundled)  # ADR-0011: omitted is fine, null is not
     module = load_module(python)
-    problems = check_models(schemas, module)
+    problems = check_models(schemas, module) + null_probe(schemas, module)  # FR-WLD-02
```

## Alternatives considered
- **Make all those properties nullable in the schemas.** This loosens the contracts: for
  example, `fallback: null` would become a valid way to say "no fallback". It would also mean
  many version bumps and two spellings for "absent". Rejected.
- **Type them as `str` with a `None` default.** Type checkers flag it, and readers would see
  `str` while getting `None`. Rejected.
- **Validate with jsonschema at every boundary.** That means two validators, and a builder will
  forget one. It stays as the extra check some services already run (cards, policy), not as the
  fix.
- **A generator flag.** No flag in datamodel-code-generator refuses explicit null for JSON Schema
  input. `--strict-nullable` is OpenAPI-only, and it is already set.

## Migration and fixture impact
- Regenerate with `just contracts-gen`. Code that passes `None` explicitly to one of these
  properties now fails validation. A search of `packages/`, `services/` and `apps/` found no
  such construction. SP's `brief.py` strip of `label: null` can stay as a clean-up of model
  output.
- Fixtures:
  - Valid fixtures never carry these nulls, since they pass the JSON Schema, so none change.
  - Add `contracts/fixtures/brief/invalid/source_label_null.json` (fails the JSON Schema), so
    the case is on record and the probe has a named example.
- A test-writer test for the probe, for example
  `test_FR_WLD_02_generated_models_reject_null_where_schema_does`. It runs inside the drift
  sandbox, which holds `contracts/`, `packages/contracts-*` and `scripts/` and needs nothing
  else.
- TypeScript output does not change.

## Consequences
- The generated types match the schemas on nullability too. FR-WLD-02's drift check now covers
  it.
- FR-INT-03 no longer depends on SP's workaround to keep a brief valid.
- The codegen must refuse a contract property literally named `_not_null`. It can check for this
  while computing the sets.
