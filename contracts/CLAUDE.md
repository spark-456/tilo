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
- One file per contract, `$id` `https://contracts.tilo.example/<path>.schema.json` where
  `<path>` is the file's path under `contracts/` (`event`, `events/registry`,
  `events/data/building.completed`), `title` = the generated name (PascalCase; `EventRegistry`;
  `<Type>Data` for event data), top-level `"x-version"`. Cross-file refs are relative
  (`common.schema.json#/$defs/x`, `../../common.schema.json#/$defs/x` from `events/data/`).
- A new event type needs a registry entry, a data schema, a valid fixture and, if it is a side
  effect, the same type in `event.schema.json`'s side-effect list (`event.rules.md`).
- Avoid a root-level `allOf`: json-schema-to-typescript turns it into an open intersection
  type. Nest conditionals as one `if`/`then`/`else` instead.
- `additionalProperties: false` unless a field is explicitly open; enums are closed.
- Every object shape is a named `$defs` entry, so generated names stay stable. `$defs` names
  must not collide across files once prefixed (the generator fails loudly if they do).
- Frozen at CP0 (29 Sep): additive change = minor version; breaking change = major version,
  migration, ADR and the user's approval.
- Every change ships with valid and invalid fixtures (one invalid file per rule, named after
  the rule), regenerated types in the same commit, and no secrets, real people or real model
  ids in fixtures (use example.com / example.org and fake profiles).
- Never edit generated files; change the schema and run `just contracts-gen`.
