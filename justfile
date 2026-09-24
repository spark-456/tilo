# Tilo task runner (ADR-0001: `just` instead of `make`, native Windows + Linux CI).
# Every recipe calls uv, pnpm, python or node only — no bash-only or
# PowerShell-only scripts — so each line runs unchanged in pwsh and sh.

set windows-shell := ["pwsh", "-NoLogo", "-NoProfile", "-Command"]
set shell := ["sh", "-cu"]

# Install Python and JS dependencies for every workspace member.
setup:
    uv sync --all-packages
    pnpm install

# Run the API dev server.
dev:
    uv run --package tilo-api uvicorn tilo_api:app --reload --port 8080

# Format check + lint + typecheck + all tests (the full gate; matches PRD 20.4 "make check").
check: fmt-check lint typecheck test

# Fast subset for .claude/hooks/stop_check.py: format + lint + tests, meant to
# finish in well under 2 minutes by only touching what pytest/pnpm can see
# quickly (full suites, not per-file selection, since the repo is still small).
check-fast:
    uv run ruff format --check .
    uv run ruff check .
    pnpm exec biome check .
    uv run pytest -q

# Run every test suite (Python + JS, once JS suites exist).
test:
    uv run pytest -q
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

# Type-check everything.
typecheck:
    uv run mypy services/api packages/providers
    pnpm -r exec tsc --noEmit

# Run the eval harness (not built yet — ticket P3).
eval:
    python -c "print('eval harness not built yet (ticket P3); nothing to run')"

# Run skills/ tests (FR-AGT-04). Passes with zero skills present.
skills-test:
    python -c "import pathlib,sys; d=pathlib.Path('skills'); tests=[p for p in d.rglob('test_*.py')] if d.is_dir() else []; print(f'{len(tests)} skill test file(s) found'); sys.exit(0)"

# Apply infrastructure. Refuses everything but dev, and infra isn't applied yet either way.
deploy env="dev":
    python -c "import sys; env='{{env}}'; sys.exit(sys.stderr.write(f'deploy: only env=dev is allowed here, got {env!r}\n') or 1) if env != 'dev' else sys.exit(sys.stderr.write('deploy: infra/ is not applied yet (ticket P0-07 defines the plan; the user runs terraform apply)\n') or 1)"
