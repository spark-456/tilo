# FR-CHN-09: public API pinned by the triage tests (overridable)

FR-CHN-09 "Triage into five categories with priority and learning from corrections". The acceptance test is
"Pilot: ≥ 85% agreement with the user's own labels after day 1" (PRD 11.6). A pilot number cannot be proven in
CI, so the tests prove the parts it is made of: every mail lands in exactly one of the five categories with a
priority; corrections are kept and change later triage; and the agreement figure is computed as below, on the
30 E-MAIL triage cases (PRD 19.2: "≥ 85% triage"). Sources: PRD 11.2, 11.3, 11.4 (Injection row), 13.1
(Preferences layer holds triage corrections; email bodies are never cached), 14.2 and BQ-03 (`mail_triaged`
units), 16.2 ("flagged mail can never be auto-answered"), 16.3 items 1 to 4, 16.5, SEC-04, SEC-05, PL-01, PL-04,
EFF-01, and `services/channels/CLAUDE.md`. FR-CHN-08 calls triage as `triage(user_id, message_id)`
(`API_FR_CHN_08.md`, tests/FR-CHN-08 at c2c70a5).

These are the tests' assumptions, and the architect or builder may override them. If a name or shape below
changes, update the tests in the same PR and say so in the review. The tests import only what is listed here.
The test doubles are in `_chn09_lib.py`.

## `tilo_channels.triage` (new module)

```python
CATEGORIES: tuple[str, ...]   # exactly {"needs_reply", "needs_action", "fyi", "newsletter_promo", "suspicious"}
                              # (PRD 11.3, spelled as the E-MAIL eval ground truth spells them)
PRIORITIES: tuple[str, ...]   # exactly {"high", "normal", "low"} (the E-MAIL ground truth levels)
PILOT_AGREEMENT_TARGET = 0.85 # PRD 11.6 FR-CHN-09, 19.2 E-MAIL
PILOT_WARMUP_S = 86_400       # "after day 1": the first 24 h after the user's Autopilot start are not counted

class MailReader(Protocol):   # the quarantined reader (PRD 16.3 item 3): read-only, no side-effect method
    def get_message(self, user_id: str, message_id: str) -> dict
        # {"message_id", "thread_id", "from" (may carry a display name), "to": [..], "cc": [..],
        #  "subject", "body" (plain text), "headers": {name: value}}; everything but the ids is untrusted

class PreferenceStore(Protocol):   # P7 preferences (PRD 13.1); JSON-able documents, per user
    def get(self, user_id: str) -> dict | None
    def put(self, user_id: str, value: dict) -> None

class TriageStore(Protocol):       # triage results; JSON-able documents
    def get(self, user_id: str, message_id: str) -> dict | None
    def create(self, user_id: str, message_id: str, value: dict) -> bool   # atomic set-if-absent
    def put(self, user_id: str, message_id: str, value: dict) -> None
    def items(self, user_id: str) -> list[tuple[str, dict]]                # (message_id, value)

@dataclass(frozen=True)
class TriageResult:
    message_id: str
    category: str      # one of CATEGORIES
    priority: str      # one of PRIORITIES
    source: str        # where the category came from: "model" | "rule" | "user" | "safety" | "fallback"
    flagged: bool      # the safety provider flagged this mail

@dataclass(frozen=True)
class AgreementReport:
    agreed: int
    labelled: int
    rate: float | None     # agreed / labelled; None when labelled == 0
    meets_target: bool     # rate is not None and rate >= PILOT_AGREEMENT_TARGET

class Triage:
    def __init__(self, *, reader: MailReader,
                 model: ModelProvider,      # the "autopilot" role (config/models.yaml) through the Router in
                                            # production, like tilo_api.deps._RoleModel; only .generate is called
                 safety: SafetyProvider,    # tilo_providers SafetyProvider; only .check is called
                 preferences: PreferenceStore, results: TriageStore,
                 clock: Callable[[], float], emit: Callable[[dict], None] = ...) -> None
    def __call__(self, user_id: str, message_id: str) -> TriageResult    # the FR-CHN-08 `triage` callable
    def triage(self, user_id: str, message_id: str) -> TriageResult
    def correct(self, user_id: str, message_id: str, *, category: str | None = None,
                priority: str | None = None) -> None      # a relabel; the user's own label for this message
    def mute(self, user_id: str, message_id: str) -> None # "don't ask me about these"
    def add_vip(self, user_id: str, address: str) -> None # the user's VIP list (PRD 11.3 Priority)
    def agreement_records(self, user_id: str) -> list[dict]
        # one per triaged message: {"message_id", "triaged_at": float (clock at first triage),
        #  "predicted": the category first given, never changed by a later correction,
        #  "label": the user's latest corrected category, or None}

def pilot_agreement(records: Iterable[Mapping], *, started_at: float) -> AgreementReport
```

## Behaviour the tests check

- **Categories and priority.** Every result has exactly one category from `CATEGORIES` and one priority from
  `PRIORITIES`. The model is asked for JSON `{"category": ..., "priority": ...}` in `GenerateResponse.text`. A
  valid answer with no rule, VIP or flag is taken as given (`source == "model"`). The same mail with the same
  model answer always gives the same result, on any instance.
