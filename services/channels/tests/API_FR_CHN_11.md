# FR-CHN-11: public API pinned by the preview and undo-window tests (overridable)

FR-CHN-11 "Preview with Send / Edit / Cancel (L1) and send with undo window (L2)". The acceptance test is "L2 send
can be cancelled within 60 s; no send after cancel" (PRD 11.6). Sources: PRD 10.4 (levels, T3 examples, undo window
default 60 s), 11.2 (preview step), 11.4 (Preview, Undo, Formats, Injection), FR-HIL-04, FR-HIL-05, FR-CHN-12 and
FR-CHN-13 (no recipient added without a person; exactly once), `contracts/outbox.schema.json` and
`contracts/outbox.rules.md` (OB-01 to OB-05), `config/autonomy.yaml` (`money_or_legal`, `safety_flag`,
`new_recipients` raise to T3), BQ-147, issue #243 (deterministic money / legal / commitment signal).

These are the tests' assumptions, and the builder may override them. If a name or shape below changes, update the
tests in the same PR and say so in the review. The tests import only what is listed here. Test doubles are in
`_chn11_lib.py` (fake outbox, fake autonomy policy, contacts) on top of `_chn10_lib.py` (the real FR-CHN-10
`Drafter` with a scripted model). Fake clock only, no real send, no network, no paid call. New events: none; only
registered types may be emitted, and never `data.transfer` (the outbox emits it).

## `tilo_channels.autopilot` (new module)

```python
OPTIONS = ("send", "edit", "cancel")    # a ready draft's card; a card without a ready draft has ("edit", "cancel")
UNDO_WINDOW_S = 60                      # PRD 10.4 L2 default
PREVIEW_CHARS = 600                     # PRD 11.4 Preview
ACTION_TYPE = "send_email"              # config/autonomy.yaml: T2 unless a modifier applies

def t3_content_signal(text: str) -> frozenset[str]
    # Deterministic (issue #243). Subset of {"money", "legal", "commitment", "obfuscated"}; empty = no signal.
    # money: amounts with a currency ($1,200), refund, invoice, payment, wire, bank, IBAN ...
    # legal: contract, liability, lawsuit, NDA, terms, waiver ...
    # commitment: we will, guarantee, promise, commit, deadline ...
    # Runs on the cleaned NFKC text, so zero-width, soft-hyphen, bidi, fullwidth and look-alike variants still give a
    # signal, or the text fails closed with "obfuscated". Plain replies ("Friday 2pm works for us.") give none.

def clean_text(text: str) -> str
    # Removes Unicode Cf characters and Cc characters other than "\n" and "\t".

@dataclass(frozen=True)
class DraftContext:          # what FR-CHN-10's Drafter.draft was called with
    instruction_id: str
    thread_id: str
    instruction: str
    mailbox: str
    mode: str = "reply"

class AutonomyPolicy(Protocol):
    def level(self, user_id: str, action_type: str) -> tuple[str, str | None]   # ("L2", policy_id) or ("L1", None)

class Outbox(Protocol):      # same names as tilo_connectors.outbox.Outbox; tilo-channels never imports it
    def enqueue(self, entry: dict, evidence: dict) -> dict      # entry: contracts/outbox.schema.json, OB-02;
                                                                 # a repeated (world_id, idempotency_key) returns the stored one
    def cancel(self, outbox_id: str) -> dict                    # raises once the entry is no longer "scheduled"

@dataclass(frozen=True)
class Preview:
    card_id: str
    user_id: str
    instruction_id: str
    status: str                  # the DraftResult status: "ready" | "needs_you" | "failed"
    options: tuple[str, ...]
    to: tuple[str, ...]          # exactly the draft's recipients; never added to
    cc: tuple[str, ...]
    subject: str
    excerpt: str                 # body[:600]
    body: str                    # clean_text(draft body): what will be sent
    findings: tuple[str, ...]    # inert plain text, one "kind: text" line per FR-CHN-10 Finding, cleaned
    questions: tuple[str, ...]
    tier: str | None             # "T2" | "T3"; None without a ready draft
    modifiers: tuple[str, ...]   # tier_condition names, e.g. ("new_recipients", "money_or_legal", "safety_flag")
    level: str                   # "L2" only when the send was scheduled with the undo window, else "L1"
    undo_window_s: int           # 60 at L2, else 0
    outbox_id: str | None        # the scheduled entry at L2; None until a person taps Send at L1
    scheduled_at: str | None     # the entry's scheduled_at at L2

@dataclass(frozen=True)
class Outcome:
    status: str                  # send: "queued" | "scheduled" | "refused"; cancel: "cancelled" | "too_late" | "refused"
    outbox_id: str | None

class Autopilot:
    def __init__(self, *, drafter: Drafter, reader: ThreadReader,
                 contacts: Callable[[str], Iterable[str]],   # the user's known contacts
                 policy: AutonomyPolicy, outbox: Outbox,
                 cards: DraftStore,                         # FR-CHN-10's protocol: get / create / put by (user_id, key)
                 clock: Callable[[], float], emit: Callable[[dict], None] = ...,
                 world_id: str, run_id: str, connector: str = "gmail") -> None
    def preview(self, user_id: str, context: DraftContext, result: DraftResult) -> Preview
    def send(self, user_id: str, card_id: str) -> Outcome
    def cancel(self, user_id: str, card_id: str) -> Outcome
    def edit(self, user_id: str, card_id: str, change: str, *, instruction_id: str) -> Preview | None
```

