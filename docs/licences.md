# Licences

Every direct dependency (Python and JS, dev and runtime) and tool the Tilo build uses, per
CLAUDE.md's "record every dependency's licence" rule. Updated whenever a dependency is added.

## Python (root `pyproject.toml` dev group, `uv`-managed)

| Dependency | Licence | Source |
| --- | --- | --- |
| pytest | MIT | https://pypi.org/project/pytest/ |
| hypothesis | MPL-2.0 | https://pypi.org/project/hypothesis/ |
| ruff | MIT | https://pypi.org/project/ruff/ |
| mypy | MIT | https://pypi.org/project/mypy/ |
| pre-commit | MIT | https://pypi.org/project/pre-commit/ |
| pyyaml | MIT | https://pypi.org/project/PyYAML/ |
| httpx | BSD-3-Clause | https://pypi.org/project/httpx/ |
| jsonschema | MIT | https://pypi.org/project/jsonschema/ |
| referencing | MIT | https://pypi.org/project/referencing/ |
| datamodel-code-generator (generates `packages/contracts-py`) | MIT | https://pypi.org/project/datamodel-code-generator/ |

## Python (`services/api`)

| Dependency | Licence | Source |
| --- | --- | --- |
| fastapi | MIT | https://pypi.org/project/fastapi/ |
| python-multipart (`tilo-api` form uploads) | Apache-2.0 | https://pypi.org/project/python-multipart/ |
| uvicorn | BSD-3-Clause | https://pypi.org/project/uvicorn/ |

## Python (`packages/contracts-py`)

| Dependency | Licence | Source |
| --- | --- | --- |
| pydantic | MIT | https://pypi.org/project/pydantic/ |

## Python (`services/harness`)

| Dependency | Licence | Source |
| --- | --- | --- |
| google-adk | Apache-2.0 | https://pypi.org/project/google-adk/ |
| google-cloud-firestore | Apache-2.0 | https://pypi.org/project/google-cloud-firestore/ |

`services/harness` also uses `pyyaml`, `jsonschema` and `referencing` (already listed under the
root dev dependency group), declared as its own direct dependencies since its code imports them
directly rather than relying only on the shared dev group. FR-AGT-01/02/03 adds the in-workspace
`tilo-contracts` and `tilo-providers` members (not external; no new licence).

## Python (`packages/providers`)

No new dependency was added for ticket P0-04 (`packages/providers/pyproject.toml` still
declared none of its own): `tilo_providers.config` uses `pydantic` (already listed under
`packages/contracts-py`, via the `tilo-contracts` workspace member it imports) and `pyyaml`
(already listed under the root dev dependency group); both are already installed into the
shared `uv` workspace venv by `uv sync --all-packages`.

## Python (`packages/policy`)

`tilo-policy` declares `pyyaml`, `jsonschema` and `referencing` as runtime dependencies (ticket
P4-01); all three are already listed above under the root dev dependency group (MIT). No new
licence.
Ticket P0-05 adds two direct runtime dependencies (`packages/providers/pyproject.toml`):

| Dependency | Licence | Source |
| --- | --- | --- |
| google-genai (`tilo_providers.google_adapter`, PRD 6.4/6.5) | Apache-2.0 | https://pypi.org/project/google-genai/ |
| httpx (`tilo_providers.openai_compat_adapter`, PL-02; already a root dev dependency, above) | BSD-3-Clause | https://pypi.org/project/httpx/ |

`google.genai.Client(vertexai=True, ...)` is only ever constructed under `LIVE=1`
(`tilo_providers.factory`); dev/CI tests fake the `google.genai` import path at the
`sys.modules` boundary and never install real credentials (EFF-01).

## Python (`services/connectors`)

`tilo-connectors` declares `jsonschema` and `referencing` as runtime dependencies (ticket ST-2 /
FR-AGT-11), both already listed above (MIT); and the in-workspace `tilo-policy` (not external).
No new licence.

## Python (`packages/planning`)

