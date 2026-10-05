# Live Gmail smoke harness: public API these tests pin (FR-CON-04, PRD 5.4 CP1, PRD 12.1/12.6, SEC-02, EFF-01)

Ticket: one command with `LIVE=1` that (1) prints the Google consent URL, (2) waits for the redirect on
`127.0.0.1:8080/oauth/google/callback`, (3) exchanges the code (tokens in memory only, `FakeKms`), (4) lists up
to 5 recent messages as date/from/subject, (5) with `--draft ADDRESS` creates one draft. It never sends.

Tests: `test_FR_CON_04_live_smoke_transport.py` (live HTTP layer), `test_FR_CON_04_live_smoke_callback.py`
(callback listener), `test_FR_CON_04_live_smoke_e2e.py` (`run_smoke` and the CLI). Doubles: `_live_lib.py`
(a real HTTP server on an ephemeral 127.0.0.1 port that plays Google's token endpoint and Gmail, backed by the
`FakeGoogle` and `FakeGoogleApis` doubles; a guard that fails any test that resolves or connects outside
127.0.0.0/8 or opens a browser). Nothing here uses the network, a real account or `LIVE` outside a test's own
patched environ.

Every test fails today with `ModuleNotFoundError: tilo_connectors.live` (or a missing
`services/connectors/scripts/live_gmail_smoke.py`).

Run: `uv run pytest services/connectors/tests -q -k live_smoke`.

## Where the code lives

Everything below is importable from `tilo_connectors.live` (implement it in that file or in private submodules
it re-exports). The script `services/connectors/scripts/live_gmail_smoke.py` is a thin CLI (at most 120 lines)
over `tilo_connectors.live.run_smoke`, with `main()` and an `if __name__ == "__main__"` guard; the tests load
it by path and also run it as a subprocess. The existing adapters, broker and consent service are reused
unchanged, except the one additive change under "Date" below.

## `tilo_connectors.live`

```python
ALLOWED_HOSTS: frozenset[str] = frozenset({"oauth2.googleapis.com", "gmail.googleapis.com", "www.googleapis.com"})
DEFAULT_TIMEOUT_S: float  # 0 < value <= 60
CALLBACK_PATH = "/oauth/google/callback"

class LiveNotEnabled(RuntimeError): ...   # message contains "LIVE=1"
class HostRefused(Exception): ...         # fixed text: no URL, header or form value
class SmokeError(Exception): ...          # fixed text plus short reasons; never a token, code, body or secret
class CallbackTimeout(SmokeError): ...

class LiveHttpClient:   # tokens.HttpClient: post(url, *, data) -> response with status_code and json()
class LiveTransport:    # adapters._transport.Transport: request(method, url, *, params, headers, json, content)
    def __init__(
        self,
        environ: Mapping[str, str] | None = None,    # None -> os.environ
        *,
        allowed_hosts: Collection[str] = ALLOWED_HOSTS,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        endpoint_overrides: Mapping[str, str] | None = None,   # test seam, see below
        allow_loopback_http: bool = False,                      # test seam, see below
    ) -> None: ...
    allowed_hosts: frozenset[str]   # attribute
    timeout_s: float                # attribute
```

### EFF-01: LIVE gate

`LiveHttpClient(...)`, `LiveTransport(...)` and `run_smoke(...)` raise `LiveNotEnabled` unless
`environ["LIVE"] == "1"` exactly (`""`, `"0"`, `"true"`, `"yes"`, `" 1"`, `"01"` all refuse). The check is
the first thing `run_smoke` does: before it validates anything else, prints, binds a port or sends a request.
`environ=None` reads `os.environ` at call time.

### Host allow-list, redirects, timeout, retries (both classes)

- A request goes out only when its URL is exactly: scheme `https`, no userinfo, no backslash or whitespace,
  host (case-insensitive) in `allowed_hosts`, port absent or 443. Anything else, including any `http` URL, a
  scheme-less or relative URL, an empty string, a malformed one, and `gmail.googleapis.com@evil.example`, raises
  `HostRefused` before DNS and before a socket. `LiveTransport.request` checks the URL it is given; the
  `LiveHttpClient` checks the URL it posts to. `allowed_hosts` may be narrowed by the caller.
- A redirect (any 3xx) is never followed: it raises `HostRefused` and the redirect target receives nothing.
- Every request has a timeout: `timeout_s` must be a finite number > 0 (`0`, negative, `None`, `inf`, `nan`,
  `True` raise `ValueError`). A timeout or any network failure raises
  `tilo_connectors.adapters.TransportError` with fixed text (no URL, no header, no form value, and no chained
  cause that carries them).
