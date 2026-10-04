# FR-CHN-10: public API pinned by the drafting tests (overridable)

FR-CHN-10 "Draft from instruction plus thread, within the content rules in 11.4". The acceptance test is "Eval: 0
invented commitments across 50 drafting cases" (PRD 11.6; 19.2 E-MAIL; 19.4 gate 5). A real model cannot run in
CI (EFF-01), so the tests run the eval offline on scripted model answers: the 20 E-MAIL drafting cases
(`evals/cases/E-MAIL/E-MAIL-31..50.yaml`) plus 30 cases in `fixtures/FR_CHN_10_drafting_cases.yaml`, each with a
clean answer and answers that invent something (every eval case's ground-truth `forbidden_commitments` is acted
out). Every clean answer must become a ready draft; no invented answer may. Sources: PRD 11.2, 11.4 (every row),
11.6 Events, 13.1 and 16.5 (email bodies never cached), 14.2 and BQ-03, 16.2, 16.3 items 1 to 4, 19.2, 19.3,
SEC-03, SEC-04, SEC-05, PL-01, PL-04, EFF-01, `config/autonomy.yaml`, `services/channels/CLAUDE.md`. Patterns
follow FR-CHN-09 (`API_FR_CHN_09.md`, tests/FR-CHN-09 at dbc145d): untrusted mail inside delimited prompt data,
nothing of it in `system`, no tools.

These are the tests' assumptions, and the architect or builder may override them. If a name or shape below
changes, update the tests in the same PR and say so in the review. The tests import only what is listed here.
The test doubles are in `_chn10_lib.py`.

## `tilo_channels.drafting` (new module)

```python
MODES: tuple[str, ...]     # contains "reply" (the default, PRD 11.4 "reply-to-sender by default") and "reply_all"
PRESETS: tuple[str, ...]   # contains "confirm", "decline", "follow_up", "reschedule", "formal_letter" (PRD 11.4)

@dataclass(frozen=True)
class Finding:
    kind: str    # "number" | "date" | "contact" | "commitment" | "obfuscation" (direction control, mixed script)
    text: str    # the span of the draft that no source supports (shown to the user; never logged or emitted)

def find_invented(body: str, *, instruction: str, thread: Sequence[str],
                  trusted: Sequence[str] = ()) -> list[Finding]
    # Deterministic; the same inputs always give the same findings. [] means nothing invented.

class ThreadReader(Protocol):    # the quarantined reader (PRD 16.3 item 3): read-only, no side-effect method
    def get_thread(self, user_id: str, thread_id: str) -> dict
        # {"thread_id", "messages": [ {"message_id", "from" (may carry a display name), "to": [..], "cc": [..],
        #   "subject", "body" (plain text), "date", "headers": {name: value} (incl. "Message-ID", maybe
        #   "References", "In-Reply-To", "Reply-To")} ]}, oldest first; everything but the ids is untrusted

class DraftStore(Protocol):       # drafting results, JSON-able documents, keyed (user_id, instruction_id)
    def get(self, user_id: str, instruction_id: str) -> dict | None
    def create(self, user_id: str, instruction_id: str, value: dict) -> bool   # atomic set-if-absent
    def put(self, user_id: str, instruction_id: str, value: dict) -> None

@dataclass(frozen=True)
class Draft:
    artifact_id: str             # ^art_[0-9A-Za-z_]{1,48}$ (contracts/common.schema.json artifact_id)
    version: int                 # 1
    thread_id: str               # the thread's id
    mode: str                    # one of MODES
    to: tuple[str, ...]          # bare, lower-case addresses
    cc: tuple[str, ...]
    bcc: tuple[str, ...]         # always ()
    subject: str
    in_reply_to: str             # the Message-ID header of the message replied to
    references: str              # space-separated message ids
    body: str                    # contains the model's body (stripped) unchanged
    attachments: tuple[str, ...] # always ()
    safety_flag: bool            # the safety provider flagged the thread

@dataclass(frozen=True)
class DraftResult:
    instruction_id: str
    status: str                  # "ready" | "needs_you" | "failed"
    draft: Draft | None          # set only when status == "ready"
    findings: tuple[Finding, ...]  # () when ready; what was invented when needs_you
    questions: tuple[str, ...]   # the model's questions for the user, when it asked instead of drafting
    flagged: bool                # the safety provider flagged the thread (PRD 11.4 Injection: "are flagged")

class Drafter:
    def __init__(self, *, reader: ThreadReader,
                 model: ModelProvider,     # the "autopilot" role (config/models.yaml) through the Router in
                                           # production; only .generate is called
                 safety: SafetyProvider,   # only .check is called
                 drafts: DraftStore, clock: Callable[[], float],
                 emit: Callable[[dict], None] = ...) -> None   # no sender, outbox or connector parameter
    def draft(self, user_id: str, *, instruction_id: str, thread_id: str, instruction: str, mailbox: str,
              mode: str = "reply", preset: str | None = None,
              style: Mapping[str, Any] | None = None) -> DraftResult
        # instruction_id: the id of the user's instruction (e.g. the channel.message_in it came in), the
        #   idempotency key; mailbox: the user's own connected address; style: structured style-profile settings
        #   {"greeting", "sign_off", "formality", "language", "signature"} (PRD 11.4 Style profile; FR-CHN-15)
```

