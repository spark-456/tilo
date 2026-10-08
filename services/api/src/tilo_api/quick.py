"""COST-FAST-1: the Quick mode of `POST /intake` (services/api/tests/API_COST_FAST_1.md).

A simple question gets one plain call on the `assistant` role; real work gets a switch offer, never a silent
Thinking run. Quick creates no task, world, artifact or event (nothing animates, HR-1), calls neither the Director nor
the approaches, and shows the model the cleaned question alone. Its credits are held and committed on the person's
FR-PA-19 daily allowance and, deployed and live, one unit on the SEC-16 uid ledger (the classifier call and the answer
call share one reservation and one half-credit budget). No question or answer is logged.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import unicodedata
import uuid
import weakref
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from tilo_planning.intake import IntakeRejected
from tilo_providers.errors import ProviderError
from tilo_providers.interfaces import GenerateRequest, SafetyProvider
from tilo_providers.prompts import load_prompt, neutralise_marker
from tilo_providers.replay import ReplayMissError
from tilo_providers.router import Router, RouterError

from tilo_api import deps, spend
from tilo_api.assistant.metering import SpendLedger
from tilo_api.people_limits import Limits
from tilo_api.people_writes import Refusal
from tilo_api.quick_ledger import LedgerWriter, quick_entry
from tilo_api.quick_rules import REASONS, QuickConfigError, QuickRules, classify, clean, load_quick_rules, parse_verdict

logger = logging.getLogger("tilo_api.quick")
_KEY = re.compile(r"[A-Za-z0-9._-]{1,64}")
_UNAVAILABLE = frozenset({"QuotaError", "RetryableError"})  # PL-02: 429 and 5xx or timeouts, not a bad reply
_BILLED = frozenset({"OutputTruncatedError"})  # sent, ran to the output cap, no usage reported
_NOT_SENT = {"BudgetExceededError", "TokenCapExceededError"}  # attempts the router refused before sending
_MODEL_REASONS = ", ".join(sorted(REASONS - {"attachments", "too_long", "scenario"}))


class QuickRefusal(Exception):
    """A refusal with a fixed sentence: the question, the answer and the key are never in it."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


class _Body(BaseModel):  # what a retry's fingerprint covers: the question as sent
    text: str


_LIMITS: dict[int, Limits] = {}
_LIMITS_LOCK = threading.Lock()


def _limits_of(owner: object) -> Limits:
    """Keys live as long as the allowance ledger they sit beside (a fresh ledger starts clean), like people_limits."""
    with _LIMITS_LOCK:
        found = _LIMITS.get(id(owner))
        if found is None:
            found = _LIMITS[id(owner)] = Limits()
            weakref.finalize(owner, _LIMITS.pop, id(owner), None)
        return found


@dataclass
class _Tally:
    """What the router has spent of one ask's budget. A call that reached a model and was billed stays charged even
    when its reply is unusable; only an unsent or refused call (RequestError, quota, 5xx) is released."""

    budget: float
    left: float = -1.0
    profile: str | None = None  # the last profile that answered, for the cost report's rows
    tokens: tuple[int, int] = (0, 0)

    def __post_init__(self) -> None:
        self.left = self.budget

    @property
    def spent(self) -> float:
        return self.budget - self.left


@dataclass
class _Spend:
    """The holds of one ask: the allowance reservation and, deployed and live, the uid ledger unit."""

    allowance: SpendLedger
    reservation: str
    guard: spend.SpendGuard | None
    plan: spend.UnitPlan | None
    unit_minor: int

    def commit(self, credits: float) -> None:
        self.allowance.commit(self.reservation, credits)
        if self.guard is not None and self.plan is not None:
            self.guard.settle_unit(self.plan, self.unit_minor)

    def release(self) -> None:
        self.allowance.release(self.reservation)
        if self.guard is not None and self.plan is not None:
            self.guard.abort_unit(self.plan)


