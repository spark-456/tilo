# tilo-connectors

The only service that holds a person's Google OAuth grant. It runs the OAuth consent flow, keeps tokens
envelope-encrypted, and performs Gmail, Drive and Calendar calls on behalf of `tilo-api` once policy and a person have
approved them. It runs as a single instance.

## Routes

Every route is `POST /internal/...` and accepts exactly one caller: a Google ID token for audience
`TILO_CONNECTORS_AUDIENCE` from the account `TILO_MEETING_HOST_CALLER` (the `tilo-api` service account). Any other
account gets 403, `tilo-harness` included; unset configuration gives 503; bodies are capped at 64 KiB.

| Group | Routes |
| --- | --- |
| Connections | `/connections/start`, `/connections/callback`, `/connections/disconnect`, `/connections/views` |
| Writes | `/side-effects/execute` (Gmail, Drive and Calendar outbox entries) |
| Reads | `/workspace/read` (`search_email`, `read_email`, `read_events`, `list_files`, `read_file`) |
| Meeting host | `/meeting-host/send`, `/meeting-host/status`, `/meeting-host/disconnect`, `/meeting-host/join` |

The routes people use (`/v1/connectors/*`, `/v1/meeting-host/*`) live in `tilo-api`, which forwards here.

## What the adapters can do

| Connector | Reads | Writes |
| --- | --- | --- |
| Gmail (`gmail.readonly`, `compose`, `send`) | list and search threads and messages, labels, history, watch | `create_draft`, `send_email` (new mail or a threaded reply; attachments up to 25 MiB, blocked file types) |
| Drive (`drive.file`) | metadata, folder listing, search, download, read text | `save_file`, `save_as_google_file` (a PPTX, DOCX or XLSX from `tilo-render` converted to a native Google file), only into an unshared app-created "Tilo" folder |
| Calendar (`calendar.readonly`, `calendar.events.owned`) | `list_events` (sync token), `list_window` (up to 31 days) | `create_event` (no guests), `create_event_with_guests` (T3, up to 50), primary calendar only |
| Meeting host | `join_link` | `create_meeting_event` (T3, on the meeting bot's own account) |

Not implemented: free/busy, event update or delete, send-as, label changes, and the Docs, Sheets and Slides APIs.
No MCP server can connect (`config/mcp.yaml` has `servers: []`); Lovable and Canva are held and are described in
[docs/connectors/README.md](../../docs/connectors/README.md).

## Outbox and tiers

Every write is an outbox entry (`queued`, `scheduled`, `sending`, `sent`, `cancelled`, `failed`). The risk tier comes
from `config/autonomy.yaml` and an unlisted action is T3; T3 runs only at autonomy level L1 and only with a person's
recorded `approval.resolved`. Entries are idempotent: create-if-absent on world plus idempotency key, and each adapter
looks for its earlier attempt by a marker (a Gmail Message-ID, Drive `appProperties`, a Calendar event id) before
sending again. `/side-effects/execute` checks the item hash, the tier against the table and that the grant predates the
approval. An outcome is `sent`, `refused`, `retry` or `possibly_sent`; an uncertain send is never presented as sent. The
durable outbox store lives in `tilo-api` (`outbox_firestore.py`); this service builds an in-memory outbox per call.

## Tokens and live mode

Grants are stored in the separate `tilo-tokens` Firestore database (`token_grants/{user}/connectors/{connector}`), each
sealed with its own AES-GCM data key wrapped by the Cloud KMS key `oauth-tokens` (`tokens.py`); that database denies all
client access. OAuth consent uses PKCE (S256). The OAuth client id and secret are Secret Manager values surfaced as
`GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`.

Live calls need the owner's switch: `LIVE=1` plus `TILO_TOKEN_STORE=firestore`, `TILO_FIRESTORE_PROJECT`,
`TILO_TOKEN_DATABASE`, `TILO_KMS_KEY` and the OAuth client. Otherwise the routes answer 503 `not_configured`, and tests
use fakes and recorded transports. See [docs/deploy-dev.md](../../docs/deploy-dev.md) ("Live connectors").

## Key modules

`app.py`, `host_routes.py`, `host_join.py`, `host_auth.py`, `host_broker.py`, `tokens.py`, `consent.py`, `outbox.py`,
`side_effect_execute.py`, `workspace_read.py`, `live.py` (HTTP transport limited to Google hosts), `adapters/`
(`gmail`, `drive`, `calendar`, `calendar_write`, `meeting_host`), `registry.py`.

## Tests

```sh
uv run pytest services/connectors/tests -q
```

`scripts/live_gmail_smoke.py` and `scripts/live_meeting_host_smoke.py` are owner-run live checks. See
[CLAUDE.md](CLAUDE.md) for the requirement IDs and local rules.
