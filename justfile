# Tilo task runner (ADR-0001: `just` instead of `make`, native Windows + Linux CI).
# Every recipe calls uv, pnpm, python or node only — no bash-only or
# PowerShell-only scripts — so each line runs unchanged in pwsh and sh.

set windows-shell := ["pwsh", "-NoLogo", "-NoProfile", "-Command"]
set shell := ["sh", "-cu"]

# Install Python and JS dependencies for every workspace member, and install
# the pre-commit git hook so the local secret scan / lint hooks run on commit.
setup:
    uv sync --all-packages --locked
    pnpm install
    uv run pre-commit install

# Run the web dev server (`just dev-api` in a second terminal runs the API).
dev:
    pnpm --filter @tilo/web run dev

dev-api:
    uv run --package tilo-api python -m tilo_api

# CP2 browser walk on the real dev API (fake providers, no credentials, no live mode). Starts tilo-api
# on 127.0.0.1:8080 and its own Vite on TILO_CP2_PORT (default 5391); local only, CI never runs it.
e2e-cp2:
    node apps/web/scripts/e2e-cp2.mjs

# Park pixel-parity harness (WEB-PARITY, dev/test only, local): design reference vs our /park pages, report in
# apps/web/parity-report/. `just parity team` or `just parity team,profile` (default: all pages). Own ports
# TILO_PARITY_PORT (5395) and TILO_PARITY_REF_PORT (5396). Reports diffs; never fails on one.
parity pages="":
    node apps/web/scripts/parity.mjs {{pages}}

# Whole-stack system test (tests/system): starts the real tilo-api (dev mode, fake providers) and the other
# services as processes and drives them over HTTP; about 3 minutes, port 8080. Docs: docs/system-test.md.
system-test:
    uv run pytest tests/system -q -p no:cacheprovider

# Regenerate apps/web design tokens from design/tokens.json (drift-tested).
tokens:
    node apps/web/scripts/generate-tokens.mjs

# Format check + lint + typecheck + all tests (the full gate; matches PRD 20.4 "make check").
# contracts-check runs first so CI fails on contract drift (FR-WLD-02).
check: contracts-check fmt-check lint typecheck test

# Regenerate Python (packages/contracts-py) and TypeScript (packages/contracts-ts) types
# from contracts/*.schema.json (ADR-0002).
contracts-gen:
    uv run python scripts/contracts_codegen.py gen

# Validate every schema and fixture, regenerate into a temp dir, fail on any difference.
contracts-check:
    uv run python scripts/contracts_codegen.py check

# Fast subset for .claude/hooks/stop_check.py: format + lint + tests, meant to
# finish in well under 2 minutes by only touching what pytest/pnpm can see
# quickly (full suites, not per-file selection, since the repo is still small).
check-fast:
    uv run ruff format --check .
    uv run ruff check .
    pnpm exec biome check .
    uv run pytest -q -m "not emulator and not system"

# Run every test suite (Python + JS, once JS suites exist). Emulator-marked tests
# (services/harness, P0-09) need Java + firebase-tools and run separately in CI
# (see .github/workflows/ci.yml) and with `uv run pytest services/harness/tests -m emulator`.
test:
    uv run pytest -q -m "not emulator and not system"
    pnpm -r run test

# Format everything in place.
fmt:
    uv run ruff format .
    pnpm exec biome format --write .

fmt-check:
    uv run ruff format --check .
    pnpm exec biome format .

# Lint everything.
lint:
    uv run ruff check .
    pnpm exec biome lint .
    uv run python scripts/lint_model_ids.py

# Type-check everything.
typecheck:
    uv run mypy services/api/src services/harness/src services/sandbox-web/src packages/providers packages/contracts-py packages/policy/src packages/metering packages/planning/src evals/src services/connectors/src packages/archive/src packages/memory/src services/render/src services/channels/src services/browser/src packages/people/src packages/logging/src
    pnpm -r exec tsc --noEmit

# Validate the dev Terraform without a backend or credentials (EFF-05c). Downloads providers, changes nothing in the cloud.
# Run it before the apply (docs/deploy-dev.md); needs the terraform binary on PATH.
tf-validate:
    terraform -chdir=infra/envs/dev init -backend=false -input=false
    terraform -chdir=infra/envs/dev validate

# Start the Firestore emulator and run the harness skeleton against it (P0-09).
harness-skeleton:
    uv run --package tilo-harness python -m tilo_harness.skeleton --world w_harness_skeleton --run r_harness_skeleton

# Replay the eval set (no paid calls) into the git-ignored evals/results.local.md (evals/results.md is the committed pass record); exit 0 all passed, 1 a case failed, 2 error, 3 stopped at the credit cap (EFF-07).
eval:
    uv run python -m tilo_evals run --pass full --results-md evals/results.local.md

# EV-01..EV-15 metrics report from the replay set and the bank on fakes into the git-ignored evals/metrics.local.md; no paid calls; exit 2 if LIVE, K_SERVICE or CLOUD_RUN_JOB is set.
eval-metrics:
    uv run python -m tilo_evals metrics

# PL-05 conformance suite -> config/conformance/<profile>.json (replay by default; a miss fails)
conformance:
    uv run python -m tilo_providers.conformance

# PL-02 live Vertex smoke: one capped call per role. Refuses unless the user sets the live switch; `just vertex-smoke --replay` is free.
vertex-smoke *args:
    uv run python packages/providers/scripts/live_vertex_smoke.py {{args}}

# PL-02 schema probe: the exact Director brief request (small cap) and one variant per suspect field removed, then seven tiny Director-profile calls (no schema, json mode, sanitized/raw schema, thinking) to find what Vertex refuses. Refuses unless the user sets the live switch; `just vertex-probe-schema --dry-run` is free.
vertex-probe-schema *args:
    uv run python packages/providers/scripts/live_vertex_probe_schema.py {{args}}