## Behaviour the tests check

- **Preview card.** To, Cc, subject, the first 600 characters, Send / Edit / Cancel. L1: nothing enters the outbox
  until the card's owner taps Send; then one `queued` entry, `undo_window_s` 0, `authz` person = the user, T2,
  recipients = To + Cc, `destination` = the thread id, `item.artifact_id` = the draft's. Cancel closes the card.
- **L2.** A T2 draft under an L2 policy is enqueued at once as `scheduled`, `undo_window_s` 60, `scheduled_at` =
  `created_at` + 60 s (from the injected clock), `authz` {by: policy, ref: policy id}, no modifiers. Nothing sends at
  59 s; it sends at 60 s unless cancelled. Cancel within the window returns `cancelled` and nothing is ever sent;
  after the send it returns `too_late`. A cancelled card cannot be sent. Cancel works from another instance.
- **Never auto-sent (T3, PRD 10.4).** `t3_content_signal(body)` non-empty adds `money_or_legal`; `safety_flag` on
  the draft or `flagged` on the result adds `safety_flag` (BQ-147); a recipient that is not known (BQ-154) adds
  `new_recipients`. Any modifier makes it T3: the card is L1 and nothing is scheduled, whatever the policy port
  answers and whatever the instruction was (empty, or one that asks for the refund): the checker's `ready` never
  lowers a tier. A person's Send then queues a T3 entry with those modifiers and `authz` person.
- **needs_you / failed.** No Send option; `send` returns `refused`; findings (including `obfuscation`) are shown as
  cleaned plain text lines.
- **Edit.** Cancels the pending send, redrafts through the drafter with an instruction containing the original
  instruction and the change (the checker runs again; an invented redraft is `needs_you` with no Send), and returns a
  new card at L1 (OB-01, OB-05). The T3 signal runs on the redraft's text. The superseded card cannot be sent. If the
  entry was already sent, `edit` returns None.
- **Exactly once.** Replaying `preview` (same instruction, again, on another instance, on eight instances at once, or
  after a crash between enqueue and the card store write) and replaying Send taps give one entry and one send.
  Only the card's owner can send or cancel it.
- **Property tests.** Under any interleaving of advance / dispatch / cancel / edit / send, an entry pending when a
  cancel or edit succeeded never sends, each card sends at most once, only the instructed draft rides the L2
  window, and a policy send never leaves before created_at + 60 s. Over random recipient sets, every sent entry has
  exactly the draft's recipients, and one with an unknown recipient is a person's send with `new_recipients`.
- **No side channels.** Emitted parts have registered types and valid data, never `data.transfer`, and carry no body
  text or address. The module imports no connector, sender or network client.

Defaults taken where the PRD is silent: BQ-152 to BQ-158 in `docs/open-questions.md`.