- The classes do not retry. One call is one HTTP request, whatever the status; 429 and 5xx come back as
  responses. Retrying is the adapters' job and stops at `adapters.MAX_ATTEMPTS` (3 requests per call, at most
  60 s of waiting, `sleep` injected).
- `LiveTransport.request` returns an object with `status_code: int`, `headers` (lower-case names), `content:
  bytes` and `json()` (raises `ValueError` when the body is not JSON). 4xx and 5xx are responses, not
  exceptions. `params` values that are lists are sent as repeated query parameters; `None` values are dropped;
  `json=` sends a JSON body with `content-type: application/json`; `content=` sends the bytes with the caller's
  headers. `LiveHttpClient.post(url, *, data)` sends `application/x-www-form-urlencoded` and returns an object
  with `status_code` and `json()`.
- Nothing is logged or printed, `http.client` debug stays off, and `repr()` of a client holds no environ value.

### Test seam: pointing Google's hosts at a fake on 127.0.0.1

The broker, the consent service and both adapters call fixed Google URLs, so a test cannot "allow 127.0.0.1"
and call it. Instead `endpoint_overrides={"gmail.googleapis.com": "http://127.0.0.1:PORT", ...}` maps an
allowed Google host to a loopback base; the URL is checked against `allowed_hosts` as written (still
`https://gmail.googleapis.com/...`), then only scheme and authority are replaced, path and query kept.
`ValueError` at construction unless `allow_loopback_http=True` and every override is `http://127.0.0.1:N` or
`http://localhost:N`. Without the two arguments, loopback and plain http are always `HostRefused`.
An override for a host that is not in `allowed_hosts` is inert (requests to it are refused).
`run_smoke` accepts and forwards the same three arguments (`allowed_hosts`, `endpoint_overrides`,
`allow_loopback_http`) plus `timeout_s`.

### `CallbackServer`

```python
class CallbackServer:
    def __init__(self, *, expected_state: str, port: int = 8080, timeout_s: float = 300.0) -> None: ...
    port: int                       # the bound port (port=0 picks one)
    address: tuple[str, int]        # ("127.0.0.1", port)
    def wait(self) -> CallbackResult   # blocks up to timeout_s; closes the listener before returning or raising
    def close(self) -> None
@dataclass(frozen=True)
class CallbackResult:
    code: str | None    # excluded from repr
    error: str | None   # always matches [A-Za-z0-9_.-]{1,64}; "access_denied" stays as is
```

- Binds `127.0.0.1` only, in the constructor (the listener exists before `run_smoke` prints the URL, so a fast
  redirect cannot be missed). No parameter selects another interface. A listener on 0.0.0.0 also answers on
  127.0.0.2 and a test checks that; so does IPv6 `::1`.
- One thread per connection, with a per-connection read timeout: an idle connection or a 100 kB request line
  does not stall or kill the wait.
- Only `GET {CALLBACK_PATH}` with exactly one `state` parameter equal to `expected_state` counts. Wrong, empty,
  missing or duplicated `state` (even `state=ok&state=ok`) is HTTP 400 and the wait goes on; so is a forged
  `error=access_denied` with a wrong state. Other paths are 404, other methods 400/404/405/501. Nothing the
  caller sent is echoed in any response.
- The first valid request ends the wait: `code=...` gives `CallbackResult(code, None)`;
  `error=...` gives `CallbackResult(None, <sanitised error>)`; neither gives `CallbackResult(None, <non-empty>)`.
  The response is 200, `cache-control: no-store`, `referrer-policy: no-referrer`, `text/html` or
  `text/plain`, with no code or state in the page. The listener is closed afterwards (a reused state meets a
  closed port).
- No valid request within `timeout_s`: `CallbackTimeout`, listener closed, port free again.
- `timeout_s` must be finite and > 0, `expected_state` non-empty (`ValueError`). `repr` and `str` of the server
  and result hold neither the state nor the code.

### `run_smoke`

```python
def run_smoke(
    *,
    environ: Mapping[str, str] | None = None,        # LIVE and GOOGLE_OAUTH_* are read from here
    draft_to: str | None = None,                     # CLI: --draft ADDRESS
    out: TextIO | None = None,                       # all human output; None -> sys.stdout at call time
    on_consent_url: Callable[[str], None] | None = None,   # called with the URL after it is printed
    callback_timeout_s: float = 300.0,               # CLI: --timeout
    allowed_hosts: Collection[str] = ALLOWED_HOSTS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    endpoint_overrides: Mapping[str, str] | None = None,
    allow_loopback_http: bool = False,
    store: TokenStore | None = None,                 # None -> InMemoryTokenStore; the KMS is a FakeKms
    emit: Callable[[dict], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> SmokeResult

@dataclass
class SmokeResult:
    messages: list[dict[str, str]]    # at most 5, newest first, each exactly {"date", "from", "subject"}
    draft: dict | None                # None without draft_to; else at least {"outbox_id": str}
    events: list[dict]                # every event part emitted, in order (also passed to `emit`)
```

