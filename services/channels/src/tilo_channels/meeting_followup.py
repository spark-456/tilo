"""tilo_channels.meeting_followup: after the Owner confirmed a meeting's minutes, a drafted (never sent) minutes email
to the attendees the Owner picks and a nudge per open item (FR-MTG-08, FR-MTG-08b; PRD 10.4, 11.4; PE-03, PE-05, PE-07,
PE-09, PE-19 to PE-22; BQ-MTG08-1 to -8, BQ-MTG08B-1 to -6).

Only the meeting's Owner drafts, and only for a `minuted` meeting whose minutes the Owner confirmed. Content is what
the Owner confirmed: the summary, the `verified` decisions and the action items whose work item is `open`, confirmed
by the Owner, of this meeting and assigned to the person the minutes name. Recipients come from the directory
(tilo-api), never from a model, the minutes or the meeting text. The FR-CHN-10 `Checker` runs on every body with the
confirmed text as its only source of facts and no instruction, so no commitment word is granted: one is allowed only
inside a verbatim repeat of a confirmed entry. A body that repeats text the Owner did not confirm is refused
(`needs_you`, never sendable). A draft is a new thread-less email: `Autopilot.preview` makes it T3 (new recipients),
L1, and a card waits for the Owner's approval. This module imports no connector, outbox, policy engine or network
client and never sends. Cards and prompts hold the meeting text; no log line or event does.

Fail closed (FR-MTG-08b): a `flagged` that is not `False` reads as flagged (PE-21); more entries than minutes.schema
allows draw nothing and read no work item; the idempotency key is a JSON array, so no part can forge another.

Residuals (FR-MTG-08c, BQ-MTG08C-1 to -7): a body too long to read once cleaned is a finding, not an exception, and one
failed nudge never aborts the others; an entry that holds a commitment word is a verbatim repeat only after a label
lead-in ("Action items:", not "Approved:"); the title is checked against the confirmed text.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from tilo_providers.interfaces import GenerateRequest, ModelProvider, SafetyProvider
from tilo_providers.prompts import load_prompt

from tilo_channels.autopilot import Autopilot, DraftContext, Preview
from tilo_channels.drafting import (
    EMIT_LEASE,
    MAX_ATTEMPTS,
    MAX_OUTPUT_TOKENS,
    MAX_QUESTIONS,
    QUESTION_CAP,
    ROLE,
    SCREEN_CAP,
    DraftResult,
    DraftStore,
    _address,
    _header,
    _parse,
    _render,
    _result,
)
from tilo_channels.drafting_check import Checker, Finding, clean

__all__ = ["MeetingFollowUp"]

# minutes.schema.json: 240 characters per text (a longer one is cut and its rest only screened); at most 8 summary
# points, 30 decisions and 60 action items (more of any: no draft, before any work item is read).
TEXT_CAP, MAX_SUMMARY, MAX_DECISIONS, MAX_ACTIONS = 240, 8, 30, 60
SUBJECT_CAP = 120
MINUTES_CAP = 40_000  # chars of a minutes body and its answer: a maximal minutes is ~23.5k (BQ-MTG08B-5)
MAX_LABEL_WORDS = 6  # a lead-in that is only a label: this many words, all of LABEL_WORDS (BQ-MTG08C-2)
LABEL_WORDS = frozenset(
    "a an the this that item items reminder reminders about for on of from action actions decision decisions summary "
    "note notes follow following up here is are your our meeting minutes task tasks open next step steps point points "
    "re regarding".split()
)
INSTRUCTION = "Follow up a confirmed meeting"  # the card's stored instruction: no meeting text

_LOG = logging.getLogger(__name__)
# Where a verbatim repeat of an entry may start: the line start, after a colon, a list marker or "1. ".
_LEAD = r"(?:^|(?<=: )|(?<=- )|(?<=\* )|(?<=• )|(?<=\d\. )|(?<=\d\d\. ))"


class MeetingReader(Protocol):
    def get(self, user_id: str, meeting_id: str) -> Mapping[str, Any] | None: ...  # meeting.schema record


class MinutesReader(Protocol):
    def get(self, user_id: str, artifact_id: str, version: int) -> Mapping[str, Any] | None: ...  # minutes.schema


class WorkItemReader(Protocol):
    def get(self, user_id: str, work_item_id: str) -> Mapping[str, Any] | None: ...  # work_item.schema record


class AddressBook(Protocol):
    def address(self, person_id: str) -> str | None: ...  # resolved server side by tilo-api (PE-09, PE-20)


def _text(value: Any, cap: int, rests: list[str]) -> str:
    """A confirmed text as the model and the screen see it: cut to `cap`, rendered, on one line. The raw rest is
    screened too."""
    raw = value if isinstance(value, str) else ""
    if len(raw) > cap:
        rests.append(raw[cap:])
    return " ".join(_render(raw, "body", cap).split())


def _norm(text: str) -> str:
    return " ".join(clean(text).split())


def _lists(minutes: Mapping[str, Any]) -> tuple[list[Mapping], list[Mapping], list[Mapping]] | None:
    """(summary points, decisions, action items) as mappings, or None when one list has more entries than the schema
    allows. Checked first: nothing is read or screened for minutes that are too large to write safely."""
    out: list[list[Mapping]] = []
    for key, cap in (("summary", MAX_SUMMARY), ("decisions", MAX_DECISIONS), ("action_items", MAX_ACTIONS)):
        raw = minutes.get(key)
        raw = raw if isinstance(raw, (list, tuple)) else []
        if len(raw) > cap:
            return None
        out.append([e for e in raw if isinstance(e, Mapping)])
    return out[0], out[1], out[2]


def _neutral(label: str) -> bool:
    """True when the words of a lead-in are only a label ("Action items", "A reminder about this item"): no word that
    could say what the entry after it means (approved, agreed, grant, yes, please)."""
    words = re.findall(r"[^\W\d_]+", label)
    return len(words) <= MAX_LABEL_WORDS and set(words) <= LABEL_WORDS


def _lead_in(lines: str, start: int) -> str:
    """The words in front of the entry at `start` on its line; with none, the heading line above it (the nearest line
    with text) when that ends in a colon."""
    begin = lines.rfind("\n", 0, start) + 1
    before = lines[begin:start]
    if re.search(r"[^\W\d_]", before) or begin == 0:
        return before
    above = lines[:begin].rstrip("\n").rsplit("\n", 1)[-1]
    return above if above.rstrip().endswith(":") else ""


def _unquoted(body: str, confirmed: Sequence[str], checker: Checker) -> str:
    """The body, as the checker reads it, with every verbatim repeat of a confirmed entry cut out. A repeat is the whole
    entry, at a line start or after a list marker or a colon, and it ends its line (a full stop may follow). Inside a
    longer sentence an entry is no repeat: a commitment word the Owner confirmed is not one the body may use. Nor is it
    when the entry holds a commitment word and a lead-in says more than a label ("Approved: <entry>")."""
    lines = "\n".join(" ".join(line.split()) for line in clean(body, MINUTES_CAP).split("\n"))
    entries = sorted({n for c in confirmed if (n := _norm(c))}, key=len, reverse=True)
    if not entries:
        return lines
    risky = {e for e in entries if any(f.kind == "commitment" for f in checker.find(e))}
    pattern = re.compile(_LEAD + "(?:" + "|".join(map(re.escape, entries)) + r")(?=[.;!]?$)", re.MULTILINE)

    def cut(match: re.Match[str]) -> str:
        keep = match.group(0) in risky and not _neutral(_lead_in(lines, match.start()))
        return match.group(0) if keep else ""

    return pattern.sub(cut, lines)


def _audit(checker: Checker, body: str, confirmed: Sequence[str]) -> list[Finding]:
    """The checker's findings for `body`. The checker holds no instruction, so it grants no commitment word; the
    commitment words are read again on the body without its verbatim confirmed entries, and each one left is a
    finding. Numbers, dates, contacts and obfuscations are read on the whole body. A body too long to read once it is
    cleaned is a finding too, never an exception (one bad item must not abort the others)."""
    try:
        found = [f for f in checker.find(body) if f.kind != "commitment"]
        return found + [f for f in checker.find(_unquoted(body, confirmed, checker)) if f.kind == "commitment"]
    except ValueError:
        return [Finding("obfuscation", "text too long to check")]


def _repeats(body: str, unconfirmed: Sequence[str], confirmed: Sequence[str]) -> list[Finding]:
    """Text the Owner did not confirm that the body repeats (whole words, as the checker reads text). A text that a
    confirmed text holds is not unconfirmed content."""
    seen, held = _norm(body), _norm("\n".join(confirmed))
    found = []
    for text in unconfirmed:
        norm = _norm(text)
        if norm and norm not in held and re.search(rf"(?<!\w){re.escape(norm)}(?!\w)", seen):
            found.append(Finding("unconfirmed", text))
    return found


class MeetingFollowUp:
    def __init__(
        self,
        *,
        meetings: MeetingReader,
        minutes: MinutesReader,
        work_items: WorkItemReader,
        directory: AddressBook,
        model: ModelProvider,
        safety: SafetyProvider,
        drafts: DraftStore,
        autopilot: Autopilot,
        mailbox: Callable[[str], str | None],
        clock: Callable[[], float],
        emit: Callable[[dict], None] = lambda part: None,
    ) -> None:
        self._meetings, self._minutes, self._work_items, self._directory = meetings, minutes, work_items, directory
        self._model, self._safety, self._drafts, self._autopilot = model, safety, drafts, autopilot
        self._mailbox, self._clock, self._emit = mailbox, clock, emit
        self._system = load_prompt(ROLE, "followup_system.md")

    def draft_minutes_email(
        self, user_id: str, meeting_id: str, *, recipients: Sequence[str], request_id: str
    ) -> Preview | None:
        """The T3 card of a new email with the confirmed minutes to the attendees the Owner picked, or None."""
        found = self._confirmed(user_id, meeting_id)
        if found is None or not request_id or not isinstance(recipients, (list, tuple)):
            return None
        meeting, minutes, owner_mailbox = found
        lists = _lists(minutes)
        if lists is None:
            return None  # too large to write safely: nothing read, screened or drafted
        attendees = {a.get("user") for a in meeting.get("attendees") or [] if isinstance(a, Mapping)}
        picks = list(dict.fromkeys(recipients))
        if not picks or not all(isinstance(p, str) and p in attendees for p in picks):
            return None  # nobody picked, or someone who was no attendee: the Owner's audience is never changed
        addresses = [_address(self._directory.address(p) or "") for p in picks]
        if None in addresses:
            return None
        to = tuple(dict.fromkeys(a for a in addresses if a))
        rests: list[str] = []
        summary = [t for s in lists[0] if (t := _text(s.get("text"), TEXT_CAP, rests))]
        decisions, unconfirmed = list[str](), list[str]()
        for d in lists[1]:
            if t := _text(d.get("text"), TEXT_CAP, rests):
                (decisions if d.get("state") == "verified" else unconfirmed).append(t)
        items, held = self._open_items(user_id, meeting_id, lists[2], rests)
        unconfirmed += held["unconfirmed"]
        confirmed = [*summary, *decisions, *[i["text"] for i in items]]
        fields = {
            "summary": "\n".join(summary) or "(none)",
            "decisions": "\n".join(f"- {d}" for d in decisions) or "(none)",
            "items": "\n".join(f"- {i['text']}" for i in items) or "(none)",
        }
        title = _header(meeting.get("title"), SUBJECT_CAP)
        subject = f"Minutes: {title}" if self._title_is_clear(title, confirmed) else "Meeting minutes"
        key = self._key("minutes", meeting_id, request_id, *sorted(to))
        flagged = any(i["flagged"] for i in items) or minutes.get("flagged") is not False
        return self._run(
            user_id, key, "minutes_task.md", fields, confirmed, unconfirmed, rests, flagged, to, subject, owner_mailbox
        )

    @staticmethod
    def _title_is_clear(title: str, confirmed: Sequence[str]) -> bool:
        """The title is its own source of nothing: a link, address, number, commitment word or obfuscation in it that
        the confirmed text does not hold gives the generic subject (BQ-MTG08C-6). "Q3" or "v2" is a label."""
        checked = re.sub(r"\b[A-Za-z]{1,2}\d{1,2}\b", " ", title)
        found = Checker(instruction="", thread=confirmed, cap=MINUTES_CAP).find(checked)
        return bool(title) and not [f for f in found if f.kind != "date"]

    def draft_nudges(self, user_id: str, meeting_id: str, *, request_id: str) -> list[Preview]:
        """One T3 card per confirmed open item: a new email to its assignee about that item alone."""
        found = self._confirmed(user_id, meeting_id)
        if found is None or not request_id:
            return []
        meeting, minutes, owner_mailbox = found
        lists = _lists(minutes)
        if lists is None:
            return []  # at most MAX_ACTIONS items: no work item is read for more
        everything = [_text(s.get("text"), TEXT_CAP, []) for s in [*lists[0], *lists[1]]]
        items, held = self._open_items(user_id, meeting_id, lists[2], [])
        everything += held["all"]
        cards: list[Preview] = []
        for it in items:
            owner = it["owner"]
            address = _address(self._directory.address(owner) or "")
            if address is None:
                continue  # an assignee Tilo cannot address gets no nudge (the Owner's list is never guessed)
            rests: list[str] = []
            text = _text(it["raw"], TEXT_CAP, rests)
            key = self._key("nudge", meeting_id, request_id, it["work_item_id"])
            subject = f"Reminder: {_header(text, SUBJECT_CAP)}"
            flagged = it["flagged"] or minutes.get("flagged") is not False
            try:
                card = self._run(
                    user_id, key, "nudge_task.md", {"item": text}, [text], everything, rests, flagged, (address,),
                    subject, owner_mailbox,
                )  # fmt: skip
            except Exception as error:  # one bad item never aborts the other nudges; the type only, never the message
                _LOG.warning("meeting follow-up %s: failed (%s)", key, type(error).__name__)
                continue
            if card is not None:
                cards.append(card)
        return cards

    # -- what the Owner confirmed ---------------------------------------------------------------------------------

    def _confirmed(self, user_id: str, meeting_id: str) -> tuple[Mapping[str, Any], Mapping[str, Any], str] | None:
        """(meeting, minutes, the Owner's mailbox) only for the meeting's Owner, a `minuted` meeting whose minutes the
        Owner confirmed and whose minutes artifact names this meeting; None otherwise, nothing recorded."""
        if not (isinstance(user_id, str) and isinstance(meeting_id, str) and self._autopilot.owns(user_id)):
            return None
        meeting = self._meetings.get(user_id, meeting_id)
        if not isinstance(meeting, Mapping) or meeting.get("id") != meeting_id or meeting.get("owner") != user_id:
            return None
        confirmed, ref = meeting.get("minutes_confirmed_by"), meeting.get("minutes")
        if meeting.get("status") != "minuted" or not isinstance(confirmed, Mapping) or confirmed.get("by") != user_id:
            return None
        if not isinstance(ref, Mapping) or not isinstance(ref.get("artifact_id"), str):
            return None
        version = ref.get("version")
        minutes = self._minutes.get(user_id, ref["artifact_id"], version) if isinstance(version, int) else None
        if not isinstance(minutes, Mapping) or minutes.get("meeting_id") != meeting_id:
            return None
        mailbox = self._mailbox(user_id)
        return (meeting, minutes, mailbox) if isinstance(mailbox, str) and mailbox else None

    def _open_items(
        self, user_id: str, meeting_id: str, actions: Sequence[Mapping[str, Any]], rests: list[str]
    ) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
        """The confirmed open items (verified, work item `open`, confirmed by the Owner, of this meeting, assigned to
        the person the minutes name), and the texts of every other item. `owner` is the work item's, `flagged` is True
        unless the work item says `False` (PE-21)."""
        items, held = [], {"unconfirmed": list[str](), "all": list[str]()}
        for ai in actions:
            text = _text(ai.get("text"), TEXT_CAP, rests)
            held["all"].append(text)
            work_id = ai.get("work_item_id")
            work = self._work_items.get(user_id, work_id) if isinstance(work_id, str) else None
            if not self._is_open(user_id, meeting_id, ai, work):
                held["unconfirmed"].append(text)
                continue
            assert isinstance(work, Mapping) and isinstance(work_id, str)
            items.append(
                {
                    "raw": ai.get("text"),
                    "text": text,
                    "owner": work["owner"],
                    "work_item_id": work_id,
                    "flagged": work.get("flagged") is not False,
                }
            )
        return items, held

    @staticmethod
    def _is_open(user_id: str, meeting_id: str, action: Mapping[str, Any], work: Mapping[str, Any] | None) -> bool:
        if not isinstance(work, Mapping) or action.get("state") != "verified" or work.get("status") != "open":
            return False
        owner = work.get("owner")
        if not isinstance(owner, str) or owner != action.get("owner"):
            return False  # the minutes and the work item name different people: no nudge, no line (fail closed)
        by, source = work.get("confirmed_by"), work.get("source")
        ours = isinstance(source, Mapping) and source.get("ref") == f"{meeting_id}#{action.get('id')}"
        return ours and isinstance(by, Mapping) and by.get("by") == user_id

    # -- drafting -------------------------------------------------------------------------------------------------

    @staticmethod
    def _key(kind: str, *parts: str) -> str:
        """Injective in (kind, parts): a JSON array, so no text in a part can read as another part."""
        return f"mtg08-{kind}-" + hashlib.sha256(json.dumps([kind, *parts]).encode()).hexdigest()[:32]

    def _run(
        self,
        user_id: str,
        instruction_id: str,
        template: str,
        fields: Mapping[str, str],
        confirmed: Sequence[str],
        unconfirmed: Sequence[str],
        rests: list[str],
        flagged: bool,
        to: tuple[str, ...],
        subject: str,
        mailbox: str,
    ) -> Preview | None:
        doc = self._drafts.get(user_id, instruction_id)
        if doc is None:
            made = self._make(template, fields, confirmed, unconfirmed, rests, flagged, to, subject)
            if self._drafts.create(user_id, instruction_id, made):  # atomic: the first writer's draft is the result
                _LOG.info("meeting follow-up %s: %s", instruction_id, made["status"])
            doc = self._drafts.get(user_id, instruction_id) or made
        self._announce(user_id, instruction_id, doc)
        if doc["status"] == "failed":
            return None
        result: DraftResult = _result(instruction_id, doc)
        context = DraftContext(instruction_id, None, INSTRUCTION, mailbox, "new")  # thread-less: no thread id
        return self._autopilot.preview(user_id, context, result)

    def _announce(self, user_id: str, instruction_id: str, doc: Mapping[str, Any]) -> None:
        """One artifact.created per stored ready draft, as the FR-CHN-10 drafter does it: an `#emitted` marker, and one
        caller per EMIT_LEASE window (an atomic claim) emits while it is missing."""
        if not doc.get("draft") or self._drafts.get(user_id, f"{instruction_id}#emitted") is not None:
            return
        window = int(max(0.0, self._clock() - doc["drafted_at"]) // EMIT_LEASE)
        if self._drafts.create(user_id, f"{instruction_id}#emit{window}", {}):
            artifact = {"artifact_id": doc["draft"]["artifact_id"], "version": 1}
            self._emit({"type": "artifact.created", "data": {"artifact": artifact}})
            self._drafts.create(user_id, f"{instruction_id}#emitted", {})

    def _make(
        self,
        template: str,
        fields: Mapping[str, str],
        confirmed: Sequence[str],
        unconfirmed: Sequence[str],
        rests: list[str],
        flagged: bool,
        to: tuple[str, ...],
        subject: str,
    ) -> dict[str, Any]:
        """The model writes the body from the confirmed text only; the screen sees exactly the prompt plus the raw rest
        of any cut text (up to SCREEN_CAP, more is flagged) and the subject. Raises: nothing stored or emitted."""
        prompt = load_prompt(ROLE, template, {**fields, "problems": "none"})
        screened, room = [prompt], SCREEN_CAP
        for rest in rests:
            screened.append(rest[: max(0, room)])
            room -= len(rest)
        flagged = self._safety.check("\n".join([*screened, subject]))["flagged"] or room < 0 or flagged
        doc: dict[str, Any] = {"drafted_at": self._clock(), "flagged": flagged, "draft": None, "findings": []}
        # The Owner's confirmed text is the only source of facts; no instruction, so no commitment word is granted.
        checker = Checker(instruction="", thread=confirmed, cap=MINUTES_CAP)
        findings: list[Finding] = []
        for _ in range(MAX_ATTEMPTS):
            request = GenerateRequest(
                system=self._system, prompt=prompt, json_mode=True, max_output_tokens=MAX_OUTPUT_TOKENS
            )
            response = self._model.generate(request)
            if response is None:  # the Router's own screen blocked the call: fail closed
                return {**doc, "status": "failed", "flagged": True, "questions": []}
            parsed = None if response.tool_calls else _parse(response.text, MINUTES_CAP)
            if parsed is None or self._safety.check(parsed[0] or "\n".join(parsed[1]))["flagged"]:
                return {**doc, "status": "failed", "questions": []}
            body, questions = parsed
            if questions:  # unclear points are asked, not guessed; one holding an unsupported fact is never shown
                checked = [(q, [f for f in checker.find(q) if f.kind != "commitment"]) for q in questions]
                shown = [{"kind": f.kind, "text": f.text} for _, found in checked for f in found]
                kept = [q for q, found in checked if not found and len(q) <= QUESTION_CAP][:MAX_QUESTIONS]
                return {**doc, "status": "needs_you", "findings": shown, "questions": kept}
            findings = [*_audit(checker, body, confirmed), *_repeats(body, unconfirmed, confirmed)]
            if not findings:
                draft = {"artifact_id": "art_" + secrets.token_hex(12), "version": 1, "thread_id": None, "mode": "new"}
                draft |= {"to": list(to), "cc": [], "bcc": [], "subject": subject, "in_reply_to": "", "references": ""}
                draft |= {"body": body, "attachments": [], "safety_flag": flagged}
                return {**doc, "status": "ready", "draft": draft, "questions": []}
            prompt = load_prompt(ROLE, template, {**fields, "problems": ", ".join(sorted({f.kind for f in findings}))})
        return {
            **doc,
            "status": "needs_you",
            "findings": [{"kind": f.kind, "text": f.text} for f in findings],
            "questions": [],
        }
