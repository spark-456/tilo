---
name: provider-error-base-class
description: tilo_providers adapters raise bare ProviderError (base) for malformed bodies/stream chunks/missing env; router code catching only the 4 subtypes lets it escape raw
metadata:
  type: project
---

Adapters (openai_compat_adapter.py, google_adapter.py) raise the *base* `ProviderError` for malformed response bodies, mid-stream bad chunks, bad tool-call JSON and missing api_key_env (P0-05 fix d0b6266). Only 429/5xx/4xx/safety map to the four subtypes.

**Why:** P0-06 router (2026-09-25) caught only Quota/Retryable/Request/Safety; a bare ProviderError escaped with no call record and no fallback, contradicting the P0-05 security hand-over. Tests only scripted the four subtypes plus RuntimeError, so it passed green.

**How to apply:** In any router/harness review, probe with `ProviderError("malformed")` from the primary (run a scratch test with `-p conftest -o pythonpath=tests`). Also check stream()/embed() paths and whether attempts survive RouterExhaustedError/RequestError.
