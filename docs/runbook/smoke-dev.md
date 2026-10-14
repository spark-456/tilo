# Unsigned deployed smoke

Run from the repository root with Python and uv available on Windows, macOS or Linux:

```text
just smoke-dev https://tilo-api-123456789.asia-southeast1.run.app
```

Replace the example with the actual tilo-api URL. This mode ignores `TILO_SMOKE_ID_TOKEN`, sends no credentials or
cookies, follows no redirects and makes only GET and OPTIONS requests. No sign-in or model call is required.

The command prints exactly one PASS or FAIL line for each of five checks, and exits 1 if any fails:

| Check | Evidence |
| --- | --- |
| sign-in | Hosted HTML or its same-origin JavaScript contains Continue with Google |
| bundle-api | The downloaded JavaScript names exactly the supplied tilo-api base |
| healthz | GET /healthz returns 200 |
| cors-intake | OPTIONS /intake grants POST and the required headers to the hosting origin, returning 200 |
| plate-auth | GET /v1/plate without authentication returns exactly 401 |

The sign-in check inspects the shipped page and script text; it does not replace browser visual acceptance.
Hosted assets are bounded to 32 files and all response bodies together to 20 MiB; HTTP requests time out after 15 s.
The hosted origin is https://essential-wares-510320-f0.web.app. Foreign script origins fail the page checks.

The optional signed-in replay flow documented in deploy-dev.md remains available explicitly with
`uv run python scripts/smoke_dev.py <api-url>`; `just smoke-dev` always selects the unsigned checks above.
