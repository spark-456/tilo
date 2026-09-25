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
| uvicorn | BSD-3-Clause | https://pypi.org/project/uvicorn/ |

## Python (`packages/contracts-py`)

| Dependency | Licence | Source |
| --- | --- | --- |
| pydantic | MIT | https://pypi.org/project/pydantic/ |

## Python (`packages/providers`)

No new dependency was added for ticket P0-04 (`packages/providers/pyproject.toml` still
declared none of its own): `tilo_providers.config` uses `pydantic` (already listed under
`packages/contracts-py`, via the `tilo-contracts` workspace member it imports) and `pyyaml`
(already listed under the root dev dependency group); both are already installed into the
shared `uv` workspace venv by `uv sync --all-packages`.

Ticket P0-05 adds two direct runtime dependencies (`packages/providers/pyproject.toml`):

| Dependency | Licence | Source |
| --- | --- | --- |
| google-genai (`tilo_providers.google_adapter`, PRD 6.4/6.5) | Apache-2.0 | https://pypi.org/project/google-genai/ |
| httpx (`tilo_providers.openai_compat_adapter`, PL-02; already a root dev dependency, above) | BSD-3-Clause | https://pypi.org/project/httpx/ |

`google.genai.Client(vertexai=True, ...)` is only ever constructed under `LIVE=1`
(`tilo_providers.factory`); dev/CI tests fake the `google.genai` import path at the
`sys.modules` boundary and never install real credentials (EFF-01).

## JavaScript / TypeScript (root `package.json` devDependencies, `pnpm`-managed)

| Dependency | Licence | Source |
| --- | --- | --- |
| @biomejs/biome | MIT | https://www.npmjs.com/package/@biomejs/biome |
| typescript | Apache-2.0 | https://www.npmjs.com/package/typescript |

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
| pre-commit/pre-commit-hooks | v5.0.0 | MIT | https://github.com/pre-commit/pre-commit-hooks |

## Fonts, icons and design assets

None vendored yet. `design/source/` is read-only reference material, not a dependency; its
licence terms are tracked in `design/source/INDEX.md`, not here.
