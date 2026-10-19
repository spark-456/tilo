# packages/logging — `tilo_logging`

## Purpose
Structured logs for every Tilo service (PRD 17.2, NFR-26): one JSON object per line on stdout, which Cloud Run ships
to Cloud Logging. Standard library only.

## Commands
- `uv run pytest -q tests/repo/test_NFR_26_structured_logs.py` and
  `uv run pytest -q services/harness/tests/test_NFR_26_harness_run_logs.py`; `just check` is the full gate.

## Contracts and config
- No events, no config. Keys: `severity`, `message`, `logger`, `run_id`, `world_id`,
  `logging.googleapis.com/trace` (Cloud Trace link), `exception` (only with `exc_info`).
- Defaults are pinned in the docstring of `tests/repo/test_NFR_26_structured_logs.py`; decisions in BQ-NFR26-1.

## Requirement IDs
- NFR-26 (structured-log half). The runbook is a separate ticket.

## Local rules
- `configure_logging` is the one public function; it replaces only its own handler, so it is idempotent and keeps
  pytest's handlers (caplog) on the root logger.
- Ids live in contextvars (`tilo_logging.context.bound`), so asyncio runs and threads never see each other's ids.
  An absent id is left out, never null. The trace id comes only from `X-Cloud-Trace-Context`.
- Never copy a header, token, cookie, e-mail address or `extra` field into a line: only the keys above.
