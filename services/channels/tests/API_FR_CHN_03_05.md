# `tilo_channels`: public API pinned by the FR-CHN-03 and FR-CHN-05 tests

Server side only (the S-16 binding screen and the web card are AG-WEB #84). Sources: PRD 10.3 (one card,
every channel), 10.4 (risk tiers, T3 always a person), 11.1 (binding a WhatsApp number), 11.6 (FR-CHN-03,
FR-CHN-05), 15.1 (`ChannelBinding`), 16.2 and SEC-06 (bound numbers only, PIN for T3 approvals over
WhatsApp), 18.4 (WhatsApp copy rules), honesty rules HR-1 and HR-7 (9.4); contracts
`card.schema.json`, `events/data/channel.message_in.schema.json`, `channel.message_out.schema.json`,
`approval.resolved.schema.json` (`pin_verified`), outbox rule OB-01, ADR-0006, BQ-56. Defaults the PRD
does not state are BQ-89 in `docs/open-questions.md` (listed at the end). Tests import only what is below.
Test doubles live in `_chn_0305_lib.py`.

## `tilo_channels.whatsapp` (additive)

`InboundMessage` gains two fields with defaults, so existing positional construction still works:

```text
button_id: str | None = None   # interactive.button_reply.id (kind "interactive"), or button.payload
                               # (kind "button", a template quick reply); else None. Non-string,
                               # empty or list_reply values give None.
context_id: str | None = None  # context.id (the wamid of the message being replied to), any kind
```

## `tilo_channels.binding` (FR-CHN-03)

```python
CODE_TTL_S = 600                 # a code is valid while now < sent_at + CODE_TTL_S
MAX_CODE_ATTEMPTS = 5            # the 5th wrong code voids the pending code
RECONFIRM_AFTER_S = 30 * 86400   # bound while now < verified_at + RECONFIRM_AFTER_S (PRD 11.1)

def normalise_number(raw: str) -> str | None
    # E.164 as typed ("+1 202-555-0101", "(202) ...") -> WhatsApp wa_id digits ("12025550101").
    # Strips spaces, dashes, dots, parentheses and one leading "+"; None unless 8-15 digits remain.

class NumberCipher(Protocol):    # Cloud KMS in production
    def encrypt(self, plaintext: str) -> str: ...
    def decrypt(self, ciphertext: str) -> str: ...

class BindingStore(Protocol):    # Firestore in production; values are JSON-able dicts
    def get(self, key: str) -> dict | None: ...
    def put(self, key: str, value: dict) -> None: ...
    def create(self, key: str, value: dict) -> bool: ...   # atomic create-if-absent
    def delete(self, key: str) -> None: ...

@dataclass(frozen=True)
class BindingResult:
    ok: bool
    reason: str | None   # None when ok, else one of the codes below

@dataclass(frozen=True)
class BindingStatus:
    state: str                 # "none" | "pending" | "bound" | "expired"
    number_masked: str | None  # "***" + last 4 digits; never the full number
    verified_at: float | None  # unix seconds
    expires_at: float | None   # verified_at + RECONFIRM_AFTER_S

class BindingService:
    def __init__(self, *, store: BindingStore, cipher: NumberCipher, sender: Sender,
                 clock: Callable[[], float], hash_key: bytes) -> None   # hash_key < 32 bytes: ValueError
    def start(self, user_id: str, number: str) -> BindingResult
    def confirm(self, user_id: str, code: str) -> BindingResult
    def unbind(self, user_id: str) -> bool          # True when a binding or pending code was removed
    def user_for(self, number: str) -> str | None   # satisfies keywords.Bindings
    def number_for(self, user_id: str) -> str | None
    def status(self, user_id: str) -> BindingStatus
```

`start` (the web app, signed-in user): `invalid_number` (nothing sent), `number_taken` (the number is
bound to another user; nothing sent), `send_failed` (the sender raised; no pending code kept). On success
exactly one WhatsApp text goes to the normalised number containing a fresh 6-digit code (the only 6-digit
run in the body); a new `start` replaces the user's pending code and resets attempts. An existing binding
stays in force until the new number is confirmed.

`confirm` (the web app): `no_pending`, `expired`, `wrong_code`, `too_many_attempts` (returned by the
attempt that voids the code and by every later one until a new `start`), `number_taken` (another user
confirmed the number first). On success the number is bound to the user, any previous number of that
user is unbound, and the code is spent (single use).

`user_for` / `number_for` return a value only for a confirmed binding with `now < verified_at + 30 d`;
a pending or expired number is unbound. Re-confirmation is `start` + `confirm` with the same number.

Storage: numbers are encrypted with the cipher and looked up by a keyed hash (PRD 11.1, 15.1). No key or
value in the store contains the number in any spelling, and the code is never stored in clear.
Invariants: one number binds to at most one user, one user has at most one bound number.

## `tilo_channels.inbound` (FR-CHN-03 acceptance, the dispatcher)

```python
@dataclass(frozen=True)
class RouteResult:
    route: str   # "opt_in" | "keyword" | "card" | "off_topic" (FR-CHN-04, API_FR_CHN_04.md)

class InboundRouter:
    def __init__(self, *, bindings: Bindings, sender: Sender, web_url: str,
                 keywords: KeywordHandler | None = None, cards: WhatsAppCards | None = None) -> None
    def handle(self, message: InboundMessage) -> RouteResult
    def __call__(self, message: InboundMessage) -> RouteResult   # usable as the WhatsAppWebhook handler
```

