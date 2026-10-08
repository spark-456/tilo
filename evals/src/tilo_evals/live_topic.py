"""`just live-run`: one real end-to-end run on a typed topic (PL-LIVE-E2E, #340; FR-INT-15, FR-INT-02; PRD 6.6 EFF-01,
9.4 HR-1, 10.3). The SAME runner as `just live-e2e` (gate, meter, cap, pipeline, checks, report). Differences: the case
is built in memory from the topic (typed at a prompt, or read from a file: it never passes through a shell), with no
expected outcome; the untrusted topic goes through the safety role (Model Armor, via the provider layer) first and is
refused if that screen is missing, fails or flags it; a person answers questions, the approach and every gate card in
the terminal; no flag approves a T3 gate, and only an interactive terminal can.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import unicodedata
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal

from tilo_providers.config import ProvidersConfig
from tilo_providers.interfaces import ModelProvider, SafetyProvider
from tilo_providers.safety import SAFETY_ROLE, build_safety_provider, reason_category

from . import live_e2e as e2e
from .bank import BankCase

MODEL_ARMOR_NEEDS = (
    "the `safety` role on a `provider: model_armor` profile whose `model` is the template id (config/models.yaml: "
    "armor-default), GOOGLE_CLOUD_PROJECT (the project holding the template), "
    "TILO_MODEL_ARMOR_LOCATION (default asia-southeast1), user ADC and the Model Armor API enabled"
)
TOPIC_FAKED = tuple(item for item in e2e.FAKED if not item.startswith("safety screen"))  # the screen here is real
NL = chr(10)
_BLANKS = re.compile(r"\n\s*\n\s*")  # a run of blank lines is one: a preview cannot push the card off screen
ADHOC = e2e.default_recordings_dir("adhoc")  # git-ignored: a typed topic is the person's own text


def clean(text: Any, *, lines: bool = False) -> str:
    """Model text as the terminal shows it: no C0/C1 control, format or bidi character (only newlines and tabs stay
    when `lines`), so a reply can neither move the cursor nor reorder what the person reads."""
    kept = "".join(c for c in str(text) if unicodedata.category(c)[0] != "C" or (lines and c in "\n\t"))
    return kept if lines else " ".join(kept.split())


_NUMBER_LIST = re.compile(r"\d{1,2}(?:\s*(?:,|;|&|\+|\band\b)\s*\d{1,2}|\s+\d{1,2})+", re.IGNORECASE)


def _numbers(said: str) -> list[int] | None:
    """The numbers of "1 and 2", "1, 2" or "1 2" (two or more), else None (one number or words are not a list)."""
    return [int(n) for n in re.findall(r"\d+", said)] if said.isascii() and _NUMBER_LIST.fullmatch(said) else None


def _clip_at_part(answer: str, limit: int = 300) -> str:
    """Cut at the answers route's limit, on a part boundary when the answer joins several."""
    if len(answer) <= limit:
        return answer
    cut = answer[:limit]
    return cut[: cut.rfind("; ")] if "; " in cut else cut


def _flush_input() -> None:
    """Discard what is waiting in the console's input buffer. Raises if this is not a real console."""
    if os.name == "nt":
        import ctypes  # noqa: PLC0415

        kernel = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
        kernel.GetStdHandle.restype = ctypes.c_void_p
        if not kernel.FlushConsoleInputBuffer(kernel.GetStdHandle(-10)):  # STD_INPUT_HANDLE
            raise OSError("stdin is not a console")
    else:
        import termios  # noqa: PLC0415

        termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)  # type: ignore[attr-defined,unused-ignore]


def drain_stdin() -> bool:
    """True only if the terminal's pending input was discarded. Anything else (stdin not a tty, no API) is False, so the
    caller holds: text pasted or typed before a write card must never be able to answer it."""
    try:
        if not sys.stdin.isatty():
            return False
        _flush_input()
    except Exception:  # noqa: BLE001 - fail closed
        return False
    return True


