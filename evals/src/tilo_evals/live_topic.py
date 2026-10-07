"""`just live-run --topic "<any request>"`: one real end-to-end run on a typed topic (PL-LIVE-E2E, #340; FR-INT-15,
FR-INT-02; PRD 6.6 EFF-01, 9.4 HR-1, 10.3). The SAME runner as `just live-e2e` (gate, meter, cap, pipeline, checks,
report). Differences: the case is built in memory from the topic, with no expected outcome; the untrusted topic goes
through the safety role (Model Armor, via the provider layer) first and is refused if that screen is missing or flags
it; a person answers questions, the approach and every gate card in the terminal, and no flag ever approves a T3 gate.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
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


class TerminalPerson:
    """The person at the terminal (`bank_run.drive`'s `person`); `log` says who decided each thing, for the report."""

    def __init__(self, *, auto_answer: bool = False, auto_approve_t1t2: bool = False,
                 read: Callable[[str], str] = input, write: Callable[[str], None] = print) -> None:  # fmt: skip
        self.auto_answer, self.auto_approve_t1t2, self._input, self._write = auto_answer, auto_approve_t1t2, read, write
        self.log: list[str] = []

    def _read(self, prompt: str) -> str:
        try:
            return self._input(prompt).strip()
        except EOFError:  # input closed: never read as a yes
            return "\0"

    def _yes(self, prompt: str) -> tuple[bool, str]:
        while (said := self._read(f"{prompt} [y/n]: ").lower()) != "\0":
            if said in ("y", "yes", "n", "no"):
                return said.startswith("y"), self._read("reason: ").strip("\0")
            self._write("answer y or n")
        return False, "no answer (input closed)"

    def _pick(self, prompt: str, options: list[Any]) -> Any:
        said = self._read(prompt)
        return options[int(said) - 1] if said.isdigit() and 1 <= int(said) <= len(options) else said.strip("\0")

    def answer(self, question: dict[str, Any]) -> str | None:
        suggested = [str(s) for s in question.get("suggested_answers") or []]
        default = suggested[0] if suggested else None  # None: the Director records its own assumption
        if self.auto_answer:
            self.log.append(f"question {question['field']}: {default!r} (answered by the CLI default, not a person)")
            return default
        self._write(f"Director asks ({question['field']}): {question['text']}")
        self._write("\n".join(f"  {n}. {option}" for n, option in enumerate(suggested, 1)))
        pick = self._pick("answer (a number, your own words, or empty for the default): ", suggested) or default
        self.log.append(f"question {question['field']}: {pick!r} (answered by the person)")
        return pick[:300] if pick else None  # the answers route's own limit

    def approach(self, offered: dict[str, Any]) -> str | None:
        options, recommended = offered["approaches"], offered["recommended"]
        self._write("Director proposes:")
        for n, a in enumerate(options, 1):
            credits, mark = a["credits"], " (recommended)" if a["id"] == recommended else ""
            self._write(f"  {n}. {a['label']}: {a['summary']} [{credits['min']}-{credits['max']} credits]{mark}")
        chosen = self._pick("approach number (empty for the recommended): ", options)
        chosen = chosen if isinstance(chosen, dict) else next(a for a in options if a["id"] == recommended)
        ok, why = self._yes(f"approve the approach {chosen['label']!r}?")
        self.log.append(f"approach {chosen['id']}: {'approved' if ok else 'declined'} by the person ({why or '-'})")
        return chosen["id"] if ok else None

    def gate(self, card: dict[str, Any]) -> bool:
        gate = card.get("gate") or {}
        tier, action = gate.get("risk_tier"), (gate.get("action") or {}).get("type", "?")
        if self.auto_approve_t1t2 and tier in ("T1", "T2"):  # a T3 or an unknown tier always asks (PRD 10.3)
            self.log.append(f"gate {tier} {action}: approved by --auto-approve-t1t2 (a CLI flag, not a person)")
            return True
        self._write(f"gate card ({tier or 'tier unknown'}, {action}): {card['what_happened']} {card['why_it_matters']}")
        ok, why = self._yes("approve this step?")
        self.log.append(f"gate {tier} {action}: {'approved' if ok else 'held'} by the person ({why or '-'})")
        return ok


def _safety_note(config: ProvidersConfig) -> str:
    """The live screen the config names, or a refusal that says what it needs: nothing goes out unscreened."""
    role = config.roles.get(SAFETY_ROLE)
    profile = config.profiles.get(role.primary) if role else None
    if role is None or profile is None or profile.provider != "model_armor":
        raise e2e.LiveE2ERefused("safety_unavailable", f"no live safety screen. It needs {MODEL_ARMOR_NEEDS}")
    return f"safety role, profile {role.primary} (Model Armor template {profile.model})"


def _screen(config: ProvidersConfig, recordings: Path, text: str, safety: SafetyProvider | None) -> SafetyProvider:
    """The topic through the safety screen before any model call: flagged, or a screen that cannot run, refuses."""
    try:
        screen = safety or build_safety_provider(config, fixtures_dir=recordings)
        result = screen.check(text)
    except Exception as error:  # noqa: BLE001 - fail closed; the error's text is never shown
        why = f"the safety screen could not run ({type(error).__name__}). It needs {MODEL_ARMOR_NEEDS}"
        raise e2e.LiveE2ERefused("safety_unavailable", why) from None
    if result["flagged"]:
        category = reason_category(result["reason"]) or "other"
        raise e2e.LiveE2ERefused("unsafe_topic", f"the safety screen flagged the topic ({category}); nothing was sent")
    return screen


def run_topic(
    topic: str, *, mode: Literal["live", "dry-run"] = "live", max_credits: float = e2e.DEFAULT_MAX_CREDITS,
    environ: Mapping[str, str] | None = None, models_path: Path | None = None, prices_path: Path | None = None,
    recordings_dir: Path | None = None, live_provider_factory: Callable[[str, str], ModelProvider] | None = None,
    safety: SafetyProvider | None = None,  # the test seam; None: the safety role, built through the provider layer
    person: TerminalPerson | None = None, announce: Callable[[e2e.Estimate, float], None] | None = None,
) -> e2e.LiveE2EReport:  # fmt: skip
    env = os.environ if environ is None else environ
    e2e._gate(mode, env, max_credits)  # the live switch, CI, Cloud Run and the cap: first of all
    if not (text := topic.replace("\r\n", "\n").strip()):
        raise e2e.LiveE2ERefused("empty_topic", "the topic is empty; nothing was sent")
    config = e2e._load_config(models_path, prices_path, env)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    case = BankCase(f"adhoc-{digest}", "ad-hoc topic", "adhoc", (), text, {}, {"outcome": None}, Path(os.devnull))
    note = f"injected ({type(safety).__name__})" if safety is not None else _safety_note(config)
    if mode == "dry-run":
        estimate = e2e._estimate(config, case)
        if announce is not None:
            announce(estimate, max_credits)
        print(f"safety: {note}")
        return e2e.LiveE2EReport(case.id, mode, max_credits, estimate, safety=note, faked=TOPIC_FAKED)
    recordings = Path(recordings_dir) if recordings_dir else e2e.default_recordings_dir("adhoc") / digest  # gitignored
    screen = _screen(config, recordings, text, safety)
    report = e2e.run_live_e2e(
        case.id, mode="live", max_credits=max_credits, environ=environ, models_path=models_path,
        prices_path=prices_path, recordings_dir=recordings, live_provider_factory=live_provider_factory, safety=screen,
        announce=announce, adhoc=case, person=person,
    )  # fmt: skip
    report.safety, report.faked = note, TOPIC_FAKED
    return report


def main(
    argv: list[str] | None = None, *, environ: Mapping[str, str] | None = None,
    live_provider_factory: Callable[[str, str], ModelProvider] | None = None, safety: SafetyProvider | None = None,
    read: Callable[[str], str] | None = None,
) -> int:  # fmt: skip
    parser = argparse.ArgumentParser(prog="live_run", description=(__doc__ or "").split("\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--topic", help="the request, in your own words")
    source.add_argument("--topic-file", type=Path, help="a UTF-8 text file holding a long request")
    parser.add_argument("--max-credits", type=float, default=e2e.DEFAULT_MAX_CREDITS, help="default 40, at most 200")
    parser.add_argument("--dry-run", action="store_true", help="print the estimate and the safety screen; no call")
    parser.add_argument("--auto-answer", action="store_true", help="take each question's default; labelled as such")
    parser.add_argument("--auto-approve-t1t2", action="store_true", help="approve T1/T2 gates; a T3 gate always asks")
    for name in ("models-file", "prices-file", "recordings-dir"):
        parser.add_argument(f"--{name}", type=Path)
    args = parser.parse_args(argv)
    try:
        topic = args.topic if args.topic is not None else args.topic_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        print("REFUSED topic_unreadable: the topic file could not be read as UTF-8 text", file=sys.stderr)
        return 2
    person = TerminalPerson(auto_answer=args.auto_answer, auto_approve_t1t2=args.auto_approve_t1t2, read=read or input)
    try:
        report = run_topic(
            topic, mode="dry-run" if args.dry_run else "live", max_credits=args.max_credits, environ=environ,
            models_path=args.models_file, prices_path=args.prices_file, recordings_dir=args.recordings_dir,
            live_provider_factory=live_provider_factory, safety=safety, person=person, announce=e2e.announce,
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
    for title, text in report.work:
        print(f"{label}: {title}\n{text}\n")
    bad = report.outcome_class not in ("completed", "held_at_gate", "declined") or any(f.hard for f in report.findings)
    code = 3 if report.outcome_class == "stopped_at_cap" else int(bad)
    if code:
        why = " ".join((report.reason or "the run did not finish, or a hard check failed").split())
        print(f"STOP {report.outcome_class}: {why}", file=sys.stderr)
    return code
