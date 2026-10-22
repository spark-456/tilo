# evals

The eval harness (`tilo_evals`, PRD 19). It replays recorded runs against deterministic checks, so it costs nothing and
needs no credentials.

| What | Where | Run |
| --- | --- | --- |
| 160 replay cases in eight groups: E-MAIL 50, E-CHN 30, E-HAND 20, E-ROUTE 20, E-RED 14, E-PLAN 10, E-RES 10, E-DOC 6 | `evals/cases/<group>/<id>.yaml` (schema `case.schema.json`) | `just eval` |
| 38-case generality bank: the real `tilo-api` in process from intake to delivery, only the Director scripted; it tests pipeline mechanics, not model judgement | `evals/bank/B-NNN.yaml`, pinned by `MANIFEST.sha256` | `uv run python -m tilo_evals bank` |
| One web-research replay case, E-RES-11 | `evals/web-cases/` | `uv run python -m tilo_evals.web_replay --replay` |
| EV-01 to EV-15 metrics report, with a latency table of Tilo's own overhead | | `just eval-metrics` |
| Nightly smoke pass through a batch job (Cloud Run job `tilo-eval-nightly`, Cloud Scheduler 19:00 UTC) | `evals/Dockerfile`, `evals/cloudbuild.yaml` | `just build-evals-image` builds the image |
| One bank case or one typed topic through the real pipeline | | `just live-e2e`, `just live-run` (live only when the owner sets `LIVE=1`) |

`just eval` writes `evals/results.local.md`, which is git-ignored. **There is no committed results file:**
`evals/results.md` is the intended official record (PRD 19.5) but is not in the repository, so no pass rate is claimed
anywhere in the documentation. Credit caps per pass kind are in `config/evals.yaml`; a pass that reaches its cap stops
and lists what it did not run (exit code 3). Exit codes: 0 all ran cases passed, 1 a case failed, 2 the pass could not
run, 3 stopped at the credit cap.

No model id appears here (rule PL-01); results name profiles taken from each event's own trace. Autorater checks are
reported as pending and never counted as passes. Tests for the harness itself: `uv run pytest evals/tests -q`. Details,
flags and rules are in [CLAUDE.md](CLAUDE.md) and [docs/live-e2e.md](../docs/live-e2e.md).