def _hold(
    rules: QuickRules, uid: str, now: datetime, allowance: SpendLedger, switches: Any, mode: str, caps: Any
) -> _Spend:
    cap = deps.get_assistant_config().user_day_credits  # FR-PA-19: the panel's own daily allowance
    reservation = allowance.reserve(uid, now.strftime("%Y-%m-%d"), rules.budget, cap)
    if reservation is None:
        raise QuickRefusal(429, "Your allowance for questions today is used up; it renews tomorrow (UTC).")
    guard = plan = None
    if mode == "live":  # SEC-16: no ledger or no caps means no hold, so no live call
        if not (isinstance(switches, spend.Switches) and switches.ledger is not None and caps is not None):
            allowance.release(reservation)
            raise deps.ReplayOnly
        guard = spend.SpendGuard(switches.ledger, switches.flags, caps)  # SEC-16: one unit on the uid ledger
        plan = guard.begin_unit(
            "live", uid=uid, run_id=f"quick_{uuid.uuid4().hex}", org_id=deps.ORG_ID,
            estimate_minor=caps.unit_reserve_minor, at=now,
        )  # fmt: skip
        if plan.reservation is None:
            allowance.release(reservation)
            raise spend.SpendCapReached if plan.reason == "uid_lifetime" else deps.ReplayOnly
    return _Spend(allowance, reservation, guard, plan, caps.unit_reserve_minor if caps is not None else 0)


def _call(
    router: Router, rules: QuickRules, request: GenerateRequest, tally: _Tally, *, empty_ok: bool = False
) -> tuple[str, int]:
    """One call on the role within the tally's budget: (reply text, calls sent). Failures become fixed answers, and
    a billed call is left on the tally."""
    try:
        result = router.generate(rules.role, request, budget=tally.left)
    except ReplayMissError as exc:
        raise deps.ModelUnavailable from exc
    except RouterError as exc:  # a budget or cap refusal is a RouterError too: it never reached a model
        tried = [a for a in exc.attempts if a.error_type not in _NOT_SENT]
        if any(a.error_type in _BILLED for a in tried):
            tally.left = 0.0  # the model ran to its cap: charge the whole remaining budget, the call's worst case
        if tried and all(a.error_type in _UNAVAILABLE for a in tried):
            raise deps.ModelUnavailable from exc  # NFR-22: quota or availability on every candidate that was tried
        raise QuickRefusal(502, "The model could not answer.") from None
    except ProviderError:
        raise QuickRefusal(502, "The model could not answer.") from None
    reply = None if result.response is None else result.response.text
    reply = "" if reply is None and empty_ok and result.outcome == "ok" else reply
    if result.budget is not None:
        tally.left = result.budget
    if result.response is not None:
        used = result.response.usage or {}
        tally.profile = result.response.profile_id
        tally.tokens = (
            tally.tokens[0] + int(used.get("input_tokens") or 0),
            tally.tokens[1] + int(used.get("output_tokens") or 0),
        )
    sent = sum(1 for a in result.attempts if a.error_type not in _NOT_SENT)
    if result.outcome != "ok" or type(reply) is not str or not (reply.strip() or empty_ok):
        raise QuickRefusal(502, "The model gave no usable reply.")
    return reply, max(sent, 1)


def _ask(rules: QuickRules, router: Router, question: str, tally: _Tally, *, vet: bool) -> dict[str, Any]:
    """The classifier call (when `vet`: the rules left this text to the model) and then the answer call."""
    data = neutralise_marker(question, "QUESTION")
    calls = 0
    if vet:
        request = GenerateRequest(
            system=load_prompt("assistant", "quick_classify_system.md", {"reasons": _MODEL_REASONS}),
            prompt=load_prompt("assistant", "quick_classify_task.md", {"question": data}),
            json_mode=True,
            thinking_level=rules.thinking_level,
            max_output_tokens=rules.classifier_max_output_tokens,
        )
        reply, made = _call(router, rules, request, tally, empty_ok=True)  # a bad verdict is no verdict
        calls += made
        verdict = parse_verdict(reply)
        if verdict is None or verdict.kind == "work":  # no verdict is the offer `unclear`; a model never answers it
            return {"offer": verdict.reason if verdict else "unclear", "calls": calls}
    request = GenerateRequest(
        system=load_prompt("assistant", "quick_answer_system.md"),
        prompt=load_prompt("assistant", "quick_answer_task.md", {"question": data}),
        thinking_level=rules.thinking_level,
        max_output_tokens=rules.answer_max_output_tokens,
    )
    reply, made = _call(router, rules, request, tally)
    return {"text": _plain(reply)[: rules.answer_max_chars], "calls": calls + made}


