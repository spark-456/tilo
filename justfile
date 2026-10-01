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
    uv run --package tilo-api uvicorn tilo_api:app --reload --port 8080

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
    uv run pytest -q -m "not emulator"

# Run every test suite (Python + JS, once JS suites exist). Emulator-marked tests
# (services/harness, P0-09) need Java + firebase-tools and run separately in CI
# (see .github/workflows/ci.yml) and with `uv run pytest services/harness/tests -m emulator`.
test:
    uv run pytest -q -m "not emulator"
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
    uv run mypy services/api/src services/harness/src services/sandbox-web/src packages/providers packages/contracts-py packages/policy/src packages/metering packages/planning/src evals/src services/connectors/src packages/archive/src services/render/src
    pnpm -r exec tsc --noEmit

# Start the Firestore emulator and run the harness skeleton against it (P0-09).
harness-skeleton:
    uv run --package tilo-harness python -m tilo_harness.skeleton --world w_harness_skeleton --run r_harness_skeleton

# Run the eval harness (not built yet — ticket P3).
eval:
    python -c "print('eval harness not built yet (ticket P3); nothing to run')"

# PL-05 conformance suite -> config/conformance/<profile>.json (replay by default; a miss fails)
conformance:
    uv run python -m tilo_providers.conformance

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
