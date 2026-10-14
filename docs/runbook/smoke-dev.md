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

## Merge lane: after every release

Keep the `BUNDLE-SHA256` line from the previous successful release. After the authorized deployment,
save a fresh service description (PowerShell example; read only):

```powershell
gcloud run services describe tilo-api --project essential-wares-510320-f0 --region asia-southeast1 --format=json | Set-Content -Encoding utf8 traffic.json
just smoke-dev-release <api-url> <new-revision-name> traffic.json <previous-bundle-sha256>
```

Use the actual URL and exact expected new revision. The snapshot must name that revision as latest ready,
assign it all 100 percent of traffic, and contain exactly one tagged URL for it. The smoke GETs `/healthz`
at that tagged URL, separately from the service URL, and compares a stable SHA256 of all downloaded JS
URLs and contents with the previous release. All eight PASS lines are required; any FAIL exits 1.
The snapshot is evidence captured by the merge lane, not a live control-plane query by this script.
If there is no revision tag, report the missing prerequisite to the release owner; this smoke creates none.
If only the API changed and the frontend bundle did not, the bundle check correctly fails: record that
release disposition explicitly instead of inventing a different baseline. The first baseline can be captured
with 64 zeroes as the previous hash, but that bootstrap run does not prove a change from a prior release.
Save the new hash only after the release checks pass. No token, deployment, traffic edit or model call is made.