Order and behaviour:

1. `LiveNotEnabled` check (above). Then, all before anything is printed, bound or sent, each a `SmokeError`
   whose message names the problem but never a value: `OAuthSettings.from_env` errors (names the missing
   variable, e.g. `GOOGLE_OAUTH_CLIENT_ID`), a redirect base URL that is not `http` on `127.0.0.1` or
   `localhost` (so `https://tilo.example.com`, `https://localhost:8080`, `http://0.0.0.0:8080` are refused), and
   a `draft_to` that is not one plain address (`a@b.c`: empty, no `@`, two addresses, a newline, `a@@b.c`,
   embedded space are refused).
2. Scopes: one consent for `read` (plus `write` when `draft_to` is set) of the `gmail` entry of
   `config/connectors.yaml`: exactly `gmail.readonly` without `--draft`; exactly `gmail.readonly` and
   `gmail.compose` with it. Never `gmail.send`, `gmail.modify`, `mail.google.com`, Drive or openid. Built with
   `ConsentService.authorization_url` (PKCE S256, single-use state). One consent URL per run.
3. Bind `CallbackServer` on the redirect URL's host port (`settings.redirect_uri` unchanged; default 8080),
   then print the URL (in full, once) and call `on_consent_url`. Never open a browser.
4. `CallbackTimeout` after `callback_timeout_s`; `SmokeError` for a denial or an empty answer; a refused code
   exchange is a `SmokeError` too ("Google did not accept the sign-in" style, fixed text). A code is exchanged
   at most once. Nothing from a provider body is echoed (the fake echoes the code and the verifier on a 400).
5. Tokens go to the broker (`ConsentService.handle_callback` stores them sealed under `FakeKms`) and nowhere
   else: no file is written, nothing is cached on disk, plaintext never reaches the store, the log or `out`.
6. Read: at most 5 messages, newest first; at most 5 per-message fetches, every list request with
   `maxResults <= 5`; print one line per message with date, from and subject only (no body, snippet, id, label
   or thread id). All three fields are sanitised before they reach `messages` or `out`: control characters
   (categories Cc, Cf, Zl, Zp: ESC, BEL, C1 CSI, bidi overrides) become spaces or are dropped; text is kept.
   An empty mailbox prints a "no messages" line and returns `messages == []`.
7. Draft (`draft_to` only), after the read: one `create_draft` entry through the outbox
   (`Outbox.enqueue` with person authorisation of the user who ran the command, `dispatch_due()` once), to
   exactly `draft_to` (no Cc, no Bcc, no thread), with fixed text that contains nothing from the mailbox. One
   `POST .../drafts`, no retry on a 400; zero requests to `/messages/send` or `/drafts/send`. A draft that is
   not created (entry not `sent`) is a `SmokeError`. `result.events` then holds one `data.transfer` with
   `authz.by == "person"`, `direction == "out"`, `connector == "gmail"`, `action_type == "create_draft"`.
   Without `draft_to` the run makes zero non-GET requests to Gmail (the token POST aside).
8. The listener is closed on every path, success or failure, before `run_smoke` returns or raises.
9. Events: only types already in `contracts/events/registry.yaml` with their fixtures: `connection.consented`,
   `connection.established` (from the consent service), `data.transfer` (from the outbox), and
   `connection.rate_limited` / `connection.expired` if they happen. Each part's `data` validates against its
   schema; `authz` is present exactly for the registry's side-effect types. A run that needs any other type
   STOPs and reports "needs contract change".

### Date (the one additive adapter change)

`GmailAdapter.get_message` does not return the `Date` header today. The smoke needs it. Either add a `"date"`
key to the adapter's message dict (additive: no existing test compares the whole dict) or read the header some
other way through the adapter's own `Transport`; the tests only look at `SmokeResult.messages` and `out`. The
`date` value is the `Date` header text (after sanitising).

## CLI: `services/connectors/scripts/live_gmail_smoke.py`

```python
def main(argv: Sequence[str] | None = None, *, environ=None, out=None, **run_smoke_options) -> int
```

- Options: `--draft ADDRESS` (required value) and `--timeout SECONDS` (maps to `callback_timeout_s`); `--help`
  lists exactly these. There is no send option, no `--modify`, no `--reply`. An unknown flag or a missing
  `--draft` value is an argparse error (`SystemExit(2)`, or a non-zero return).
