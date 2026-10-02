# `tilo_channels`: public API these tests pin (FR-CHN-02, FR-CHN-06)

Package `services/channels`, import name `tilo_channels`, dist name `tilo-channels`
(`src/tilo_channels`, hatchling, workspace member like `services/connectors`; the builder adds the
`pyproject.toml`, the root workspace entry and the lock). It does not exist yet, so every test here
fails today with `ModuleNotFoundError`. Tests import only what is listed below.

## `tilo_channels.whatsapp`

```python
@dataclass(frozen=True)
class InboundMessage:
    message_id: str        # Meta wamid
    sender: str            # `from` (wa_id), trusted only after the signature check
    timestamp: int         # unix seconds, from the payload
    kind: str              # payload `type`: "text", "image", ...
    text: str | None       # text.body for kind "text", else None

def verify_signature(app_secret: bytes, raw_body: bytes, header: str | None) -> bool
    # True only for "sha256=" + lowercase-hex HMAC-SHA256(app_secret, raw_body); constant-time compare;
    # False (never raises) for None, empty, wrong prefix, non-hex, wrong length, other secret or body.

@dataclass(frozen=True)
class MessageOutcome:
    message_id: str
    sender: str
    result: str            # "processed" | "duplicate" | "stale"

@dataclass(frozen=True)
class WebhookResponse:
    status: int            # 200, 400 (signed but not JSON), 401 (signature)
    outcomes: tuple[MessageOutcome, ...]   # () for 400, 401 and status-only deliveries

class WhatsAppWebhook:
    def __init__(self, *, app_secret: bytes, now: Callable[[], float], store: DedupeStore,
                 handler: Callable[[InboundMessage], object], max_age_s: float = 300) -> None
    def receive(self, raw_body: bytes, signature_header: str | None) -> WebhookResponse
```

Injected `DedupeStore` (Firestore in production, `MemoryDedupeStore` in tests):
`claim(key: str, ttl_s: float) -> bool`, an atomic set-if-absent; True for the first claimant.

Behaviour: verify the signature over the raw bytes first (nothing else runs on failure: no claim, no
handler); parse Meta's `entry[].changes[].value.messages[]` (ignore `statuses`); a message older than
`max_age_s` is `stale` and claims nothing; otherwise claim `<key containing the message id>` with
`ttl_s >= max_age_s`, a lost claim is `duplicate`; claimed messages go to `handler`, serialised per
sender (never overlapping, thread-safe), sorted by (timestamp, payload position) within one delivery.

## `tilo_channels.keywords`

```python
def parse_keyword(text: str | None) -> str | None
    # "STOP AUTOPILOT" | "PAUSE" | "UNSUBSCRIBE" | None. Whole message, case-insensitive, whitespace trimmed
    # and collapsed; anything else (including bare STOP, or a keyword inside a sentence) is None.

@dataclass(frozen=True)
class KeywordResult:
    handled: bool          # False: not a keyword, not text, or number not bound (dispatcher continues)
    keyword: str | None
    applied: bool          # the control-plane effect succeeded
    confirmed: bool        # the confirmation was sent

class KeywordHandler:
    def __init__(self, *, bindings: Bindings, controls: Controls, sender: Sender) -> None
    def handle(self, message: InboundMessage) -> KeywordResult   # never raises on a failed effect
```

Injected protocols: `Bindings.user_for(number: str) -> str | None`;
`Controls.stop_all_autopilot(user_id, *, channel) -> int` (every policy to L1, one `policy.changed`
change=stop_all level=L1 each), `Controls.pause_all(user_id, *, channel) -> None` (`world.paused`
reason=pause_all), `Controls.unsubscribe_whatsapp(user_id) -> None` (WhatsApp notifications off);
`Sender.send_text(to: str, body: str) -> None`. `channel` is always `"whatsapp"`.
