# ADR-0001: Native Windows development with `just` instead of `make`

- Status: Accepted (2026-09-25, user decision)
- Deciders: product owner, orchestrator

## Context
PRD 20.3 names one `make` entry point (`make dev`, `make check`, `make test`, `make eval`, `make deploy ENV=dev`). The team develops on native Windows 11 (no WSL), where `make` is not installed and bash-only scripts do not run. CI and Cloud Run are Linux. The repository lives in `C:\Users\josna\OneDrive\Desktop\Claude Projects\Tilo`, a OneDrive-redirected folder; the OneDrive client is disabled at sign-in, so the folder is not syncing.

## Decision
- The task runner is `just` (Casey.Just, CC0-1.0). Recipes mirror the PRD names: `just dev`, `just check`, `just check-fast`, `just test`, `just eval`, `just deploy env=dev`. Where the PRD or acceptance tests say `make <x>`, read `just <x>` (for example FR-AGT-04 `make skills-test` is `just skills-test`).
- Every recipe calls `uv`, `pnpm`, Python or Node. No bash-only or PowerShell-only scripts; helper scripts are Python (stdlib where possible) or Node.
- LF line endings everywhere via `.gitattributes`; `core.autocrlf=false` and `core.longpaths=true` in the repo.
- CI runs on Linux (`ubuntu-latest`) so platform drift shows up in CI.
- The repository stays in the OneDrive path at the user's request. OneDrive must stay off for this folder; push to a remote early once the user decides what is public.

## Consequences
- One more tool to install (`winget install Casey.Just`; CI installs it with a pinned action or binary).
- Slower dependency installs than on a Linux filesystem, most visible with several worktrees.
- If OneDrive is started, it will try to sync `.git`, `node_modules`, `.venv` and worktrees, which can lock files and corrupt worktrees. Moving to `C:\dev\tilo` later is a copy plus `git worktree prune`.
