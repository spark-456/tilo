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
Ticket CHN-WIRE-1 makes `tilo-channels` depend on the in-workspace `tilo-policy` (`check_entry` before an L1/T3 Send); not external, no new licence.
Ticket P0-05 adds two direct runtime dependencies (`packages/providers/pyproject.toml`):

| Dependency | Licence | Source |
| --- | --- | --- |
| google-genai (`tilo_providers.google_adapter`, PRD 6.4/6.5) | Apache-2.0 | https://pypi.org/project/google-genai/ |
| httpx (`tilo_providers.openai_compat_adapter`, PL-02; already a root dev dependency, above) | BSD-3-Clause | https://pypi.org/project/httpx/ |

Ticket FR-INT-02 (Model Armor adapter, `tilo_providers.model_armor_adapter`) declares `google-auth[requests]` directly
(both already installed through `google-genai`):

| Dependency | Licence | Source |
| --- | --- | --- |
| google-auth (user ADC token, `google.auth.default`) | Apache-2.0 | https://pypi.org/project/google-auth/ |
| requests (`google.auth.transport.requests`, via the `requests` extra) | Apache-2.0 | https://pypi.org/project/requests/ |

`google.genai.Client(vertexai=True, ...)` is only ever constructed under `LIVE=1`
(`tilo_providers.factory`); dev/CI tests fake the `google.genai` import path at the
`sys.modules` boundary and never install real credentials (EFF-01).

## Python (`packages/people`)

`tilo-people` (PPL-10) depends on the in-workspace `tilo-policy` (schema checks; not external) and adds
one runtime dependency, the IANA zone database for `zoneinfo` (Windows and slim images ship none):

| Dependency | Licence | Source |
| --- | --- | --- |
| tzdata | Apache-2.0 | https://pypi.org/project/tzdata/ |

## Python (`services/connectors`)

`tilo-connectors` declares `jsonschema` and `referencing` as runtime dependencies (ticket ST-2 /
FR-AGT-11), both already listed above (MIT); and the in-workspace `tilo-policy` (not external).
FR-CON-01 adds `pyyaml` (MIT, already listed above) as a direct dependency for the connector config
loader. No new licence. FR-CON-02 adds `cryptography` for AES-GCM envelope encryption of OAuth tokens:

| Dependency | Licence | Source |
| --- | --- | --- |
| cryptography (`tilo_connectors.tokens`, FR-CON-02) | Apache-2.0 OR BSD-3-Clause | https://pypi.org/project/cryptography/ |
| tzdata (`tilo_connectors.calendar_sync`, FR-CAL-08: the IANA zone database `zoneinfo` needs on Windows) | Apache-2.0 | https://pypi.org/project/tzdata/ |

FR-CON-10 (`tilo_connectors.provenance`) adds the in-workspace `tilo-archive` and `tilo-contracts`
(not external). No new licence.

## Python (`services/browser`)

`tilo-browser` (FR-CON-07/08) adds one direct runtime dependency, already in `uv.lock` through `httpx`:

| Dependency | Licence | Source |
| --- | --- | --- |
| idna (UTS 46 non-transitional host normalisation for the egress allowlist, as browsers do) | BSD-3-Clause | https://pypi.org/project/idna/ |

Its tests use `jsonschema` and `referencing` from the root dev group (above).

## Python (`packages/planning`)

`tilo-planning` (FR-INT-01/02) depends only on the in-workspace `tilo-contracts` and
`tilo-providers` (not external); `tilo-api` now depends on the in-workspace `tilo-planning`, and
(CL-INT-2) on the in-workspace `tilo-policy`, `tilo-harness` and `tilo-connectors`, and (CL-INT-5d) on the in-workspace `tilo-metering`, and (CL-INT-6) on the in-workspace `tilo-world` (the layout solver; standard library only, no external dependency), and (ADR-0018 T4, FR-AGT-02) on the in-workspace `tilo-archive` and `tilo-memory` (not external). No new licence.

## Python (`services/render`)

| Dependency | Licence | Source |
| --- | --- | --- |
| python-pptx | MIT | https://pypi.org/project/python-pptx/ |
| reportlab | BSD | https://pypi.org/project/reportlab/ |
| pypdf | BSD-3-Clause | https://pypi.org/project/pypdf/ |

`tilo-render` (AGR-01/02/03 / FR-CON-09) also uses `pydantic` (already listed under `packages/contracts-py`, MIT) and `pyyaml` (already listed under the root dev dependency group, MIT).

