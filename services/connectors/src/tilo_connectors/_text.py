"""tilo_connectors._text — small text helpers shared by handoff.py and grants.py (FR-CON-16, FR-CON-20).

No network, no model, no logging. A refusal names ids only, so `safe_id` keeps a caller's string out of a message
unless it is shaped like an id.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_ID = re.compile(r"[A-Za-z0-9_.:@-]{1,80}")
# Invisible or direction-changing code points that can hide text from a person reading a prompt: Unicode tag
# characters, bidi embeddings, overrides and isolates, deprecated format controls, interlinear annotation.
_HIDDEN = re.compile(r"[\U000e0000-\U000e007f\u202a-\u202e\u2066-\u2069\u206a-\u206f\ufff9-\ufffb]")


def collapse(value: str) -> str:
    return " ".join(value.split())


def safe_id(value: Any) -> str:
    """`value` when it is shaped like an id, else a fixed placeholder: refusal messages never echo free text."""
    return value if isinstance(value, str) and _ID.fullmatch(value) else "(not an id)"


def has_hidden(value: str) -> bool:
    return _HIDDEN.search(value) is not None


def flagged(safety: Any, text: str) -> bool:
    """The safety screen's verdict on `text`; an error or an unreadable verdict counts as flagged."""
    try:
        verdict = safety.check(text)
        return not isinstance(verdict, Mapping) or verdict.get("flagged") is not False
    except Exception:
        return True


def redacted_unchanged(redact: Any, text: str) -> bool:
    """True only when the redactor ran and left `text` exactly as it was; an error counts as a change."""
    try:
        return bool(redact(text) == text)
    except Exception:
        return False