class TerminalPerson:
    """The person at the terminal (`bank_run.drive`'s `person`); `log` says who decided each thing, for the report."""

    def __init__(self, *, auto_answer: bool = False, auto_approve_t1t2: bool = False,
                 read: Callable[[str], str] = input, write: Callable[[str], None] = print,
                 tty: Callable[[], bool] = sys.stdin.isatty,
                 drain: Callable[[], bool] | None = None) -> None:  # fmt: skip
        self.auto_answer, self.auto_approve_t1t2, self._input, self._write = auto_answer, auto_approve_t1t2, read, write
        self._tty, self.log = tty, list[str]()
        self.decline_reason = ""  # why the person declined the last approach set, said in their words
        self._wgate: Any = None  # CL-LIVE-2 write gate, bound by the run
        self._drain = drain  # discards the input buffer before a write prompt; None or False: the write is held

    def bind_write_gate(self, gate: Any) -> None:
        self._wgate = gate

    def _write_gate(self, card: dict[str, Any]) -> bool | None:
        """A real connector write: only a typed `yes` at an interactive terminal approves it, for exactly the payload
        shown. No flag (`--auto-approve-t1t2`), no piped input, no tier decides. None: not a real write."""
        review = self._wgate.review(card) if self._wgate is not None else None
        if review is None:
            return None
        kind = f"{clean(review.connector)} {clean(review.action)}"
        self._write(
            f"REAL WRITE ({kind}): {'this SENDS mail' if review.action == 'send_email' else 'a real draft or file'}"
        )
        to = clean(", ".join(review.recipients)) or "(none)"
        self._write(f"  to: {to}; destination: {clean(review.destination)}")
        if not review.allowed:
            self._write(f"  held: {clean(review.why)}")
            self.log.append(f"gate {kind}: held ({clean(review.why)})")
            return self._hold()
        self._write(f"  title: {clean(review.title)}; {review.size} characters; payload {review.digest[:12]}")
        self._write(f"  preview: {_BLANKS.sub(NL * 2, clean(review.preview, lines=True))}")
        if not self._tty():
            self._write("a real write needs a person at an interactive terminal; piped input cannot approve it: held")
            self.log.append(f"gate {kind}: held (no interactive terminal)")
            return self._hold()
        self._write(
            f"  writing to: {to}; destination: {clean(review.destination)}"
        )  # above the prompt, whatever the preview did
        if not self._flushed():  # last thing before the prompt: nothing queued earlier may answer it
            self._write("could not discard input queued before this card (not a real terminal?): held")
            self.log.append(f"gate {kind}: held (queued input could not be discarded)")
            return self._hold()
        said = self._read("type yes to write exactly this (anything else holds it): ")
        ok = self._wgate.approve(review, said=said or "", interactive=True)
        self.log.append(f"gate {kind}: {'approved by a typed yes' if ok else 'held'} (the person, at the terminal)")
        return True if ok else self._hold()

    def _flushed(self) -> bool:
        try:
            return bool(self._drain is not None and self._drain())
        except Exception:  # noqa: BLE001 - fail closed
            return False

    def _hold(self) -> bool:
        """A held card ends the run: no approval may stay behind for it."""
        self._wgate.clear()
        return False

    def _read(self, prompt: str) -> str | None:
        try:
            return self._input(prompt).strip()
        except EOFError:  # input closed: never read as a yes
            return None

    def _yes(self, prompt: str) -> tuple[bool, str]:
        while (said := self._read(f"{prompt} [y/n]: ")) is not None:
            if said.lower() in ("y", "yes", "n", "no"):
                return said.lower().startswith("y"), self._read("reason: ") or ""
            self._write("answer y or n")
        return False, "no answer (input closed)"

    def _pick(self, prompt: str, options: list[Any], *, many: bool = False) -> Any:
        """An option by its number, the person's own words, or "" (the default); a bad number asks again. With
        `many` (a question that can name several: deliverables) "1 and 2" or "1,2" picks both options, joined."""
        while (said := self._read(prompt)) is not None:
            numbers = _numbers(said) if many and options and all(isinstance(o, str) for o in options) else None
            if numbers is not None:
                if all(1 <= n <= len(options) for n in numbers):
                    return "; ".join(dict.fromkeys(options[n - 1] for n in numbers))
                self._write(f"pick numbers from 1 to {len(options)}, or type words")
                continue
            if not said.isdigit() or not options:  # words, or "" for the default
                return said
            if said.isascii() and 1 <= int(said) <= len(options):
                return options[int(said) - 1]
            self._write(f"pick a number from 1 to {len(options)}, or type words")
        return ""

    def answer(self, question: dict[str, Any]) -> str | None:
        field, suggested = clean(question["field"]), [clean(s) for s in question.get("suggested_answers") or []]
        default = suggested[0] if suggested else None  # None: the Director records its own assumption
        if self.auto_answer:
            self.log.append(f"question {field}: {default!r} (answered by the CLI default, not a person)")
            return default
        self._write(f"Director asks ({field}): {clean(question['text'])}")
        self._write("\n".join(f"  {n}. {option}" for n, option in enumerate(suggested, 1)))
        pick = (
            self._pick(
                "answer (a number, your own words, or empty for the default): ", suggested, many=field == "deliverables"
            )
            or default
        )
        self.log.append(f"question {field}: {pick!r} (answered by the person)")
        return _clip_at_part(pick) if pick else None  # the answers route's own limit

    def explain(self, detail: str) -> None:
        """The answers were refused as a brief: say why in the person's terms; the run asks again, it does not end."""
        self._write(f"That did not fit the brief ({clean(detail)}). Please answer again.")
        self.log.append("answers refused as a brief change: asked again")

    def approach(self, offered: dict[str, Any]) -> str | None:
        options, recommended = offered["approaches"], offered["recommended"]
        self._write("Director proposes:")
        for n, a in enumerate(options, 1):
            credits, mark = a["credits"], " (recommended)" if a["id"] == recommended else ""
            what = f"{clean(a['label'])}: {clean(a['summary'])}"
            self._write(f"  {n}. {what} [{credits['min']}-{credits['max']} credits]{mark}")
        chosen = self._pick("approach number (empty for the recommended): ", options)
        chosen = chosen if isinstance(chosen, dict) else next(a for a in options if a["id"] == recommended)
        ok, why = self._yes(f"approve the approach {clean(chosen['label'])!r}?")
        said = "approved" if ok else "declined"
        self.log.append(f"approach {clean(chosen['id'])}: {said} by the person ({clean(why) or '-'})")
        self.decline_reason = "" if ok else clean(why)[:200]
        return chosen["id"] if ok else None

    def gate(self, card: dict[str, Any]) -> bool:
        if (real_write := self._write_gate(card)) is not None:
            return real_write
        gate = card.get("gate") or {}
        action = gate.get("action") or {}
        tier, kind = gate.get("risk_tier"), clean(action.get("type", "?"))
        if self.auto_approve_t1t2 and tier in ("T1", "T2"):  # a T3 or an unknown tier always asks (PRD 10.3)
            self.log.append(f"gate {tier} {kind}: approved by --auto-approve-t1t2 (a CLI flag, not a person)")
            return True
        self._write(f"gate card ({tier or 'tier unknown'}, {kind}): {clean(card.get('what_happened', ''))}")
        self._write(f"  exactly: {clean(action.get('exact') or '(not stated)')}")  # deterministic, from the send itself
        to = clean(", ".join(map(str, gate.get("recipients") or []))) or "(none)"
        self._write(f"  to: {to}; destination: {clean(action.get('destination') or '(none)')}")
        if tier not in ("T1", "T2") and not self._tty():
            self._write("a T3 gate needs a person at an interactive terminal; piped input cannot approve it: held")
            self.log.append(f"gate {tier} {kind}: held (no interactive terminal; piped input never approves T3)")
            return False
        ok, why = self._yes("approve this step?")
        self.log.append(f"gate {tier} {kind}: {'approved' if ok else 'held'} by the person ({clean(why) or '-'})")
        return ok


