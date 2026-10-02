"""Test doubles and builders for FR-CHN-04 (task-scoped WhatsApp bot, off-topic refusal). The API they
drive is pinned in API_FR_CHN_04.md.

Package-unique module name on purpose (same reason as `_channels_lib.py`). Nothing here is production
logic: `OffTopicRig` wires the real `InboundRouter`, `KeywordHandler` and `WhatsAppCards` to the fakes in
`_chn_0305_lib.py`; `ProviderSpy` records every call that reaches the provider layer (`tilo_providers`), so
a test can prove a message never went to a model or the safety provider; `load_e_chn_cases` reads the
E-CHN eval set (PRD 19.2) straight from `evals/cases/E-CHN/*.yaml`.

No real numbers, PINs or secrets: the eval senders are fictional 555-01xx numbers and PINs come from
`fake_pin()` at runtime.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import re
from dataclasses import dataclass
from typing import Any

import pytest
import yaml
from _channels_lib import FakeControls
from _chn_0305_lib import REPO_ROOT, WEB_URL, CardRig

E_CHN_DIR = REPO_ROOT / "evals" / "cases" / "E-CHN"


# ---------------------------------------------------------------------------
# The E-CHN eval set (PRD 19.2: 30 off-topic WhatsApp messages, threshold 100% redirected)


@dataclass(frozen=True)
class EChnCase:
    id: str
    sender: str  # wa_id digits, as Meta sends `from`
    message: str
    category: str
    topic_keywords: tuple[str, ...]


def load_e_chn_cases() -> list[EChnCase]:
    cases = []
    for path in sorted(E_CHN_DIR.glob("E-CHN-*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        inputs, truth = raw["inputs"], raw["ground_truth"]
        assert truth["expected"] == "redirect", path.name
        cases.append(
            EChnCase(
                id=raw["id"],
                sender=re.sub(r"\D", "", inputs["sender"]),
                message=inputs["message"],
                category=inputs["category"],
                topic_keywords=tuple(truth.get("topic_keywords") or ()),
            )
        )
    return cases


# ---------------------------------------------------------------------------
# The wired router


class OffTopicRig(CardRig):
    """CardRig (Riya and Sam bound, cards sent through the real WhatsAppCards) plus the real keyword handler
    and the real inbound router in front of both, all sharing one sender, clock and set of fakes."""

    def __init__(self, *, extra_bound: dict[str, str] | None = None) -> None:
        super().__init__()
        self.bindings.by_number.update(extra_bound or {})
        keywords = importlib.import_module("tilo_channels.keywords")
        inbound = importlib.import_module("tilo_channels.inbound")
        self.controls = FakeControls(self.clock)
        self.keywords = keywords.KeywordHandler(bindings=self.bindings, controls=self.controls, sender=self.sender)
        self.router = inbound.InboundRouter(
            bindings=self.bindings, sender=self.sender, web_url=WEB_URL, keywords=self.keywords, cards=self.svc
        )

    def say(self, sender: str, text: str | None, *, kind: str = "text", **extra: Any) -> Any:
        """One inbound message through the router; returns the RouteResult."""
        return self.router.handle(self.message(sender, kind=kind, text=text, **extra))

    def replies_since(self, mark: int) -> list[tuple[str, str]]:
        """(to, body) of every text sent after `mark` (a len(self.sender.texts) taken earlier)."""
        return [(to, body) for (to, body, _) in self.sender.texts[mark:]]

    def side_effects(self) -> dict[str, int]:
        """Counts of everything a message could cause besides a reply."""
        return {
            "controls": len(self.controls.calls),
            "api": len(self.api.calls),
            "pins": len(self.pins.checks),
            "events": len(self.events.parts),
            "archive": len(self.archive.records),
            "cards_sent": len(self.sender.cards),
        }


# ---------------------------------------------------------------------------
# Provider-layer spy (PL-01: every model and safety call goes through tilo_providers)

_METHODS = ("generate", "stream", "embed", "count_tokens", "check", "transcribe", "search")


def _import_all_providers() -> list[type]:
    import tilo_providers

    for info in pkgutil.walk_packages(tilo_providers.__path__, "tilo_providers."):
        try:
            importlib.import_module(info.name)
        except ImportError:  # an optional SDK that is not installed: nothing of it can be called either
            continue
    interfaces = importlib.import_module("tilo_providers.interfaces")
    roots = [interfaces.ModelProvider, interfaces.SafetyProvider, interfaces.SpeechProvider, interfaces.SearchProvider]
    seen: list[type] = []
    stack = list(roots)
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.append(cls)
        stack.extend(cls.__subclasses__())
    router = importlib.import_module("tilo_providers.router")
    seen.append(router.Router)
    return seen


class ProviderSpy:
    """Wraps every model, safety, speech and search entry point in tilo_providers (and every subclass
    already imported, so one defined in tilo_channels is covered too). Calls still run; each is recorded
    with a repr of its arguments."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        importlib.import_module("tilo_channels.inbound")
        importlib.import_module("tilo_channels.cards")
        importlib.import_module("tilo_channels.keywords")
        self.calls: list[tuple[str, str, str]] = []
        for cls in _import_all_providers():
            for name in _METHODS:
                original = cls.__dict__.get(name)
                if callable(original):
                    monkeypatch.setattr(cls, name, self._wrap(cls.__name__, name, original))

    def _wrap(self, owner: str, name: str, original: Any) -> Any:
        calls = self.calls

        def spy(*args: Any, **kwargs: Any) -> Any:
            calls.append((owner, name, repr(args[1:]) + repr(kwargs)))
            return original(*args, **kwargs)

        return spy

    def dump(self) -> str:
        return "\n".join(c[2] for c in self.calls)


# ---------------------------------------------------------------------------
# Log capture (every logger, every level, exception text included)


class LogTap(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []
        self._fmt = logging.Formatter("%(name)s %(levelname)s %(message)s")

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self._fmt.format(record) + " " + repr(record.args))

    def text(self) -> str:
        return "\n".join(self.lines)


def digit_runs(text: str, min_len: int = 4) -> list[str]:
    """Runs of ASCII digits of at least `min_len` in `text`."""
    return re.findall(rf"[0-9]{{{min_len},}}", text)


def to_fullwidth(digits: str) -> str:
    return "".join(chr(0xFF10 + int(d)) for d in digits)
