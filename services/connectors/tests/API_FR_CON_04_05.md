# Gmail and Drive adapters — public API these tests pin (FR-CON-04, FR-CON-05)

Lane CL-REACH. Builds on the outbox (`API.md`, top half) and the token broker (`API.md`, "Token broker
and consent"). Tests: `test_FR_CON_04_*.py`, `test_FR_CON_05_*.py`; doubles in `_gapi_lib.py`;
hand-written recordings in `fixtures/http/`. Nothing here touches the network, a real account or `LIVE`:
the HTTP transport, the broker, the artifact source, the clock, `sleep` and `emit` are all injected.

Every test fails today with `ModuleNotFoundError: tilo_connectors.adapters` (or
`tilo_connectors.recording`), or, for the shipped-config tests, because `config/connectors.yaml`
does not exist yet.

## Shipped config

`config/connectors.yaml` (FR-CON-01's `load_registry` reads it) declares `gmail` and `google_drive`.

- `gmail`: the scopes of `contracts/fixtures/connector/valid/gmail.json` (read and search
  `gmail.readonly`, write `gmail.compose`, send `gmail.send`); actions `read_email`, `search_email`,
  `create_draft`, `send_email`. Never `https://mail.google.com/` or `gmail.modify`.
- `google_drive`: every declared capability's scopes are exactly `[drive.file]` (picker-based read and
  Tilo-created files only; PRD 12.2, 16.1 least privilege). Actions `read_file` (read), `list_files`
  (list), `save_file` (write, gate `approval`). Never `drive` or `drive.readonly`.
- Every action id that `config/autonomy.yaml` lists has that tier as its declared `risk_tier`.

## `tilo_connectors.adapters` (package `src/tilo_connectors/adapters/`)

Only modules here and `tokens.py` may call `access_token_for_adapter` (SEC-02, already pinned).

```python
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3/files"
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024  # total attachment bytes per message (Gmail's limit)
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024  # one Drive download
BLOCKED_ATTACHMENT_EXTENSIONS: frozenset[str]  # lower-case, with the dot; at least
#   .exe .bat .cmd .com .scr .pif .msi .js .jse .vbs .vbe .ps1 .jar .dll .cpl .hta .iso .lnk
MAX_ATTEMPTS = 3  # requests per HTTP call, the first one included


class TransportError(Exception):
    ...  # network failure or timeout: the request may or may not
    # have reached Google


class ApiResponse(Protocol):
    status_code: int
    headers: Mapping[str, str]  # header names lower-case
    content: bytes

    def json(self) -> Any: ...


class Transport(Protocol):
    def request(
        self,
        method: str,  # "GET" | "POST" | "PATCH"
        url: str,  # no query string; one of the three bases above + path
        *,
        params: Mapping[str, Any] | None = None,  # query; a value may be a list (labelIds)
        headers: Mapping[str, str] | None = None,  # carries "authorization": "Bearer <token>"
        json: Any = None,
        content: bytes | None = None,
    ) -> ApiResponse: ...


class AdapterError(Exception): ...  # base; its message never holds a token, a body or a full file name


class RateLimited(AdapterError):  # 429 still answered after the attempts, or Retry-After > 60 s
    retry_after_s: int


class ProviderUnavailable(AdapterError): ...  # 5xx or TransportError still after the attempts


class SideEffectRefused(AdapterError): ...  # final: the side effect can never succeed as written


class NotPicked(AdapterError): ...  # a Drive file outside the readable set


class FileTooLarge(AdapterError): ...  # a Drive download over the limit


class ArtifactSource(Protocol):  # P7's artifact store; tests pass a dict-backed double
    def get(self, artifact_id: str, version: int) -> Mapping[str, Any]: ...

    # {"kind": "email", "subject": str, "body_text": str}
    # {"kind": "file", "name": str, "mime_type": str, "content": bytes}


class InMemoryPicks:  # the files and folders a user picked in the Drive Picker
    def __init__(self) -> None: ...
    def add(self, user_id: str, ids: Iterable[str]) -> None: ...
    def picked(self, user_id: str) -> frozenset[str]: ...
```

Token errors are the broker's own types from `tilo_connectors.tokens` (`InsufficientScope`,
`ConnectionExpired`, `NotConnected`, `TokenRefreshFailed`), raised through unchanged.

### `GmailAdapter`