def _refuse(code: str, message: str) -> e2e.LiveE2ERefused:
    return e2e.LiveE2ERefused(code, message)


def _safety_note(config: ProvidersConfig) -> str:
    """The live screen the config names, or a refusal that says what it needs: nothing goes out unscreened."""
    role = config.roles.get(SAFETY_ROLE)
    profile = config.profiles.get(role.primary) if role else None
    if role is None or profile is None or profile.provider != "model_armor":
        raise _refuse("safety_unavailable", f"no live safety screen. It needs {MODEL_ARMOR_NEEDS}")
    return f"safety role, profile {role.primary} (Model Armor template {profile.model})"


def _screen(config: ProvidersConfig, recordings: Path, text: str, safety: SafetyProvider | None) -> SafetyProvider:
    """The topic through the safety screen before any model call: flagged, or a screen that cannot run, refuses.
    There is no fallback: an error is a refusal, never another (weaker) screen."""
    try:
        screen = safety if safety is not None else build_safety_provider(config, fixtures_dir=recordings)
        result = screen.check(text)
    except Exception as error:  # noqa: BLE001 - fail closed; the error's text is never shown
        why = f"the safety screen could not run ({type(error).__name__}). It needs {MODEL_ARMOR_NEEDS}"
        raise _refuse("safety_unavailable", why) from None
    if result["flagged"]:
        category = reason_category(result["reason"]) or "other"
        raise _refuse("unsafe_topic", f"the safety screen flagged the topic ({category}); nothing was sent")
    return screen