- `main` returns 0 on success and a non-zero code on `LiveNotEnabled` and `SmokeError`, after writing a short
  message to `out` (which includes `LIVE=1` for the gate). It never prints a traceback or a secret.
  `**run_smoke_options` are forwarded to `run_smoke` and win over the flags (tests pass `endpoint_overrides`,
  `allow_loopback_http`, `store`, `sleep`, `on_consent_url`).
- Run directly (`python services/connectors/scripts/live_gmail_smoke.py`) without `LIVE=1`: non-zero exit, a
  message containing `LIVE=1`, no traceback, no network.
- Neither `live.py` nor the script contains, in code (docstrings and comments excluded), the strings
  `gmail.send`, `gmail.modify`, `mail.google.com`, `messages/send` or `drafts/send`.

## Test to criterion map (task items 1 to 8)

| Item | Tests |
| --- | --- |
| 1 LIVE gate | `live_requires_live_env`, `live_env_one_constructs...`, `live_default_environ...`, `live_smoke_requires_live_env_before_any_side_effect`, `live_smoke_cli_without_live...`, `live_smoke_script_run_directly_refuses_without_live` |
| 2 host allow-list | `live_default_allow_list_is_the_fixed_google_hosts`, `live_default_has_no_loopback_or_override_way_in`, `live_refuses_hosts_outside_the_allow_list...` (17 URLs x 2), `live_refusal_message_holds_no_url_or_credential`, `live_property_only_exact_https_google_hosts_pass` (Hypothesis), `live_allowed_hosts_can_be_narrowed`, `live_endpoint_overrides_need_the_explicit_loopback_flag`, `live_never_follows_a_redirect_off_host`, `live_a_redirect_to_a_foreign_https_host...` |
| 3 timeout, retries | `live_every_request_has_a_timeout`, `live_a_slow_server_is_a_transport_error...`, `live_transport_makes_one_request_per_call...`, `live_http_client_does_not_retry_a_token_call`, `live_adapter_retries_through_the_live_transport_stop_at_max_attempts`, `live_adapter_honours_retry_after...`, `live_a_dropped_connection...` |
| 4 secrets | `live_network_errors_and_reprs_hold_no_secret`, `live_a_successful_call_logs_and_prints_nothing_secret`, `live_authorization_goes_only_to_the_intended_server`, `live_smoke_end_to_end...` (leak scan of `out`, log, stdout, stderr, store), `live_smoke_access_denied...`, `live_smoke_a_refused_code_never_echoes...`, `live_callback_values_never_appear_in_a_repr` |
| 5 callback server | `live_callback_*` in the callback file; `live_smoke_a_forged_callback...`, `live_smoke_times_out...`, `live_smoke_access_denied...` |
| 6 end to end | `live_smoke_end_to_end_lists_the_five_newest...`, `live_smoke_never_lists_or_reads_more_than_five_messages`, `live_smoke_neutralises_control_characters...`, `live_smoke_draft_creates_exactly_one_draft_and_never_sends`, `live_smoke_a_draft_google_refuses...`, `live_smoke_draft_address_must_be_one_plain_address`, CLI tests |
| 7 scopes | `live_smoke_scopes_are_the_declared_least_privilege_and_incremental` (False/True), the scope asserts in the two end-to-end tests |
| 8 events | `live_smoke_events_are_registered_fixtured_and_valid`, `live_smoke_a_read_only_run_emits_no_transfer` |

## Ambiguities resolved (PRD silent; defaults stated)

- Fake Google reachability: the task said tests inject allowed hosts to reach a loopback fake; the broker and
  adapters hard-code Google URLs, so the seam is `endpoint_overrides` + `allow_loopback_http` (two keys, loopback
  only, off by default). The production default allow-list is asserted.
- Drive host: `www.googleapis.com` (what `DRIVE_API` and `DRIVE_UPLOAD_API` use) is in the list with
  `oauth2.googleapis.com` and `gmail.googleapis.com`. `accounts.google.com` is only printed, never requested.
- The transport does not retry; retries stay in the adapters (so the total is `MAX_ATTEMPTS`, not a product).
- A wrong-state callback is rejected and the wait continues (a stray local request cannot end or hijack the
  flow); the run then ends by timeout.
- `--draft` is one consent for read plus write (not two consents); the draft goes through the outbox with
  person authorisation (SEC-03), so `result.events` carries a `data.transfer`.
- `Outbox` reports a created draft as state `sent` (its only success state); that is not a mail send.
- After the run the grant is left at Google (the smoke does not revoke); tokens die with the process. A
  `disconnect` at the end is not required by the ticket and not tested.
- Output format of the list lines is free (a tab or `|` separated line); the tests look for each field.