A sender with no valid binding gets exactly one reply, the opt-in instructions, which contain `web_url`,
are the same for every unbound sender and message, and never echo the message; nothing else runs (no
keyword effect, no card answer, no event). A bound sender goes to `keywords`, then `cards` (a result other
than `ignored` is route `card`), else `off_topic` (FR-CHN-04 owns that reply; no opt-in text).

## `tilo_channels.cards` (FR-CHN-05)

```python
PIN_WINDOW_S = 300   # a PIN is accepted only within 300 s of the Approve tap that asked for it

class CardsApi(Protocol):   # tilo-api client: POST /worlds/{w}/cards/{c}/answer as tilo-channels for user_id
    def answer(self, world_id: str, card_id: str, *, option: str, user_id: str, channel: str,
               pin_verified: bool) -> Any   # .outcome "answered" | "rejected"; .reason e.g. "already_resolved"
class PinVerifier(Protocol):
    def verify(self, user_id: str, pin: str) -> bool: ...
class Archive(Protocol):    # redacted raw archive (PRD 13.2)
    def record(self, run_id: str, kind: str, payload: Mapping[str, Any]) -> str: ...  # "<run_id>/<seq>"
class EventWriter(Protocol):
    def write(self, part: dict) -> None: ...
class CardSender(Protocol):
    def send_text(self, to: str, body: str) -> object: ...
    def send_buttons(self, to: str, body: str, buttons: Sequence[tuple[str, str]]) -> str: ...  # (id, title); returns the wamid
class CardBindings(Protocol):   # BindingService satisfies it
    def user_for(self, number: str) -> str | None: ...
    def number_for(self, user_id: str) -> str | None: ...

@dataclass(frozen=True)
class SendResult:
    outcome: str             # "sent" | "not_bound" | "not_whatsapp" | "expired"
    message_id: str | None   # the wamid when sent

@dataclass(frozen=True)
class ReplyResult:
    outcome: str   # "answered" | "pin_required" | "wrong_pin" | "already_answered" | "expired"
                   # | "unknown_card" | "forbidden" | "rejected" | "failed" | "ignored"
    card_id: str | None
    option: str | None

class WhatsAppCards:
    def __init__(self, *, bindings: CardBindings, api: CardsApi, sender: CardSender, events: EventWriter,
                 archive: Archive, pins: PinVerifier, clock: Callable[[], float], web_url: str,
                 pin_window_s: float = PIN_WINDOW_S) -> None
    def send_card(self, card: Mapping[str, Any], *, user_id: str) -> SendResult
    def handle(self, message: InboundMessage) -> ReplyResult
    def card_closed(self, card_id: str, *, channel: str) -> bool
```

`send_card`: only cards whose `answer_channels` list `whatsapp` (else `not_whatsapp`), only to the user's
valid bound number (else `not_bound`), only before `created_at + timeout` (else `expired`); nothing is
sent otherwise. One interactive message: one reply button per option, in order, title = option label
(so gate buttons read Approve / Edit first / Hold, CR-07), unique opaque ids of at most 256 characters
that never contain the number; the body carries `what_happened` and a link under `web_url`. Writes one
`channel.message_out` part.

`handle` (bound senders; anything else is `ignored` with no send): a button tap is honoured only from the
number the card was sent to while it is still bound to the card's user (`forbidden` / `unknown_card`
otherwise, no API call). Then: past the timeout `expired`; `approve` on a gate whose `risk_tier` is T3
asks for the PIN (`pin_required`, no API call); every other option calls `api.answer(..., channel=
"whatsapp", pin_verified=False)`. A text from the same number within `pin_window_s` of that prompt is
checked with `pins.verify`; true calls `api.answer(option="approve", pin_verified=True)`, false is
`wrong_pin` (no answer; the prompt is spent, tap Approve again). API `already_resolved` is
`already_answered`; other rejections `rejected`; an API exception `failed` (never raises). Typed text
never answers a card option ("yes", "approve" and the like included, BQ-56). Each refusal or outcome
sends exactly one short text; `answered` sends one confirmation, after the API accepted.

Events (registered types only; the API, not channels, emits `question.answered` and `approval.resolved`):
parts are `{"type", "world_id", "run_id", "actor", "authz": None, "data"}` with `data` valid against
`contracts/events/data/<type>.schema.json`.
- `channel.message_out` per card sent: `data = {channel: "whatsapp", message_ref, card_id}`.
- `channel.message_in` per answered tap: `actor` the bound user, `data = {channel: "whatsapp",
  message_ref, card_id, card_kind, option, destination}`, `destination` the gate's
  `action.destination` on a gate card, else null. `message_ref` comes from `archive.record`.
Neither the archive payload, nor events, nor logs ever contain the full number or a PIN.

`card_closed` (the API's card-closed notification, answered on another channel, or by timeout with
`channel="timeout"`): if the card was sent on WhatsApp and is still open there, sends one short text to
that number (only while it is still bound to the card's user) and returns True; later taps are
`already_answered`. Repeats, unknown cards and cards answered on WhatsApp itself return False and send
nothing.

## BQ-89 defaults (PRD silent)
6-digit code, valid 10 min, 5 attempts; `number_taken` while bound to another user (refused at `start`,
nothing sent); 30-day window is `now < verified_at + 30 d`; one opt-in reply per inbound message from an
unbound number; PIN is a typed reply within 300 s of the Approve tap, one try per tap; closing notice is
a short text (WhatsApp cannot edit a sent interactive message); typed text never answers a card option.