def _plain(reply: str) -> str:
    """A model reply is shown as text only: category C characters (control, bidi, format) go, but not newline or tab."""
    return "".join(c for c in reply if c in ("\n", "\t") or unicodedata.category(c)[0] != "C")


def _offer(reason: str | None) -> dict[str, Any]:
    return {"mode": "quick", "outcome": "switch_to_thinking", "reason": reason or "unclear"}


def respond(
    *,
    text: str,
    uid: str,
    has_files: bool,
    scenario: str | None,
    safety: SafetyProvider,
    router: Router,
    allowance: SpendLedger,
    switches: Any,
    mode: str,
    caps: Any,
    key: str | None,
    ledger: LedgerWriter | None = None,
) -> dict[str, Any]:
    """The 200 body (answer or offer) of a Quick ask whose text, limits and file names intake has already screened;
    raises QuickRefusal (a fixed sentence), ReplayOnly, ModelUnavailable, SpendCapReached or HTTPException."""
    if key is not None and _KEY.fullmatch(key) is None:
        raise QuickRefusal(422, "The Idempotency-Key is not valid.")  # never echoed
    question = clean(text)
    if not question:
        raise QuickRefusal(422, "Describe the task in text.")
    try:
        if question != text and safety.check(question)["flagged"]:  # the model sees the cleaned text: screen it too
            raise IntakeRejected("The safety screen flagged the task text or a file name; rephrase it.")
    except IntakeRejected as exc:
        raise QuickRefusal(422, exc.reason) from None
    except Exception as exc:
        logger.warning("safety screen failed: %s", type(exc).__name__)
        raise QuickRefusal(503, "The safety screen is unavailable; nothing was answered.") from None
    try:
        rules = load_quick_rules()
        max_chars = deps.get_assistant_config().question_max_chars
    except QuickConfigError as exc:
        logger.warning("quick config unusable: %s", exc)
        raise QuickRefusal(503, "not_configured") from None
    verdict = classify(rules, text, max_chars=max_chars, has_files=has_files, scenario=scenario is not None)
    if verdict.kind == "work":
        return _offer(verdict.reason)  # decided by rules: no model, no cost, nothing stored
    if rules.role not in deps.providers_config().roles:
        raise QuickRefusal(503, "not_configured")  # never a fallback to the Director

    def record(tally: _Tally) -> None:
        """COST-FAST-1b: the same credits on the person's Quick pseudo run, so GET /costs shows them. Best effort: the
        allowance commit above is authoritative, so a failed write is logged by type and never changes the answer."""
        if ledger is None or tally.spent <= 0:
            return
        try:
            now = datetime.now(UTC)
            ledger.append(quick_entry(uid, deps.ORG_ID, now, float(tally.spent), tally.profile, tally.tokens))
        except Exception as exc:
            logger.warning("quick ledger write failed: %s", type(exc).__name__)

    def make() -> dict[str, Any]:
        held = _hold(rules, uid, datetime.now(UTC), allowance, switches, mode, caps)
        tally = _Tally(rules.budget)
        try:
            done = _ask(rules, router, question, tally, vet=verdict.kind == "model")
        except BaseException:
            held.commit(tally.spent) if tally.spent > 0 else held.release()  # billed stays charged
            record(tally)
            raise
        held.commit(tally.spent)
        record(tally)
        if "offer" in done:
            return _offer(done["offer"])
        cost = {"model_calls": done["calls"], "credits": float(tally.spent), "saved_credits": 0.0}
        return {"mode": "quick", "outcome": "answered", "text": done["text"], "cost": cost}

    if key is None:
        return make()
    digest = hashlib.sha256(key.encode()).hexdigest()  # the people limiter's key alphabet has no "."
    try:
        return _limits_of(allowance).once(uid, "/intake#quick", digest, _Body(text=text), make)
    except Refusal as refusal:
        raise QuickRefusal(422, "That Idempotency-Key was used with another question.") from refusal