# PL-LIVE-E2E (#340): one bank case through the real pipeline. Live only when the user sets LIVE=1; `--dry-run` and `--replay` are free.
live-e2e *args:
    uv run python evals/scripts/live_e2e.py {{args}}

# PL-LIVE-E2E: one real end-to-end run on a typed topic, screened by the safety role (Model Armor) first. The topic is
# typed at the prompt (`live-run`) or read from a file (`live-run-file <path>`): it never passes through a shell. Flags
# only: --dry-run --auto-answer --auto-approve-t1t2 --max-credits N. Live switch as live-e2e. docs/live-e2e.md.
live-run *flags:
    uv run python evals/scripts/live_run.py --topic-stdin {{ if flags =~ '^[-a-z0-9.= ]*$' { flags } else { error("live-run takes flags only; type the topic at the prompt or use live-run-file") } }}

live-run-file path *flags:
    uv run python evals/scripts/live_run.py --topic-file {{ if path =~ "['\u{2018}\u{2019}\u{201A}\u{201B}]" { error("live-run-file: rename a path that holds a single quote") } else { quote(path) } }} {{ if flags =~ '^[-a-z0-9.= ]*$' { flags } else { error("live-run-file takes flags only after the path") } }}

# Run skills/ tests (FR-AGT-04). Actually runs pytest so a real failing skill
# test fails this gate; pytest's exit code 5 ("no tests collected") is treated
# as success so the recipe still passes with zero skills present.
skills-test:
    python -c "import subprocess,sys; r=subprocess.run(['uv','run','pytest','skills']); sys.exit(0 if r.returncode in (0, 5) else r.returncode)"

# Apply infrastructure. Refuses everything but dev, and infra isn't applied yet
# either way. Usage: `just deploy dev` (an `env=dev`-style prefix is stripped
# too, so the older documented form keeps working).
deploy env="dev":
    python -c "import sys; env='{{env}}'; env=env[4:] if env.startswith('env=') else env; sys.exit(sys.stderr.write(f'deploy: only env=dev is allowed here, got {env!r}\n') or 1) if env != 'dev' else sys.exit(sys.stderr.write('deploy: infra/ is not applied yet (ticket P0-07 defines the plan; the user runs terraform apply)\n') or 1)"

# Dispatch the tilo-dev deploy workflow (P0-07a) on main: it builds the images, swaps them on Cloud Run and
# smoke-tests. Refuses everything but dev; needs `gh` signed in. Steps and variables: docs/deploy-dev.md.
deploy-dev env="dev":
    python -c "import sys; env='{{env}}'; env=env[4:] if env.startswith('env=') else env; sys.exit(sys.stderr.write(f'deploy-dev: only env=dev is allowed, got {env!r}\n') or 1) if env != 'dev' else None"
    gh workflow run deploy-dev.yml --ref main

# Deploy the tilo-dev services with Google Cloud Build instead of GitHub Actions minutes (P0-07f): uploads the repo
# (.gcloudignore allowlist), builds the images, pushes them to Artifact Registry and swaps them on Cloud Run by
# digest (cloudbuild.yaml, run as the tilo-cloudbuild service account; source goes to the Terraform-managed regional
# staging bucket, not the auto-created US one). Usage: `just deploy-dev-cloudbuild api`, then
# `just deploy-dev-cloudbuild`. Pinned to the dev project like `deploy-web`: no parameter can change it. `env` must
# be dev and `service` must be all or one of the seven names; both are checked by just itself (error()) before any
# shell runs, so nothing in them can reach a shell or gcloud. Needs `gcloud auth login` (docs/deploy-dev.md).
deploy-dev-cloudbuild service="all" env="dev":
    python -c "print('deploy-dev-cloudbuild: env and service accepted')" {{ if env != 'dev' { error('deploy-dev-cloudbuild: only env=dev is allowed, got ' + env) } else { '' } }} {{ if service =~ '^(all|api|harness|channels|connectors|browser|render|sandbox-web)$' { '' } else { error('deploy-dev-cloudbuild: service must be all or one of api, harness, channels, connectors, browser, render, sandbox-web, got ' + service) } }}
    gcloud builds submit --config cloudbuild.yaml --project essential-wares-510320-f0 --substitutions "_SERVICE={{service}}" --region asia-southeast1 --gcs-source-staging-dir gs://essential-wares-510320-f0-cloudbuild-staging/source .

# Build and push the nightly eval job image on Cloud Build (EFF-05b, evals/cloudbuild.yaml): run it before the apply
# that creates the Cloud Run job tilo-eval-nightly. Pinned to the dev project; takes no parameter. Needs `gcloud auth login`.
build-evals-image:
    gcloud builds submit --config evals/cloudbuild.yaml --ignore-file evals/cloudbuild.gcloudignore --project essential-wares-510320-f0 --region asia-southeast1 --gcs-source-staging-dir gs://essential-wares-510320-f0-cloudbuild-staging/source .

# Build the web app and deploy it to Firebase Hosting on the tilo-dev project (P0-07c). The build is given an empty
# VITE_TILO_API_URL, so the deployed app runs the fixture / replay world with no backend. Pinned to the dev project:
# no parameter, no other project, never tilo-demo. Needs your own `firebase login` first (the CI deployer has no
# Firebase role). Steps and the resulting URL: docs/deploy-dev.md. scripts/web_build_env.py also reads the web app's
# VITE_FIREBASE_* config (SEC-10 App Check) into the build environment; it writes nothing to disk.
deploy-web:
    python scripts/web_build_env.py pnpm --filter @tilo/web run build
    pnpm exec firebase deploy --only hosting --project essential-wares-510320-f0
