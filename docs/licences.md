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

## Python (`services/api`)

| Dependency | Licence | Source |
| --- | --- | --- |
| fastapi | MIT | https://pypi.org/project/fastapi/ |
| uvicorn | BSD-3-Clause | https://pypi.org/project/uvicorn/ |

## Python (`packages/providers`)

No third-party runtime dependencies yet (empty scaffold; code lands in ticket P0-04).

## JavaScript / TypeScript (root `package.json` and `apps/web`, `pnpm`-managed)

| Dependency | Licence | Source |
| --- | --- | --- |
| @biomejs/biome | MIT | https://www.npmjs.com/package/@biomejs/biome |
| typescript | Apache-2.0 | https://www.npmjs.com/package/typescript |
| react, react-dom, pixi.js, vite, @vitejs/plugin-react, vitest, @types/node, @types/react, @types/react-dom | MIT | https://www.npmjs.com/ |
| @playwright/test | Apache-2.0 | https://www.npmjs.com/package/@playwright/test |
| @axe-core/playwright | MPL-2.0 | https://www.npmjs.com/package/@axe-core/playwright |
| @fontsource/nunito, @fontsource/nunito-sans, @fontsource/jetbrains-mono | MIT; fonts Nunito, Nunito Sans, JetBrains Mono are OFL-1.1 | https://fonts.google.com/ |

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
| astral-sh/ruff-pre-commit | v0.7.4 | MIT | https://github.com/astral-sh/ruff-pre-commit |

## Fonts, icons and design assets

None vendored yet. `design/source/` is read-only reference material, not a dependency; its
licence terms are tracked in `design/source/INDEX.md`, not here.
