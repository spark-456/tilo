# `tilo_browser` — public API these tests pin

Tickets FR-CON-07 (isolation, allowlist egress, masking) and FR-CON-08 (login walls raise a
card, never a filled field); FR-CON-13 is applied to the worker. Package `services/browser`,
import name `tilo_browser`, dist name `tilo-browser` (add `tilo-providers` and `jsonschema`
as dependencies; add the member to the root `[tool.uv.workspace]`). The package does not
exist yet, so every test fails today with `ModuleNotFoundError`.

## `tilo_browser.egress`

```python
class EgressBlocked(Exception):          # message must not contain the URL's query or userinfo
    decision: Decision

@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str      # "allowed" | "host_not_allowlisted" | "scheme_not_allowed" | "ip_literal"
                     # | "invalid_url" | "sensitive_query"
    url: str         # sanitised: no userinfo, no query, no fragment
    host: str | None # lower-case, IDNA A-label form; None if unparsable
    scheme: str | None
    redirect_from: str | None = None   # sanitised, set when check(..., redirect_from=)

class EgressPolicy:
    def __init__(self, allow: Sequence[str], *, allow_schemes: Sequence[str] = ("https",)): ...
        # entries: "example.com" (exact host) or "*.example.com" (any depth below, not the apex).
        # ValueError for "", "*", IP literals, schemes/paths in an entry, "ex*ample.com", "a.*.com", "*.".
    def check(self, url: str, *, redirect_from: str | None = None) -> Decision   # logs one Decision per call
    decisions: list[Decision]   # every check, in order
    blocked: list[Decision]     # the not-allowed ones, in order
```

## `tilo_browser.masking`

```python
def mask_text(text: str) -> str      # [masked:secret|card|email|phone]; idempotent; see test docstring
def mask_data(value: Any) -> Any     # recursive over dict/list/str, copies, other types untouched
```

## `tilo_browser.login`

```python
@dataclass(frozen=True)
class LoginSignal: kind: str; refs: tuple[str, ...]   # kind: password_field | otp_field | sso_redirect | credentials_in_text
class CredentialEntryRefused(Exception): ...           # message never contains the text that was to be typed
LOGIN_CARD_OPTION_IDS = ("connect_api", "upload_export", "skip")

@dataclass(frozen=True)
class CardContext:
    world_id: str; run_id: str; header: dict          # {"building": "B2", "agent": "A_s1"}
    new_card_id: Callable[[], str]; now: Callable[[], str]; timeout: int

def detect_login(*, chain: Sequence[str], tree: dict, text: str) -> LoginSignal | None
def secure_field_refs(tree: dict) -> list[str]        # password, one-time-code and payment (cc-*) fields
def build_login_card(signal: LoginSignal, *, url: str, ctx: CardContext) -> dict   # card.schema.json needs-you card
```

`chain` = every URL requested for the navigation, in order, including the requested one and
including a hop the egress gate aborted (last). Priority if several apply: password_field,
otp_field, sso_redirect, credentials_in_text (tests never require a specific winner when two
apply, except where stated).

Accessibility tree (what `Driver.read_accessibility_tree()` returns and the tests feed in):

```python
{"role": str, "name": str, "attrs": {"id": ref, "type"?: ..., "name"?: ..., "autocomplete"?: ...,
  "inputmode"?: ..., "maxlength"?: ..., "placeholder"?: ...}, "value"?: str, "children": [node, ...]}
```

`attrs["id"]` is the element ref used by `find_element` / `click` / `type`.

## `tilo_browser.worker`

```python
class WorkerClosed(Exception): ...

class BrowserWorker(HandsProvider):    # tilo_providers.interfaces.HandsProvider
    def __init__(self, engine, policy: EgressPolicy, *, card_sink: Callable[[dict], None] | None = None,
                 card_context: CardContext | None = None): ...
    def navigate(self, url) -> dict      # {"url": final_url, "login_required": bool, "login_kind": str | None}
                                         # raises EgressBlocked on a blocked navigation or redirect hop
                                         # (not for a blocked SSO hop: it returns login_required=True)
    def find_element(self, selector) -> dict      # {"ref": ref}
    def click(self, ref)  / type(self, ref, text) / upload_file(self, ref, path)
    def read_accessibility_tree(self) -> dict     # masked
    def screenshot(self) -> bytes                 # driver.screenshot(mask_refs=secure_field_refs(tree))
    def download_file(self, ref) -> bytes
    def capture(self) -> Capture                  # frozen dataclass: url, title, text, screenshot: bytes, meta: dict; all masked
    def close(self) -> None                       # idempotent; closes the engine context; __enter__/__exit__ too
```

`engine.new_context(gate) -> Driver` is called once per worker (one run = one isolated context);
`gate(url, *, redirect_from=None) -> bool` is the egress allowlist (it calls `EgressPolicy.check`) and the
driver must call it before EVERY request (navigation, each redirect hop with `redirect_from=` the hop it
came from, each subresource, a click's navigation). Driver protocol (see
`_browser_lib.FakeDriver`): `goto(url)` and `click(ref)` return
`{"chain": [urls], "aborted": url | None, "final_url": str | None}`; `type(ref, text)`;
`find(selector) -> ref`; `read_accessibility_tree()`; `page_text()`; `page_title()`;
`screenshot(mask_refs) -> bytes`; `screenshot_meta() -> dict`; `upload(ref, path)`;
`download(ref) -> bytes`; `close()`.

Worker behaviour pinned: re-inspect the page after every `navigate` and `click`; raise one needs-you
card per host per run through `card_sink`; refuse `type` on secure fields always and on every field of
a login wall; mask every string that leaves the worker (`capture`, tree); never put a URL query or
userinfo in an error message or the decision log.

## Needs contract change

None required. Noted, not blocking: there is no registered event for a blocked egress request, so the
Browser Station cannot animate one yet (HR: nothing animates without a recorded event); today the
blocked request lives in `EgressPolicy.blocked` for the caller to turn into an event or alert.
`config/connectors.yaml` (the per-adapter egress allowlist named in `services/browser/CLAUDE.md`) does
not exist yet; the tests build `EgressPolicy` from literals.
