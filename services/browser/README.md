# tilo-browser

An isolated headless Chromium (Playwright) that lets a run browse the web where a person can watch, plus a guarded
fetch for downloading files. It exists so a model never gets a raw network: every request, redirect and download is
checked by deterministic code first.

## What an agent can do

An agent drives a browser *session* with five actions: `navigate`, `click`, `type`, `scroll` and `extract`, up to 60
steps. Each click and type is bound to the digest of the element facts returned by the last `inspect`, so it acts on
what was inspected and nothing else. The service refuses secure (password-like) fields, commit-like buttons, form
submits, non-GET navigation and typed text that the masker would change; Enter works only inside a GET search field.
Tilo never types credentials: a login wall sets `login_required` in the response and the session stops there.

Frames are not streamed. Every response carries one base64 PNG, taken after secure fields and iframes are masked; if a
secure field cannot be masked the call fails closed with 409 `screenshot_unavailable`.

## Routes

All routes except health need a Google ID token whose audience matches `TILO_BROWSER_AUDIENCE` and whose verified email
is in `TILO_BROWSER_CALLERS` (comma-separated). A request without a bearer token gets 401; if either variable is unset
every authenticated route answers 403.

| Route | Purpose |
| --- | --- |
| `GET /health`, `/healthz` | liveness (public) |
| `POST /sessions` | start a session |
| `POST /sessions/{session}/act` | one action |
| `POST /sessions/{session}/inspect` | read the page's element facts |
| `DELETE /sessions/{session}` | end the session |
| `POST /fetch` | download a file (HTTPS GET, port 443 only) |

`POST /fetch` pins DNS so that every resolved address must be public, honours `robots.txt`, follows at most 5 redirects
(each re-checked), and caps 25 MiB per file, 10 files and 50 MB per unit, 512 KiB of HTML and a 60 s deadline. The file
type is decided by magic bytes, not by the server's header.

The caller in practice is `tilo-api` (`services/api/src/tilo_api/run_tools.py`, `TILO_BROWSER_URL`, ADR-0052).
Terraform names `tilo-harness` as the invoker; the allowed caller list in the environment is what the code enforces.

## Isolation

One Chromium context per session, downloads off, no cookies kept between sessions. Egress is decided in-process by
`egress.py` on every request and every redirect hop, against a deterministic allowlist; the only wider path is the assets
check, which lets images, CSS, fonts and media load from any public host. There is no proxy sidecar. A single worker
thread serialises browser calls. The service stores nothing durable: the fetch archive writes to a local directory.

## Key modules

`app.py` (routes and auth), `session.py` (`BrowserSessions`), `worker.py`, `playwright_engine.py`, `egress.py`,
`masking.py`, `login.py`, `fetch.py`.

## Tests

The tests use fakes only: no browser, no network.

```sh
uv run pytest services/browser -q
```

See [CLAUDE.md](CLAUDE.md) and [ADR-0052](../../docs/adr/0052-browser-session-rpc-and-visible-control.md).