```python
class GmailAdapter:
    def __init__(
        self,
        *,
        declaration: Mapping[str, Any],  # the connector.schema.json entry (scopes, limits)
        broker: TokenBroker,
        transport: Transport,
        artifacts: ArtifactSource,
        owner_of: Callable[[str], str],  # world_id -> the user whose mailbox an outbox entry uses
        clock: Callable[[], str],
        emit: Callable[[dict], None],
        sleep: Callable[[float], None],  # the only way it waits; never time.sleep
        max_attempts: int = MAX_ATTEMPTS,
        max_attachment_bytes: int = MAX_ATTACHMENT_BYTES,
    ) -> None: ...

    id: str  # property: declaration["id"]

    def list_threads(self, user_id, *, label_ids=(), max_results=20, page_token=None) -> dict: ...
    def search_threads(self, user_id, query, *, max_results=20, page_token=None) -> dict: ...
    def get_thread(self, user_id, thread_id) -> dict: ...
    def get_message(self, user_id, message_id) -> dict: ...
    def list_labels(self, user_id) -> list[dict]: ...
    def execute_side_effect(self, entry: Mapping[str, Any], grant: Grant) -> dict: ...
```

Requests (Google's documented REST calls; recordings match on them):

| Call | Request |
| --- | --- |
| `list_threads` | `GET {GMAIL_API}/threads`, `labelIds`, `maxResults`, `pageToken` |
| `search_threads` | `GET {GMAIL_API}/threads`, `q` = the query unchanged, `maxResults`, `pageToken` |
| `get_thread` | `GET {GMAIL_API}/threads/{id}`, `format=full` |
| `get_message` | `GET {GMAIL_API}/messages/{id}`, `format=full` |
| `list_labels` | `GET {GMAIL_API}/labels` |
| draft | `POST {GMAIL_API}/drafts`, json `{"message": {"raw": <base64url MIME>, "threadId"?}}` |
| send | `POST {GMAIL_API}/messages/send`, json `{"raw": <base64url MIME>, "threadId"?}` |
| find an earlier attempt | `GET {GMAIL_API}/messages` or `GET {GMAIL_API}/drafts` with `q=rfc822msgid:<Message-ID>` |

Returns: `list_threads` / `search_threads` give `{"threads": [{"id", "snippet"}], "next_page_token":
str | None}`; `maxResults` sent is never above `declaration["limits"]["batch_size"]`. `get_thread`
gives `{"id", "messages": [message]}`. A message is `{"id", "thread_id", "from", "to": [str], "cc":
[str], "subject", "message_id", "label_ids": [str], "body_text", "attachments": [{"filename",
"mime_type", "size"}], "headers": {name: str}, "has_text_part": bool, "has_other_parts": bool, "untrusted": True}`: `body_text` is the text/plain part verbatim
(data, never stripped or acted on); `message_id` is the RFC 5322 `Message-ID` header. `headers` (BQ-278 n) holds
only `message-id`, `in-reply-to`, `references` and `authentication-results`, names lower-cased, the first
occurrence of a repeated name (Gmail writes its own Authentication-Results above any the sender wrote); a name the
message lacks is absent. `has_text_part` is True when a text/plain part with no filename exists (HTML-only: False, with
`body_text` ""); `has_other_parts` is True when any other non-multipart part without a filename exists (text/html, a second text/plain). `list_labels` gives
`[{"id", "name", "type"}]`.

Scopes: each call asks the broker for exactly the declared scopes of the capability it uses (read
calls `read`, `search_threads` `search`); a side effect asks for its capability's scopes (`write` for a
draft, `send` for a send) plus at most the `read` scopes (for the thread headers and the earlier-attempt
lookup), never anything undeclared.

### `DriveAdapter`

```python
class DriveAdapter:
    def __init__(
        self,
        *,
        declaration,
        broker,
        transport,
        artifacts,
        picks: InMemoryPicks,
        owner_of,
        clock,
        emit,
        sleep,
        max_attempts: int = MAX_ATTEMPTS,
        max_download_bytes: int = MAX_DOWNLOAD_BYTES,
    ) -> None: ...

    id: str

    def get_metadata(
        self, user_id, file_id
    ) -> dict: ...  # {"id", "name", "mime_type", "size": int | None, "parents": [str]}
    def list_folder(
        self, user_id, folder_id, *, page_token=None
    ) -> dict: ...  # {"files": [metadata], "next_page_token"}
    def download(self, user_id, file_id) -> bytes: ...
    def execute_side_effect(self, entry, grant) -> dict: ...  # {"id": file id, "folder_id": Tilo folder id}
```