`tilo-planning` (FR-INT-01/02) depends only on the in-workspace `tilo-contracts` and
`tilo-providers` (not external); `tilo-api` now depends on the in-workspace `tilo-planning`.
No new licence.

## Python (`services/render`)

| Dependency | Licence | Source |
| --- | --- | --- |
| reportlab | BSD | https://pypi.org/project/reportlab/ |
| pypdf | BSD-3-Clause | https://pypi.org/project/pypdf/ |

`tilo-render` (AGR-01/03 / FR-CON-09) also uses `pydantic` (already listed under `packages/contracts-py`, MIT) and `pyyaml` (already listed under the root dev dependency group, MIT).

## JavaScript / TypeScript (root `package.json` and `apps/web`, `pnpm`-managed)

| Dependency | Licence | Source |
| --- | --- | --- |
| @biomejs/biome | MIT | https://www.npmjs.com/package/@biomejs/biome |
| firebase-tools (runs the Firestore emulator for `services/harness`, P0-09) | MIT | https://www.npmjs.com/package/firebase-tools |
| typescript | Apache-2.0 | https://www.npmjs.com/package/typescript |
| react, react-dom, pixi.js, vite, @vitejs/plugin-react, vitest, @types/node, @types/react, @types/react-dom | MIT | https://www.npmjs.com/ |
| @playwright/test | Apache-2.0 | https://www.npmjs.com/package/@playwright/test |
| @axe-core/playwright | MPL-2.0 | https://www.npmjs.com/package/@axe-core/playwright |
| @fontsource/nunito, @fontsource/nunito-sans, @fontsource/jetbrains-mono | MIT; fonts Nunito, Nunito Sans, JetBrains Mono are OFL-1.1 | https://fonts.google.com/ |
| fast-check (property tests, ticket P0-08b-player, FR-WLD-04) | MIT | https://www.npmjs.com/package/fast-check |
| @tilo/contracts (`packages/contracts-ts`, internal workspace package, not third-party) | n/a | `packages/contracts-ts` |

## JavaScript / TypeScript (`packages/contracts-ts` devDependencies)

| Dependency | Licence | Source |
| --- | --- | --- |
| json-schema-to-typescript (generates `packages/contracts-ts`) | MIT | https://www.npmjs.com/package/json-schema-to-typescript |
| typescript | Apache-2.0 | https://www.npmjs.com/package/typescript |

## Tools

| Tool | Licence | Source |
| --- | --- | --- |
| uv | MIT / Apache-2.0 | https://github.com/astral-sh/uv |
| just | CC0-1.0 | https://github.com/casey/just |
| pnpm | MIT | https://github.com/pnpm/pnpm |
| Biome | MIT | https://github.com/biomejs/biome |
| Terraform | BUSL-1.1 (HashiCorp; run only by the user per CLAUDE.md, never `terraform apply` from an agent) | https://github.com/hashicorp/terraform |
| pip-audit | Apache-2.0 | https://github.com/pypa/pip-audit |

## CI actions and pre-commit hook repos

Third-party code run in CI (`.github/workflows/ci.yml`) or on developer machines
(`.pre-commit-config.yaml`).

| Component | Pinned ref | Licence | Source |
| --- | --- | --- | --- |
| actions/checkout | v4 | MIT | https://github.com/actions/checkout |
| astral-sh/setup-uv | v4 | MIT | https://github.com/astral-sh/setup-uv |
| actions/setup-node | v4 | MIT | https://github.com/actions/setup-node |
| extractions/setup-just | v2 | MIT | https://github.com/extractions/setup-just |
| actions/setup-java (Firestore emulator's JRE, P0-09) | v4 | MIT | https://github.com/actions/setup-java |
| pre-commit/pre-commit-hooks | v5.0.0 | MIT | https://github.com/pre-commit/pre-commit-hooks |

## Fonts, icons and design assets

None vendored yet. `design/source/` is read-only reference material, not a dependency; its
licence terms are tracked in `design/source/INDEX.md`, not here.
