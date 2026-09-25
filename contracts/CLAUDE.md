# contracts/

## Purpose
JSON Schemas (2020-12) for every structure that crosses a service boundary, their fixtures and
the rules a schema cannot express. First source of truth (root CLAUDE.md). Conventions:
`docs/adr/0002-contract-conventions.md`.

## Commands
- `just contracts-gen` - regenerate `packages/contracts-py` and `packages/contracts-ts`
- `just contracts-check` - validate schemas and fixtures, fail on drift (part of `just check`)
- `uv run pytest tests/contracts -q` - acceptance tests

## Local rules
- Owned by the architect. Builders never edit this folder; they report "needs contract change: ...".
- One file per contract, `$id` `https://contracts.tilo.example/<name>.schema.json`, `title` =
  PascalCase name, top-level `"x-version"`. Cross-file refs are relative
  (`common.schema.json#/$defs/x`).
- `additionalProperties: false` unless a field is explicitly open; enums are closed.
- Every object shape is a named `$defs` entry, so generated names stay stable. `$defs` names
  must not collide across files once prefixed (the generator fails loudly if they do).
- Frozen at CP0 (29 Sep): additive change = minor version; breaking change = major version,
  migration, ADR and the user's approval.
- Every change ships with valid and invalid fixtures (one invalid file per rule, named after
  the rule), regenerated types in the same commit, and no secrets, real people or real model
  ids in fixtures (use example.com / example.org and fake profiles).
- Never edit generated files; change the schema and run `just contracts-gen`.