Requests: metadata `GET {DRIVE_API}/files/{id}` (any `fields`); content `GET {DRIVE_API}/files/{id}`
with `alt=media`; listing and lookups `GET {DRIVE_API}/files` with `q` built from the clauses
`'<id>' in parents`, `mimeType = '...'`, `mimeType != '...'`, `name = '...'`, `trashed = false` and
`appProperties has { key='...' and value='...' }` joined by ` and `; folder creation `POST
{DRIVE_API}/files` (json metadata); upload `POST {DRIVE_UPLOAD_API}` with `uploadType=multipart` and a
`multipart/related` body (JSON metadata part, then the media part).

**Readable set (FR-CON-05).** A user's file is readable when its id is in `picks.picked(user_id)`, it
was listed by `list_folder` of a picked folder for that user, or this adapter created it (the Tilo
folder and saved files). `list_folder` needs a picked folder or the Tilo folder. Anything else raises
`NotPicked` before any request names that id. `download` reads the metadata first and raises
`FileTooLarge` without requesting the content when `size` > `max_download_bytes`. Every Drive call asks
the broker for the declared scopes of its capability (`read`, `list`, `write`).

## The one side-effect method (SEC-03)

`execute_side_effect` is the adapters' only side-effect method; `"execute_side_effect"` is in
`side_effects.SIDE_EFFECT_METHOD_NAMES`. Neither adapter has any other public method that writes, and
neither has an attribute named after a side-effecting action (`create_draft`, `send_email`,
`save_file`). Public methods are exactly the ones listed above (helpers are underscored).

- It first calls `grant.verify(entry["idempotency_key"])`: no valid Grant raises `MissingGrant`
  before the broker or the transport is touched.
- `Outbox.dispatch_due()` calls `adapter.execute_side_effect(<copy of the entry>, grant)` for an adapter
  that has the method (adapters without it keep the `send_reply` path). `SideEffectRefused` lands the
  entry in `failed` (final, nothing emitted); every other exception stays ambiguous as today (entry
  stays due, retried on the next `dispatch_due()`); `dispatch_due()` never raises for either.
- `entry["recipients"]`, `entry["attachments"]`, `entry["item"]` and `entry["destination"]` are the
  whole input; the user is `owner_of(entry["world_id"])`.

**Gmail** (`create_draft`, `send_email`; any other action is `SideEffectRefused`). `item` is an
`email` artifact. The MIME message has `To` = exactly the entry's recipients and no `Cc` or `Bcc`;
artifact text never adds a header (CR/LF in a subject is neutralised or the entry is refused). With
`destination` set, `threadId` = destination, `In-Reply-To` = the `Message-ID` of the thread's last
message, `References` = that message's `References` plus its `Message-ID`, and `Subject` = one `Re: `
before the thread's subject; the thread's `Reply-To` is ignored. With `destination` null, no `threadId`
and no `In-Reply-To`. Attachments are `file` artifacts: total bytes over `max_attachment_bytes` or a name
whose last extension is in `BLOCKED_ATTACHMENT_EXTENSIONS` (case-insensitive) is `SideEffectRefused`.

**Exactly once.** The `Message-ID` is a pure function of (`world_id`, `idempotency_key`): the same on
every retry and in every instance, different for another key. Before saving or sending, the adapter
looks for an earlier attempt by that `Message-ID` and never makes a second copy, so a lost response, a
crash or a second `tilo-connectors` instance never duplicates a draft or a send (OB-03, FR-CHN-13).

**Drive** (`save_file`; anything else `SideEffectRefused`). `item` is a `file` artifact. It is saved in
the Tilo folder: a folder named `Tilo` in the Drive root that this adapter created (found again, never
duplicated). `destination` null means the Tilo folder; any destination other than its id is
`SideEffectRefused`. The file name is data (never a path), and the saved file carries a marker derived
from (`world_id`, `idempotency_key`) so that a retry finds it and never uploads twice.

## Errors, retries and events

- A request answered 429, 500, 502, 503 or 504, or a `TransportError` on a GET, is retried, at most
  `max_attempts` requests per call. Waits go through `sleep` only: `Retry-After` seconds when given,
  otherwise a backoff; at most 60 s of waiting in one call. A `Retry-After` over 60 is not waited:
  `RateLimited` at once, with that `retry_after_s`. Exhausted: `RateLimited` (last answer 429) or
  `ProviderUnavailable`. Any other 4xx is one request and an `AdapterError`.