## Behaviour the tests check

- **Inputs (11.4 Inputs).** The drafter reads the thread once through the reader and asks the model once per
  attempt. The instruction and the text of every message in the thread reach the model; the style settings,
  including the signature and sign-off, reach it too. A preset changes the request. An unknown preset or mode
  raises `ValueError` before any model call or event.
- **Model answer.** JSON `{"body": str, "questions": [str]}` in `GenerateResponse.text` (`questions` optional).
  Any other key (`to`, `cc`, `bcc`, `attachments`, `subject`, `in_reply_to`, `thread_id`, `mode`, `send`,
  `forward_to`, ...) is ignored. Non-empty `questions`: `needs_you` with those questions and no draft ("unclear
  points are asked, not guessed"). Unusable (empty, prose, not an object, empty or non-string body, truncated,
  tool calls): `failed`, no draft.
- **Content rules (11.4 Content), `find_invented`.** Fact sources are the instruction, the thread texts and
  `trusted` (the user's own signature and style); the commitment source is the instruction alone ("any new
  commitment must come from the instruction"), never the thread or `trusted`. At least:
  - `number`: every number in the draft must appear in a fact source. Digits compare after dropping thousands
    commas, a trailing `.00` and a trailing `:00` (`$1,200.00` = `1200`, `5:00 PM` = `5 PM`); `2:45` stays
    `2:45`. Number words two to twelve, the tens, hundred, thousand, dozen and half count as their numbers
    ("five" = `5`); "one" does not. A phone number is a number.
  - `date`: weekday names (also plural), month names and their abbreviations (`Nov`, `Nov.` = November; "may" is
    not checked, it is a common verb), and today, tonight, tomorrow, weekend, this week, next week, next month,
    end of day, EOD, same-day / same day, overnight, ASAP must appear in a fact source.
  - `contact`: every email address and link (`http://`, `https://`, `www.`) must appear in a fact source
    (case-insensitive).
  - `commitment`: these word families must appear in the instruction: free (not in "feel free"), discount,
    waive/waiver, refund, reimburse, compensate, guarantee, promise, complimentary, warranty, "no charge" / "no
    cost" (with optional "extra" or "additional"), pay/payment/prepay.
  - The checker may flag more, as long as every clean fixture answer passes and the properties hold: a draft
    made of pieces of the instruction and courtesy phrases ("Feel free to reply with any questions.") is never
    flagged; a sentence quoted from the thread never gives a `number`, `date` or `contact` finding.
- **Pipeline default for invented content.** A body with findings is never `ready`: the result is `needs_you`
  with the findings and no draft. The drafter may regenerate once (at most 2 model calls per draft); a
  regenerated answer ships only if it is clean.
- **Untrusted thread (11.4 Injection, 16.3).** The safety provider screens the subject, body and From of every
  message, and the model's body. Thread text is only in `GenerateRequest.prompt`, never in `system`; `system` is
  non-empty and comes from a `prompts/autopilot/draft*.md` template (PL-04); no tools are offered (SEC-05). A
  flagged thread gives `flagged` True and, if a draft is made, `safety_flag` True (the `safety_flag` modifier in
  `config/autonomy.yaml` raises any send of it to T3). A flagged model body is not `ready`. A model or safety
  error either raises with nothing stored and nothing emitted, or returns a result that is not `ready`.
- **Recipients and threading (11.4 Threading, Formats).** The message replied to is the latest one whose From is
  not `mailbox`. `reply`: `to == (its sender,)`, `cc == ()`. `reply_all`: its sender first in `to`, and
  `to + cc` equal to its From, To and Cc minus `mailbox` (case-insensitive), no duplicates. Never Bcc, never
  attachments, and a `Reply-To` header never adds a recipient. `subject` is "Re: " plus its subject, unless that
  already starts with "re:" (any case). `in_reply_to` is its `Message-ID`; `references` is its `References` then
  its `Message-ID`. None of these ever come from model output (property test over random threads and answers).
- **No side effects.** The module imports no connector, outbox, policy, sender, other channel module or network
  client. Drafting emits no event type marked `side_effect: true`, and no `data.transfer`,
  `channel.message_out`, `approval.requested`, `approval.resolved`, `policy.applied` or `reply_handled` unit.
- **Events.** Each new ready draft emits one `artifact.created` with `data.artifact` naming its
  `artifact_id` and `version` 1; `needs_you` and `failed` emit none. Delivery is at-least-once: an emit that fails
  is retried after a 60 s lease, and a crash between emit and its marker can repeat it, so consumers dedupe on
  `artifact_id`. Everything emitted is `{type, data, ...}`
  with a registered type and valid data, and carries no subject, body, address, display name, instruction,
  signature or draft text.
- **Privacy.** Logs never hold the thread's subject, body, addresses or display names, the instruction, the
  signature or the draft. The draft store never holds a thread body (PRD 13.1 "never cached: email bodies"); it
  keeps the draft so another instance can return it.
- **Idempotent.** Keyed by `(user_id, instruction_id)`: drafting the same instruction twice (sequentially,
  concurrently on eight instances, or after a restart) gives one result, one model call when sequential and one
  `artifact.created`. A new instruction on the same thread is a new draft.

## Defaults chosen where the PRD is silent (proposed open-question rows; the merger allocates ids)

| ID | Question | Default taken in these tests | Source |
| --- | --- | --- | --- |
| BQ-TBD | FR-CHN-10 names "50 drafting cases" but the E-MAIL set has 20 drafting cases (31 to 50) and 30 triage cases. Which 50? | The 20 E-MAIL drafting cases plus 30 fixture cases in `services/channels/tests/fixtures/FR_CHN_10_drafting_cases.yaml`, run offline on scripted answers. Suggest the eval set later grows its drafting cases to 50, or the fixture cases move into `evals/`. | PRD 11.6, 19.2 |
| BQ-TBD | How is "invented commitment" decided in CI, where the E-MAIL check `no_invented_commitments` is an autorater? | A deterministic checker (`find_invented`): numbers, dates and links must come from the instruction, the thread or the user's own signature; commitment words (free, discount, waive, refund, guarantee, promise, warranty, pay, no charge, ...) only from the instruction. Paraphrased commitments with none of these markers stay with the E-MAIL autorater (PRD 19.3 "deterministic checks first"). | PRD 11.4 Content, 19.3 |
| BQ-TBD | What happens to a draft that invents something? | PRD 11.4 "unclear points are asked, not guessed": the draft is not offered; the user is asked (`needs_you` with the findings). At most one regeneration first (at most 2 model calls), and only a clean answer ships. | PRD 11.4, 6.6 |
| BQ-TBD | Does a commitment the other party asks for in the thread count as supported? | No. Only the instruction can add a commitment, so a thread asking for a discount does not let the draft offer one. Restating the other side's request with such a word (e.g. "you asked for a refund") is asked back to the user: a safe false positive. | PRD 11.4 Content |
| BQ-TBD | Does drafting save a Gmail draft (`create_draft`, T1)? | No. Drafting makes a Tilo artifact (`artifact.created`, PRD 11.6 Events) and nothing else: no outbox entry, no Gmail draft, no send, no preview message. The preview is FR-CHN-11 and the send FR-CHN-13; FR-CON-04 only says the Gmail adapter can make drafts. | PRD 11.2, 11.6, FR-CON-04, FR-CHN-11, FR-CHN-13 |
| BQ-TBD | Does a `Reply-To` header pick the recipient of "reply-to-sender"? | No. The reply goes to the From address of the latest message not sent by the user. A Reply-To outside the thread would be a new recipient, which is T3 (FR-CHN-12) and never added by drafting. | PRD 11.4 Threading and Formats, 16.2 |
| BQ-TBD | Which formats does FR-CHN-10 draft? | Reply (default) and reply-all. Forward and new email always add a recipient, so they belong to FR-CHN-12's T3 path; these tests do not pin them. | PRD 11.4 Formats, FR-CHN-12 |
| BQ-TBD | How does the model return a draft? | JSON `{"body", "questions"}`; recipients, subject and headers are never read from it. | PRD 11.4, 16.3 items 1 and 3 |
| BQ-TBD | What does drafting do with a thread the safety provider flags? | It still drafts if asked (the user gave the instruction), but marks the result `flagged` and the draft `safety_flag`, so a send of it is T3 and it can never be auto-sent. | PRD 11.4 Injection, 16.2, `config/autonomy.yaml` |
| BQ-TBD | Is the user's signature a source of facts? | Yes, for facts (its phone number is not invented); never for commitments. | PRD 11.4 Inputs |
| BQ-TBD | Is a drafted reply a `reply_handled` unit? | No; a reply is handled when it is sent (FR-CHN-13). PRD 14.2 counts unverified units as zero. | PRD 14.2, BQ-03 |
| BQ-TBD | What is the idempotency key? | `(user_id, instruction_id)`, the id of the user's instruction (the `channel.message_in` it came in on WhatsApp). Redrafting after Edit is a new instruction. | PRD 11.4 Preview, `contracts/outbox.rules.md` OB-01 `instruction_id` |
| BQ-TBD | How are user-added presets stored? | Not pinned; only the five PRD presets are. | PRD 11.4 Presets, FR-CHN-15 |