- **Untrusted mail (PRD 11.4, 16.3).** The safety provider screens the subject, the body and the From header of
  every mail. A flagged mail is `suspicious` with `flagged` True whatever the model or a user rule says
  (`source == "safety"`). Mail text reaches the model only in `GenerateRequest.prompt`, never in `system`; the
  `system` text comes from a template under `prompts/autopilot/` (PL-04); no tools are offered (SEC-05).
  Triage never writes preferences: only `correct`, `mute` and `add_vip` do, so text in one mail, or extra keys
  in the model's answer, cannot change how any other mail is triaged. The module imports no sender, outbox,
  connector or network client; triage emits no event type marked `side_effect: true`.
- **Fallback.** An empty, non-JSON or wrongly shaped answer, a category or priority outside the sets, or a
  tool-call answer gives `source == "fallback"` with a category that is never `needs_reply` (no ask, no reply
  flow) and never `newsletter_promo` (never buried). Suggested default: `fyi`, `normal`. If the model or the
  safety provider raises, triage either raises with nothing stored and nothing emitted, or returns a result
  that is not `needs_reply` (and, for a safety failure, not `source == "model"`): fail closed.
- **Learning (PRD 11.3, 13.1).** A correction becomes a sender rule in the preference store: later mail from the
  same address (bare address, case-insensitive; never a display name) gets the corrected category
  (`source == "rule"`) and, if given, priority, ahead of the model, except that a model `suspicious` is never overridden (BQ-132). The latest correction for an address wins.
  The corrected message itself then triages to the user's label (`source == "user"`). `mute` means later mail
  from that address is never `needs_reply` (it becomes `fyi`). A VIP address gets priority `high`. Rules are per
  user and survive a restart. An unknown category or priority, or a correction with neither, raises
  `ValueError` and changes nothing.
- **Agreement.** `pilot_agreement` counts records with a label and `triaged_at >= started_at + PILOT_WARMUP_S`;
  a record agrees when `predicted == label`. Category only; priority is not part of agreement.
- **Idempotent.** A message triaged twice (sequentially, concurrently, or on two instances sharing the stores)
  yields one result, one model call when sequential, and one `mail_triaged` unit. Gmail message ids are per
  mailbox, so results are keyed by `(user_id, message_id)`.
- **Events.** Each newly triaged message emits exactly one `building.completed` with
  `data == {"unit_type": "mail_triaged", "unit_count": 1}` (BQ-03) when the result is not a fallback; a fallback
  emits at most one. Anything emitted is `{type, data, ...}` with a registered type and valid data, and carries
  no subject, body, sender address or display name.
- **Privacy.** Logs, events, the preference store and the result store never hold a subject or a body (PRD 13.1
  "never cached: email bodies", 16.5). Logs never hold a sender address or display name either.

## Defaults chosen where the PRD is silent (proposed open-question rows; the merger allocates ids)

| ID | Question | Default taken in these tests | Source |
| --- | --- | --- | --- |
| BQ-TBD | How are the five categories and the priority spelled? | `needs_reply`, `needs_action`, `fyi`, `newsletter_promo`, `suspicious`; priority `high`, `normal`, `low` (the E-MAIL eval ground truth). PRD 11.3's "score" is read as these three levels. | PRD 11.3, 19.2 |
| BQ-TBD | How is "≥ 85% agreement with the user's own labels after day 1" computed? | Over messages the user labelled (a correction, including one that confirms the category) and first triaged at least 24 h after the user's Autopilot start; agreement = the category first given equals the user's label. Category only. Unlabelled mail is not counted, so silence is never agreement. | PRD 11.6, 19.2, EV-13 ("after the first pilot day") |
| BQ-TBD | What does a correction change? | It becomes a per-user sender rule in P7 preferences, keyed on the bare From address (case-insensitive), that takes precedence over the model for later mail from that address; the latest correction wins. No domain-wide rules. | PRD 11.3, 13.1 |
| BQ-TBD | What does "don't ask me about these" do? | Later mail from that address is never `needs_reply`; it goes to the digest as `fyi`. | PRD 11.3 (Learning, Delivery) |
| BQ-TBD | How does the VIP list change priority? | A VIP address always gets `high`. Category is unchanged. | PRD 11.3 |
| BQ-TBD | What does triage do with mail the safety provider flags? | `suspicious` with `flagged` true, ahead of any model answer or user rule, so it is never auto-answered. | PRD 11.4, 16.2, 16.3 |
| BQ-TBD | What is the safe fallback for an unusable model answer? | Never `needs_reply` and never `newsletter_promo`; suggested `fyi` / `normal`, marked `source: fallback`. | PRD 16.3, 11.3 |
| BQ-TBD | Is a fallback a `mail_triaged` unit? | Not pinned (at most one). PRD 14.2 counts failed or unverified units as zero, so the suggested default is no unit. | PRD 14.2, BQ-03 |
| BQ-TBD | Which headers are screened? | Subject, body and From (with its display name) at least. | PRD 11.4, 16.3 item 2 |
