"""Inert PRD 902 shared card projection for channel renderers.

Call only with a contract-validated, owner-authorized card and an existing LinkService
open link. No signing, answering, delivery or policy authority is introduced here.
Any future delivery must use the existing outbox + policy engine at T3.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from tilo_redact import redact

from tilo_channels.links import IssuedLink


@dataclass(frozen=True)
class NeutralCard:
    lines: tuple[str, ...]
    open_url: str = field(repr=False)


def safe_text(value: str, limit: int = 2000) -> str:
    """Bound, redact, then escape channel markup and disable mention syntax."""
    text = redact(value[:8000])
    text = text.translate({**dict.fromkeys(range(32), " "), 127: " ", 64: "＠", 60: "＜", 62: "＞"})
    text = text.translate({ord(char): "\\" + char for char in "\\`*_{}[]()!#|~"})
    return text if len(text) <= limit else text[: limit - 1] + "…"


def card_to_neutral(card: Mapping[str, Any], link: IssuedLink) -> NeutralCard:
    """Project display fields only; even gates/consents open their existing sign-in flow.

    The issued-link object is trusted server input, never a URL supplied by card text.
    LinkService remains responsible for expiry, user binding and single-use checks.
    """
    parts = urlsplit(link.url)
    if (
        link.card_id != card["id"]
        or link.action != "open"
        or link.option is not None
        or parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or not parts.path.endswith("/l/" + link.token)
        or any(c.isspace() or ord(c) < 32 for c in link.url)
    ):
        raise ValueError("existing card-bound HTTPS open link required")
    lines = [safe_text(card["what_happened"]), safe_text(card["why_it_matters"])]
    gate = card.get("gate")
    if gate is not None:
        lines.append(safe_text(f"Risk: {gate['risk_tier']}; irreversible: {gate['irreversible']}"))
    for option in card["options"]:
        marks = ("; suggested" if option["suggested"] else "") + ("; irreversible" if option["irreversible"] else "")
        lines.append(safe_text(f"{option['label']}{marks}"))
    lines.append(safe_text(f"Timeout default: {card['safe_default']}"))
    lines.append("Review and answer securely in Tilo.")
    return NeutralCard(tuple(lines), link.url)
