# packages/

Shared libraries. The Python packages are members of the uv workspace (root `pyproject.toml`); `contracts-ts` is a pnpm
workspace member. Services import them as libraries; none of them is deployed on its own.

| Package | Import name | What it is | Used by |
| --- | --- | --- | --- |
| [`providers`](providers/CLAUDE.md) | `tilo_providers` | the model provider layer: roles from `config/models.yaml`, adapters (Vertex/Gemini, OpenAI-compatible for NVIDIA NIM and Gemini, Model Armor, Google search, speech, Chirp TTS), the router with fallback and budget, record-and-replay and fake providers, the only place a model id may appear | api, harness, planning, channels, meet-bot, evals |
| [`policy`](policy/CLAUDE.md) | `tilo_policy` | the deterministic policy engine: risk tiers from `config/autonomy.yaml`, autonomy levels L0 to L3, `decide`, `open_gate`, access levels | api, connectors, channels, harness |
| [`planning`](planning/CLAUDE.md) | `tilo_planning` | intake limits, brief, questions, approaches, the plan compiler, `validate_plan`, estimates and budget grants | api, browser, evals |
| [`world`](world/CLAUDE.md) | `tilo_world` | the deterministic layout solver (World, Levels, Districts, Buildings). Event-to-entity rendering is in `apps/web/src/world` | api |
| [`memory`](memory/CLAUDE.md) | `tilo_memory` | result cache, event ledger (with a BigQuery adapter tested on mocks), artifact store with versions and provenance, retention and erasure, per-account retrieval chunks | api, harness, planning |
| [`archive`](archive/CLAUDE.md) | `tilo_archive` | the hash-chained raw run archive and document parsers | api, harness, browser |
| [`metering`](metering/CLAUDE.md) | `tilo_metering` | prices, credits, the Treasury ledger, caps and the `replay_only` kill switch, cost reports | api, evals |
| [`people`](people/CLAUDE.md) | `tilo_people` | the visibility oracle for persons, meetings, work items and pins; write checks; teams; free-slot search | api, channels |
| [`redact`](redact/CLAUDE.md) | `tilo_redact` | secret-shaped string redaction (standard library only) | providers, api, channels |
| [`logging`](logging/CLAUDE.md) | `tilo_logging` | structured JSON logging with world and trace ids | api, harness, browser, render |
| [`contracts-py`](contracts-py/CLAUDE.md) | `tilo_contracts` | Pydantic types generated from `contracts/*.schema.json` | everything in Python |
| [`contracts-ts`](contracts-ts/CLAUDE.md) | `@tilo/contracts` | TypeScript types generated from the same schemas | `apps/web` |

The two contracts packages are generated, not hand-edited: `just contracts-gen` writes them and `just contracts-check`
(the first step of `just check`) fails on any drift. Each package has its own `CLAUDE.md` with its requirement IDs and
local rules, and its own `tests/` folder (`uv run pytest packages/<name>`).