## JavaScript / TypeScript (root `package.json` and `apps/web`, `pnpm`-managed)

| Dependency | Licence | Source |
| --- | --- | --- |
| @biomejs/biome | MIT | https://www.npmjs.com/package/@biomejs/biome |
| firebase-tools (runs the Firestore emulator for `services/harness`, P0-09; also an `apps/web` devDependency at the same pinned 15.31.0 for `just deploy-web`, P0-07c) | MIT | https://www.npmjs.com/package/firebase-tools |
| typescript | Apache-2.0 | https://www.npmjs.com/package/typescript |
| react, react-dom, pixi.js, vite, @vitejs/plugin-react, vitest, @types/node, @types/react, @types/react-dom | MIT | https://www.npmjs.com/ |
| vite 6.4.x (#69, replaces 5.4.x; pulls esbuild 0.25, rollup, fdir, tinyglobby, all MIT; no licence change) | MIT | https://www.npmjs.com/package/vite |
| @playwright/test | Apache-2.0 | https://www.npmjs.com/package/@playwright/test |
| @axe-core/playwright | MPL-2.0 | https://www.npmjs.com/package/@axe-core/playwright |
| @fontsource/nunito, @fontsource/nunito-sans, @fontsource/jetbrains-mono | MIT; fonts Nunito, Nunito Sans, JetBrains Mono are OFL-1.1 | https://fonts.google.com/ |
| fast-check (property tests, ticket P0-08b-player, FR-WLD-04) | MIT | https://www.npmjs.com/package/fast-check |
| happy-dom (DOM for React component unit tests, AGW-01; dev only) | MIT | https://www.npmjs.com/package/happy-dom |
| ajv (JSON Schema validator for the PPL-40a plate reducer test; dev only) | MIT | https://www.npmjs.com/package/ajv |
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

## tilo-dev deploy: actions and container base images (P0-07a)

Every action is pinned to a full commit SHA in `.github/workflows/deploy-dev.yml` (tag in the comment).

| Component | Pinned ref | Licence | Source |
| --- | --- | --- | --- |
| actions/checkout (deploy-dev) | v6.1.0 (`d23441a48e51`) | MIT | https://github.com/actions/checkout |
| google-github-actions/auth (Workload Identity Federation) | v3.0.0 (`7c6bc770dae8`) | Apache-2.0 | https://github.com/google-github-actions/auth |
| google-github-actions/setup-gcloud | v3.0.1 (`aa5489c8933f`) | Apache-2.0 | https://github.com/google-github-actions/setup-gcloud |
| ghcr.io/astral-sh/uv (builder stage of every `services/<svc>/Dockerfile`) | 0.12.18-python3.12-trixie-slim | MIT or Apache-2.0 | https://github.com/astral-sh/uv |
| python (runtime stage; Docker Official Image, Debian trixie slim) | 3.12.15-slim-trixie | PSF-2.0 (Python); Debian packages under their own licences | https://hub.docker.com/_/python |

`fastapi` (MIT) and `uvicorn` (BSD-3-Clause) are now direct dependencies of every service so each image runs
`uvicorn <module>:app` (a `/healthz` ASGI app in `harness`, `channels`, `connectors`, `browser`, `render`).

## tilo-dev deploy on Cloud Build: builder images (P0-07f)

Pinned in `cloudbuild.yaml`. They run only inside Google Cloud Build; nothing from them is shipped in a Tilo image.

| Component | Pinned ref | Licence | Source |
| --- | --- | --- | --- |
| gcr.io/cloud-builders/docker (build and push the service images) | 20.10.24 | Apache-2.0 (the builder image; Docker Engine inside is Apache-2.0) | https://github.com/GoogleCloudPlatform/cloud-builders |
| gcr.io/google.com/cloudsdktool/cloud-sdk (service selection and `gcloud run services update`) | 587.0.0 | Apache-2.0 (Google Cloud CLI) | https://github.com/GoogleCloudPlatform/cloud-sdk-docker |

## Fonts, icons and design assets

None vendored yet. `design/source/` is read-only reference material, not a dependency; its
licence terms are tracked in `design/source/INDEX.md`, not here.

## Python (`packages/memory`)

`tilo-memory` declares `jsonschema` and `referencing` as runtime dependencies (FR-MEM-06 artifact store),
both already listed above (MIT). No new licence.
