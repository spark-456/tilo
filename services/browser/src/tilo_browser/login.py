"""Login-wall detection and the needs-you card (FR-CON-08, PRD 12.3, 16.1 rule 1).

Tilo never types a credential: a login page produces a card, never a filled field. Pure
functions over the accessibility tree; page text is data, never copied onto the card.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from tilo_browser.masking import mask_text

LOGIN_CARD_OPTION_IDS = ("connect_api", "upload_export", "skip")

_INPUT_ROLES = {"textbox", "searchbox", "spinbutton", "combobox"}
_PASSWORD_AUTOCOMPLETE = {"current-password", "new-password"}
_SSO_SEGMENTS = {
    "login",
    "log-in",
    "signin",
    "sign-in",
    "sign_in",
    "sso",
    "saml",
    "oauth",
    "oauth2",
    "authorize",
    "authenticate",
}
_OTP_NAME = re.compile(r"(?<![a-z])(?:otp|totp|mfa|2fa)(?![a-z])")
_OTP_LABEL = re.compile(r"\b(?:verification|security|authentication|authenticator|\d+-digit)\b[^.]{0,40}\bcode\b")
_PASSWORD_LABEL = re.compile(r"\b(?:password|passphrase|passcode|pwd)\b")
_CREDENTIAL_ASK = re.compile(
    r"\b(?:enter|type|paste|send|share|reply with|provide|submit|give)\b[^.\n]{0,60}"
    r"\b(?:password|passcode|passphrase|credentials|login details)\b"
)
_NEGATED = re.compile(r"(?:never|not|n't)\s*$")


class CredentialEntryRefused(Exception):
    """Tilo never types into a secure field or any field of a login wall."""


@dataclass(frozen=True)
class LoginSignal:
    kind: str  # password_field | otp_field | sso_redirect | credentials_in_text
    refs: tuple[str, ...]


@dataclass(frozen=True)
class CardContext:
    world_id: str
    run_id: str
    header: dict
    new_card_id: Callable[[], str]
    now: Callable[[], str]
    timeout: int


class TreeTooDeep(ValueError):
    """An accessibility tree nested deeper than MAX_TREE_DEPTH: callers fail closed."""


MAX_TREE_DEPTH = 256


def iter_nodes(tree: dict) -> Iterator[dict]:
    """Document-order walk, iterative (no RecursionError), failing closed past MAX_TREE_DEPTH."""
    stack = [(tree, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > MAX_TREE_DEPTH:
            raise TreeTooDeep(f"accessibility tree deeper than {MAX_TREE_DEPTH} levels")
        yield node
        stack.extend((c, depth + 1) for c in reversed(node.get("children") or []))


def _role(n: dict) -> str:
    return str(n.get("role") or "").lower()


def _attr(n: dict, key: str) -> str:
    return str(n.get("attrs", {}).get(key) or "").lower()


def _ref(n: dict) -> str:
    return str(n.get("attrs", {}).get("id") or "")


def _autocomplete(n: dict) -> list[str]:
    """`autocomplete` is a whitespace-separated token list ("billing cc-number", "section-x one-time-code")."""
    return _attr(n, "autocomplete").split()


def _is_password(n: dict) -> bool:
    return _attr(n, "type") == "password" or any(t in _PASSWORD_AUTOCOMPLETE for t in _autocomplete(n))


def _is_otp(n: dict) -> bool:
    if "one-time-code" in _autocomplete(n):
        return True
    if _role(n) not in _INPUT_ROLES:
        return False
    label = str(n.get("name") or "").lower()
    named = (_attr(n, "name"), _attr(n, "id"), label)
    return any(_OTP_NAME.search(s) for s in named) or _OTP_LABEL.search(label) is not None


def _is_payment(n: dict) -> bool:
    return any(t.startswith("cc-") for t in _autocomplete(n))


def _asks_for_password(n: dict) -> bool:
    if _role(n) not in _INPUT_ROLES:
        return False
    return any(
        _PASSWORD_LABEL.search(s) for s in (str(n.get("name") or "").lower(), _attr(n, "placeholder"), _attr(n, "name"))
    )


def is_input_node(n: dict) -> bool:
    return _role(n) in _INPUT_ROLES


def is_secure_node(n: dict) -> bool:
    return _is_password(n) or _is_otp(n) or _is_payment(n)


def node_ref(n: dict) -> str:
    return _ref(n)


def _nodes_where(tree: dict, pred: Callable[[dict], bool]) -> list[dict]:
    return [n for n in iter_nodes(tree) if pred(n)]


def _refs(nodes: list[dict]) -> tuple[str, ...]:
    return tuple(r for n in nodes if (r := _ref(n)))


def secure_nodes(tree: dict) -> list[dict]:
    """Password, one-time-code and payment fields, with or without a ref."""
    return _nodes_where(tree, is_secure_node)


def secure_field_refs(tree: dict) -> list[str]:
    """Refs of the secure fields: masked in screenshots, never typed into."""
    return list(_refs(secure_nodes(tree)))


def _is_sso_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        query = {k.lower() for k, _ in parse_qsl(parts.query, keep_blank_values=True)}
    except ValueError:
        return False
    if _SSO_SEGMENTS & {s.lower() for s in parts.path.split("/")}:
        return True
    return "samlrequest" in query or {"client_id", "redirect_uri"} <= query


def _asks_in_text(text: str) -> bool:
    return any(
        not _NEGATED.search(text[max(0, m.start() - 12) : m.start()].lower())
        for m in _CREDENTIAL_ASK.finditer(text.lower())
    )


def detect_login(*, chain: Sequence[str], tree: dict, text: str) -> LoginSignal | None:
    for kind, pred in (("password_field", _is_password), ("otp_field", _is_otp)):
        if nodes := _nodes_where(tree, pred):  # keyed on the node: an id-less field still counts
            return LoginSignal(kind, _refs(nodes))
    if any(_is_sso_url(u) for u in chain):
        return LoginSignal("sso_redirect", ())
    nodes = _nodes_where(tree, _asks_for_password)
    if nodes or _asks_in_text(text):
        return LoginSignal("credentials_in_text", _refs(nodes))
    return None


def _host_of(url: str) -> str:
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        host = ""
    return mask_text(host) if re.fullmatch(r"[a-z0-9.-]{1,80}", host) else "this site"


_OPTION_LABELS = {"connect_api": "Connect by API", "upload_export": "Upload an export", "skip": "Skip"}
_SUGGESTED = "connect_api"
_SUGGESTED_REASON = "A scoped, revocable connection works without sharing a password."


def _option(option_id: str) -> dict:
    option: dict = {
        "id": option_id,
        "label": _OPTION_LABELS[option_id],
        "suggested": option_id == _SUGGESTED,
        "irreversible": False,
    }
    if option_id == _SUGGESTED:
        option["reason"] = _SUGGESTED_REASON
    return option


def build_login_card(signal: LoginSignal, *, url: str, ctx: CardContext) -> dict:
    """A needs-you card (contracts/card.schema.json). Names the host only: no path, query or page text."""
    host = _host_of(url)
    return {
        "id": ctx.new_card_id(),
        "world_id": ctx.world_id,
        "run_id": ctx.run_id,
        "kind": "needs_you",
        "rung": "needs_you",
        "header": dict(ctx.header),
        "what_happened": f"{host} needs a login",
        "why_it_matters": (
            f"{host} asks for a sign-in. Tilo never types passwords or codes. "
            "Connect by API, upload an export, or skip this site."
        ),
        "options": [_option(oid) for oid in LOGIN_CARD_OPTION_IDS],
        "add_context": False,
        "actions": ["show_me", "snooze"],
        "answer_channels": ["web", "mobile_web", "whatsapp", "email"],
        "created_at": ctx.now(),
        "timeout": ctx.timeout,
        "safe_default": "skip",
        "gate": None,
        "consent": None,
    }
