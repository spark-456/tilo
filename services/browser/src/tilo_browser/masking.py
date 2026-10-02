"""One masker for everything that leaves a browser worker (PRD 12.3, 16.1 rule 4, SEC-14).

Placeholders are `[masked:<kind>]`. Pure, idempotent, never raises on any str.
"""

from __future__ import annotations

import re
from typing import Any

_FREE_SECRETS = re.compile(
    r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|\bsk-[A-Za-z0-9_-]{20,}"
    r"|\bgh[pousr]_[A-Za-z0-9]{30,}"
    r"|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
    r"|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
    r"|\bya29\.[A-Za-z0-9_-]{20,}"
)
_KEY_VALUE = re.compile(
    r"(?i)(\b[\w-]*(?:password|passwd|pwd|secret|token|api[_-]?key|otp)[\"']?\s*[=:]\s*[\"']?)[^\s&\"']+"
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_PHONE = re.compile(r"(?<![\w+])\+\d[\d ()-]{6,}\d")
_DIGIT_RUN = re.compile(r"(?<!\w)\d+(?:[ -]\d+)*")
_GROUP = re.compile(r"\d+")


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def _mask_cards(text: str) -> str:
    """Mask the longest Luhn-valid 13 to 19 digit window made of whole digit groups."""
    out: list[str] = []
    last = 0
    for run in _DIGIT_RUN.finditer(text):
        groups = [(g.start(), g.end()) for g in _GROUP.finditer(run.group())]
        i = 0
        while i < len(groups):
            hit = None
            for j in range(len(groups) - 1, i - 1, -1):
                digits = "".join(run.group()[s:e] for s, e in groups[i : j + 1])
                if 13 <= len(digits) <= 19 and _luhn(digits):
                    hit = j
                    break
            if hit is None:
                i += 1
                continue
            out.append(text[last : run.start() + groups[i][0]])
            out.append("[masked:card]")
            last = run.start() + groups[hit][1]
            i = hit + 1
    out.append(text[last:])
    return "".join(out)


def mask_text(text: str) -> str:
    text = _FREE_SECRETS.sub("[masked:secret]", text)
    text = _KEY_VALUE.sub(r"\1[masked:secret]", text)
    text = _mask_cards(text)
    text = _EMAIL.sub("[masked:email]", text)
    return _PHONE.sub("[masked:phone]", text)


def mask_data(value: Any) -> Any:
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {k: mask_data(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_data(v) for v in value]
    return value