def run_topic(
    topic: str, *, mode: Literal["live", "dry-run"] = "live", max_credits: float = e2e.DEFAULT_MAX_CREDITS,
    environ: Mapping[str, str] | None = None, models_path: Path | None = None, prices_path: Path | None = None,
    recordings_dir: Path | None = None, live_provider_factory: Callable[[str, str], ModelProvider] | None = None,
    safety: SafetyProvider | None = None,  # the test seam, only beside an injected (fake) provider
    person: TerminalPerson | None = None, announce: Callable[[e2e.Estimate, float], None] | None = None,
    real_connectors: bool = False, real_connectors_factory: Callable[[], dict[str, Any]] | None = None,
    allow_writes: bool = False, allow_send: bool = False, progress: Callable[[str], None] | None = None,
) -> e2e.LiveE2EReport:  # fmt: skip
    env = os.environ if environ is None else environ
    e2e._gate(mode, env, max_credits)  # the live switch, CI, Cloud Run and the cap: first of all
    e2e.check_write_flags(real_connectors, allow_writes, allow_send)
    if not (text := topic.replace("\r\n", "\n").strip()):
        raise _refuse("empty_topic", "the topic is empty; nothing was sent")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    recordings = Path(recordings_dir).resolve() if recordings_dir else ADHOC / digest
    if not recordings.is_relative_to(ADHOC.resolve()):
        raise _refuse("recordings_dir_outside", f"--recordings-dir must be under {ADHOC} (git-ignored)")
    if mode == "live" and person is None:
        raise _refuse("no_person", "a live topic run needs a person to answer it; nothing was sent")
    if mode == "live" and safety is not None and live_provider_factory is None:
        raise _refuse("safety_unavailable", f"a real run screens with Model Armor only. It needs {MODEL_ARMOR_NEEDS}")
    config = e2e._load_config(models_path, prices_path, env)
    blank = {"outcome": None}  # no expected outcome; `gates="hold"`: with no person every gate holds, never approve_all
    case = BankCase(f"adhoc-{digest}", "ad-hoc topic", "adhoc", (), text, {}, blank, Path(os.devnull), gates="hold")
    note = f"injected ({type(safety).__name__})" if safety is not None else _safety_note(config)
    if mode == "dry-run":
        estimate = e2e._estimate(config, case)
        if announce is not None:
            announce(estimate, max_credits)
        print(f"safety screen named (not called in a dry run): {note}")
        if real_connectors:
            e2e.print_real_plan(allow_writes, allow_send)
        return e2e.LiveE2EReport(case.id, mode, max_credits, estimate, safety=note, faked=TOPIC_FAKED)
    if (
        real_connectors and real_connectors_factory is None
    ):  # no default factory yet (CL-LIVE-3): refuse before the screen call
        raise _refuse("real_connectors_no_token", e2e.NO_CONNECTION)
    screen = _screen(config, recordings, text, safety)
    report = e2e.run_live_e2e(
        case.id, mode="live", max_credits=max_credits, environ=environ, models_path=models_path,
        prices_path=prices_path, recordings_dir=recordings, live_provider_factory=live_provider_factory, safety=screen,
        announce=announce, adhoc=case, person=person, real_connectors=real_connectors,
        real_connectors_factory=real_connectors_factory, allow_writes=allow_writes, allow_send=allow_send,
        progress=progress,
    )  # fmt: skip
    report.safety = note
    report.faked = e2e.real_faked(TOPIC_FAKED, allow_writes) if report.real_connectors else TOPIC_FAKED
    report.story_lines = [e2e.StoryLine(clean(s.text), s.event_ids) for s in report.story_lines]
    return report