- Each 429 emits one part `{"type": "connection.rate_limited", "authz": None, "data": {"connector",
  "retry_after_s"}, "user_id"}`.
- A 401 makes the adapter get a fresh token from the broker (a forced refresh; the broker method is
  the builder's choice) and retry once. When the refresh is refused (`invalid_grant`) the broker's
  path runs: `ConnectionExpired` is raised, `connection.expired` is emitted once and
  `connection_state` is `"expired"`. A token close to expiry is refreshed by the broker as before.
- A missing scope raises `InsufficientScope` (its `missing` is what `ConsentService.scopes_needed`
  asks for), before any request; in the outbox the entry stays due until the person consents.
- Every emitted part whose type the event registry marks `side_effect: true` carries a valid `authz`
  (SEC-11); `data.transfer` out keeps the entry's `authz`.
- Untrusted content: email bodies, snippets, subjects and file names are returned as data and are
  never logged in full, never put in an exception message, and never cause a request beyond the read
  that fetched them.

## Record and replay (`tilo_connectors.recording`)

```python
RECORDING_FORMAT = "tilo.http-recording/1"
REDACTED = "REDACTED"

class ReplayMiss(Exception): ...          # no unused recorded interaction matches, or no bearer header

class ReplayTransport:                    # a Transport; never opens a socket
    def __init__(self, recording: Mapping[str, Any] | str | os.PathLike[str]) -> None: ...
    def request(self, method, url, *, params=None, headers=None, json=None, content=None) -> ApiResponse: ...
    def unused(self) -> list[dict]: ...   # interactions not served yet

class RecordingTransport:                 # wraps a Transport, keeps scrubbed interactions
    def __init__(self, inner: Transport, *, connector: str) -> None: ...
    def request(...) -> ApiResponse: ...  # returns inner's response unchanged
    def recording(self) -> dict: ...      # a recording in the format below
    def save(self, path) -> None: ...

def scrub_interaction(interaction: Mapping[str, Any]) -> dict: ...  # a scrubbed copy
```

Recording file (JSON, UTF-8, LF):

```json
{
  "format": "tilo.http-recording/1",
  "connector": "gmail",
  "note": "free text",
  "interactions": [
    {
      "request": {"method": "GET", "url": "https://gmail.googleapis.com/gmail/v1/users/me/threads",
                  "params": {"q": "from:supplier@example.com"}, "headers": {"authorization": "REDACTED"},
                  "json": null},
      "response": {"status": 200, "headers": {"content-type": "application/json"},
                   "json": {"threads": []}, "content_b64": null}
    }
  ]
}
```

- Matching: an unused interaction matches when `method` and `url` are equal, every recorded param
  equals the live one (as strings, a list as a list of strings; the live request may carry more), and
  a non-null recorded `json` equals the live json. Of the matches, the one with the most recorded
  params is served (ties: the earliest), once. The live request must carry `authorization: Bearer
  <something>`; otherwise, or with no match, `ReplayMiss`.
- The response: `status_code` = `status`, `headers` lower-case, `json()` = `json` (`content` its UTF-8
  JSON bytes), or `content` = base64 of `content_b64` when `json` is null.
- Scrubbing replaces with `"REDACTED"`: request and response headers `authorization`,
  `proxy-authorization`, `cookie`, `set-cookie`, `x-goog-api-key`; params `access_token`, `key`,
  `oauth_token`, `token`, `code`; JSON keys at any depth `access_token`, `refresh_token`, `id_token`,
  `client_secret`, `code`, `code_verifier`, `token`, `assertion`, `password`.
- A committed recording holds no token and no address outside example.com, example.net and
  example.org. Recordings are written by hand or by a `RecordingTransport` run under `LIVE=1`, which
  only the user sets.

## Ambiguities resolved (PRD silent; stated defaults)

- Attachment limit 25 MiB total and Gmail's blocked extensions; download limit 25 MiB (PRD 11.4, 12.6
  give no number).
- Drive reads use `drive.file` (picker grants per file) rather than `drive.readonly` (PRD 12.2 "files
  the user picks", 16.1 least privilege).
- Writes go only to the Tilo folder (PRD 12.2 "write deliverables to a Tilo folder").
- Bounded retry: 3 requests, at most 60 s of waiting per call (PRD 6.6, 12.1 `limits` give no number).
- Label changes are not pinned: no action id or tier is declared for them (BQ-44 would make one T3).
