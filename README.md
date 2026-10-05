# Tilo

_Skeleton — filled in as pillars land. See `docs/prd/tilo-prd-v2.md` for the full spec._

Tilo is an agentic work platform: people describe work, a Director plans it, agent teams run it,
and the work is shown as a living isometric world with Story and Trace lenses. People approve
from web, phone or email.

## Try it

_Skeleton — deployed link goes here once `apps/web` and `tilo-api` (P0-08+) are live._

## How to run

### Windows (native, no WSL — see `docs/adr/0001-native-windows-just-task-runner.md`)

```powershell
winget install Casey.Just
just setup   # uv sync + pnpm install
just dev
just check
```

### Linux / CI

```sh
just setup
just dev
just check
```

## Architecture

_Skeleton — see PRD section 6 (Architecture and the model provider layer) for the system diagram,
services table and Google Cloud service map._

## GenAI map

_Skeleton — which model, role and provider profile does each piece of work; see PRD section 6.4._

## Eval results

_Skeleton — populated from `evals/results.md` once the eval harness (P3) exists._

## Security notes

_Skeleton — see PRD section 16 (Security, privacy and safety) and `docs/licences.md`._

## Honest notes

_Skeleton — known gaps and limitations, updated as pillars land (PRD honesty rules, section 9.4)._

## License

Apache-2.0, see `LICENSE`.
