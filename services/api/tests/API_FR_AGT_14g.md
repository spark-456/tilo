# FR-AGT-14g interface (a credential or network outage of Cloud Tasks stops the tick, like 14f)

Follow-up to FR-AGT-14f (issue #502, the security reviewer's follow-up on PR #579). Builds on `API_FR_AGT_14f.md`; no
contract change, no new route, no Terraform change. Decisions: BQ-AGT14-7. Tests:
`test_FR_AGT_14g_credential_outage.py` (fakes only: `FakeTasksClient` from `_fr_agt_14_lib.py`, a `requests.Session`-
shaped session for the real `CloudTasksRestClient`, and google-auth's real `AuthorizedSession` over a fake credential
and a fake transport adapter; every fake raises the real exception classes; no network).

Why: a revoked or broken metadata credential surfaces as `google.auth.exceptions.RefreshError`, not as an HTTP 401, and a
network failure as `google.auth.exceptions.TransportError` or `requests` `Timeout` / `ConnectionError`. Before 14g these
were counted against each schedule (`start_failed`), so a credential or network outage disabled every schedule after
`MAX_FAILURES` = 8 ticks, each answering 200.

## Fan-out (the Scheduler's call of `POST /internal/schedules/tick`)

1. **These errors are service-wide.** When an enqueue raises one of them (from the session, or from the credential
   refresh the session makes first), whichever `TasksClient` raised it, the tick behaves exactly as 14f does for
   `tasks_unavailable`: no further enqueue call that tick; the slot and every later due slot stay due (no failure, no
   backoff, `next_due` unmoved, `last_error` unset, claim released); slots handed over earlier in the tick stay
   completed and are not handed over again.

   | Raised during enqueue (classified by the raised type; a subclass counts) | Code | Answer |
   |---|---|---|
   | `google.auth.exceptions.RefreshError` | `tasks_credential` | `503 {"detail": "tasks_credential"}` |
   | `google.auth.exceptions.TransportError`, `requests.exceptions.Timeout`, `requests.exceptions.ConnectionError` | `tasks_transport` | `503 {"detail": "tasks_transport"}` |

   A `ConnectTimeout` (both a `Timeout` and a `ConnectionError`) is `tasks_transport`. A `RefreshError` caused by a
   transport failure (google-auth's metadata credential wraps one) is `tasks_credential`: the raised type decides.
2. **The body is fixed** (the table above): never the exception's text, a URL, a token, a queue or an account.
3. **One ERROR line per stopped tick** on a `tilo_api.*` logger, naming the code. It may name the exception's type
   (`RefreshError`), nothing more: no exception text, no traceback (`exc_info` unset), no token, task name, queue,
   URL, account email, schedule or owner id; any `%` argument is an int or an identifier-like name.
4. **No double start after recovery.** The first tick after the outage hands every due slot over once; a task the
   outage hid (created by Cloud Tasks, its reply lost to a read timeout) answers ALREADY_EXISTS on the retry and counts
   as handed over, so no slot is created twice (deterministic `task_name`).

## What still counts per schedule (unchanged, now pinned)

An HTTP answer from Cloud Tasks other than 2xx, ALREADY_EXISTS and 401/403/404 (so 400, 429 RESOURCE_EXHAUSTED, 409
ABORTED, 500, 502, 503, 504) and any other exception (`RuntimeError`, `ValueError`, ...) is counted against that
schedule (`failures` + 1, backoff set) and the tick goes on: 200 `{"fired": n}`, no ERROR line naming a `tasks_` code.
Why (BQ-AGT14-7 b): Cloud Tasks answered, so credentials and the network work; such an answer can be one call's, and the
per-schedule backoff (2 min doubling, at most 24 h) already spaces the retries.

## Unchanged

14e and 14f behaviour and tests (`tasks_unavailable` for 401/403/404, replay-only, nothing due, the Tasks-mode
delivery). A Tasks client that cannot be built at all (`google.auth.default()` raising) stays 14e's fixed 5xx.