def _typed(read: Callable[[str], str]) -> str:
    print("Type your request; finish with an empty line (or end of input):", flush=True)
    lines: list[str] = []
    while True:
        try:
            line = read("")
        except EOFError:
            break
        if not line.strip():
            break
        lines.append(line)
    return "\n".join(lines)


def main(
    argv: list[str] | None = None, *, environ: Mapping[str, str] | None = None,
    live_provider_factory: Callable[[str, str], ModelProvider] | None = None, safety: SafetyProvider | None = None,
    read: Callable[[str], str] | None = None, tty: Callable[[], bool] | None = None,
    drain: Callable[[], bool] | None = None,
    real_connectors_factory: Callable[[], dict[str, Any]] | None = None,
) -> int:  # fmt: skip
    parser = argparse.ArgumentParser(prog="live_run", description=(__doc__ or "").split("\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--topic-stdin", action="store_true", help="type the request at a prompt (what just uses)")
    source.add_argument("--topic-file", type=Path, help="a UTF-8 text file holding the request")
    source.add_argument("--topic", help="the request, when calling this script directly (never through just)")
    parser.add_argument("--max-credits", type=float, default=e2e.DEFAULT_MAX_CREDITS, help="default 40, at most 200")
    parser.add_argument("--dry-run", action="store_true", help="print the estimate and name the safety screen; no call")
    parser.add_argument("--auto-answer", action="store_true", help="take each question's default; labelled as such")
    parser.add_argument("--auto-approve-t1t2", action="store_true", help="approve T1/T2 gates; a T3 gate always asks")
    parser.add_argument("--real-connectors", action="store_true", help="real read-only Gmail, Drive and Calendar")
    e2e.add_write_flags(parser)
    for name in ("models-file", "prices-file", "recordings-dir"):
        parser.add_argument(f"--{name}", type=Path)
    args = parser.parse_args(argv)
    read = read or input
    try:
        if args.topic_file is not None:
            topic = args.topic_file.read_text(encoding="utf-8")
        else:
            topic = _typed(read) if args.topic_stdin else args.topic
    except (OSError, UnicodeDecodeError):
        print("REFUSED topic_unreadable: the topic file could not be read as UTF-8 text", file=sys.stderr)
        return 2
    text = topic.replace("\r\n", "\n").strip()
    print(f"topic: {len(text)} characters, sha256 {hashlib.sha256(text.encode('utf-8')).hexdigest()}", flush=True)
    person = TerminalPerson(auto_answer=args.auto_answer, auto_approve_t1t2=args.auto_approve_t1t2, read=read,
                            tty=tty or sys.stdin.isatty, drain=drain or drain_stdin)  # fmt: skip
    try:
        report = run_topic(
            topic, mode="dry-run" if args.dry_run else "live", max_credits=args.max_credits, environ=environ,
            models_path=args.models_file, prices_path=args.prices_file, recordings_dir=args.recordings_dir,
            live_provider_factory=live_provider_factory, safety=safety, person=person, announce=e2e.announce,
            real_connectors=args.real_connectors, real_connectors_factory=real_connectors_factory,
            allow_writes=args.allow_writes, allow_send=args.allow_send, progress=e2e.print_progress,
        )  # fmt: skip
    except e2e.LiveE2ERefused as refusal:
        print(f"REFUSED {refusal.code}: {refusal}", file=sys.stderr)
        return 2
    if args.dry_run:
        return 0
    e2e._print_report(report)
    print("expected: none (an ad-hoc topic; terminal_honest checks only the facts behind the outcome seen)")
    print("\n".join(person.log))
    label = "deliverable" if report.outcome_class == "completed" else "draft (not delivered)"
    for title, work in report.work:
        print(f"{label}: {clean(title)}\n{clean(work, lines=True)}\n")
    bad = report.outcome_class not in ("completed", "held_at_gate", "declined") or any(f.hard for f in report.findings)
    code = 3 if report.outcome_class == "stopped_at_cap" else int(bad)
    if code:
        why = " ".join((report.reason or "the run did not finish, or a hard check failed").split())
        print(f"STOP {report.outcome_class}: {why}", file=sys.stderr)
    return code
