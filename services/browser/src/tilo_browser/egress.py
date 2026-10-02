"""Egress allowlist for browser workers (PRD 12.3, 16.2, SEC-09). Deterministic, no network.

`EgressPolicy.check` is the one gate every request passes (navigation, each redirect hop,
subresources, a click's navigation). Anything it cannot parse unambiguously is blocked. A
`Decision` is built from validated parts only: no userinfo, query or fragment, and anything
secret-looking in the host or path masked, so the log and `EgressBlocked` messages cannot leak.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import unquote_plus

import idna

from tilo_browser.masking import mask_decoded, mask_text

_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):(.*)$", re.S)
_HOST = re.compile(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)*$")
_NUMERIC_LABEL = re.compile(r"^(?:\d+|0[xX][0-9a-fA-F]*)$")
_UNSAFE_LOG = re.compile(r"[^A-Za-z0-9._~:/%!$&'()*+,;=\[\]-]")
_LOG_LIMIT = 200
_C0_AND_SPACE = "".join(map(chr, range(0x21)))
_TAB_NEWLINE = re.compile(r"[\t\n\r]")
_SCHEMES = re.compile(r"(?:[A-Za-z][A-Za-z0-9+.-]*:)+")  # one or more, so view-source:https: unwraps
_BRACKET_HOST = re.compile(r"(\[[0-9A-Za-z:.%_-]{1,64}\])(?::(\d*))?$")
MAX_URL_LENGTH = 8192


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str  # allowed | host_not_allowlisted | scheme_not_allowed | ip_literal | invalid_url | sensitive_query
    url: str  # sanitised: no userinfo, no query, no fragment, secrets masked
    host: str | None  # lower-case, IDNA A-label form, secrets masked
    scheme: str | None
    redirect_from: str | None = None


class EgressBlocked(Exception):
    def __init__(self, decision: Decision) -> None:
        super().__init__(f"egress blocked ({decision.reason}): {decision.url}")
        self.decision = decision


def sanitise_url(raw: str) -> str:
    """Log form of any URL-ish string: `scheme://host[:port]/path`, never userinfo, query or fragment.

    First pre-processes the way browsers do (WHATWG: strip leading and trailing C0 controls and
    spaces, delete every tab, LF and CR) and unwraps nested schemes (`view-source:https://...`,
    `blob:https://...`; the outer scheme is kept). Userinfo is cut before truncating; host and path
    are masked (raw and percent-decoded). Anything that is not `scheme://authority` (or
    `//authority`) with a numeric port, or is over 8 KB, is logged as `scheme:` alone."""
    s = _TAB_NEWLINE.sub("", raw.strip(_C0_AND_SPACE))
    m = _SCHEMES.match(s)
    scheme = m.group(0).split(":", 1)[0].lower() if m else ""
    rest = re.split(r"[?#]", s[m.end() :] if m else s, maxsplit=1)[0]
    if len(raw) > MAX_URL_LENGTH or not re.match(r"[/\\]{2}", rest):
        return f"{scheme}:"
    parts = re.split(r"([/\\])", rest.lstrip("/\\"), maxsplit=1)
    hostport = parts[0].rsplit("@", 1)[-1]
    v6 = _BRACKET_HOST.match(hostport)  # an IPv6 literal logs as its bracketed host
    host, port = (v6.group(1), v6.group(2)) if v6 else (hostport.partition(":")[0], hostport.partition(":")[2])
    if (port and not (port.isascii() and port.isdigit())) or (hostport.startswith("[") and not v6):
        return f"{scheme}:"
    authority = mask_decoded(host) + (f":{port}" if port else "")
    path = "".join(parts[1:2]) + mask_decoded("".join(parts[2:])) if len(parts) > 1 else ""
    prefix = f"{scheme}://" if scheme else "//"
    return _UNSAFE_LOG.sub("_", (prefix + authority + path)[:_LOG_LIMIT])


def _is_ip_label(host: str) -> bool:
    return _NUMERIC_LABEL.match(host.rsplit(".", 1)[-1]) is not None


def _normalise_host(host: str) -> str | None:
    """Lower-case IDNA A-label form by UTS 46 non-transitional processing, as browsers do
    (so glaßes.com stays distinct from glasses.com), or None if it is not a plain DNS name."""
    try:
        ascii_host = idna.encode(host, uts46=True, transitional=False).decode("ascii").lower()
    except (UnicodeError, ValueError):
        return None
    return ascii_host if _HOST.match(ascii_host) else None


class EgressPolicy:
    def __init__(self, allow: Sequence[str], *, allow_schemes: Sequence[str] = ("https",)) -> None:
        self._exact: set[str] = set()
        self._parents: set[str] = set()
        for entry in allow:
            self._add(entry)
        self._schemes = {s.lower() for s in allow_schemes}
        self.decisions: list[Decision] = []
        self.blocked: list[Decision] = []

    def _add(self, entry: str) -> None:
        wildcard = entry.startswith("*.")
        host = _normalise_host(entry[2:] if wildcard else entry)
        if host is None or _is_ip_label(host) or (wildcard and "." not in host):
            raise ValueError(f"invalid egress allowlist entry: {entry!r}")
        (self._parents if wildcard else self._exact).add(host)

    def _matches(self, host: str) -> bool:
        return host in self._exact or any(host.endswith("." + p) for p in self._parents)

    def _decide(self, raw: str) -> Decision:
        def block(reason: str, host: str | None = None, scheme: str | None = None) -> Decision:
            return Decision(False, reason, sanitise_url(raw), host and mask_text(host), scheme)

        # Anything a browser would rewrite before parsing (C0 or space at the ends, tab/LF/CR
        # inside, backslashes) is refused outright, so the gate never judges a different URL
        # than the one the browser would load. Nested schemes fail the scheme allowlist below.
        if not raw or len(raw) > MAX_URL_LENGTH:
            return block("invalid_url")
        if any(ch.isspace() or ch == "\\" or ord(ch) < 32 or ord(ch) == 127 for ch in raw):
            return block("invalid_url")
        base, _, _fragment = raw.partition("#")
        base, _, query = base.partition("?")
        m = _SCHEME.match(base)
        if m is None:
            return block("invalid_url")
        scheme, rest = m.group(1).lower(), m.group(2)
        if scheme not in self._schemes:
            return block("scheme_not_allowed", scheme=scheme)
        if not rest.startswith("//"):
            return block("invalid_url", scheme=scheme)
        authority = rest[2:].split("/", 1)[0]
        if not authority or "@" in authority or "%" in authority:
            return block("invalid_url", scheme=scheme)
        if "[" in authority or "]" in authority:
            return block("ip_literal", scheme=scheme)
        host, _, port = authority.partition(":")
        if ":" in port or (port and not (port.isascii() and port.isdigit() and int(port) <= 65535)):
            return block("invalid_url", scheme=scheme)
        ascii_host = _normalise_host(host)
        if ascii_host is None:
            return block("invalid_url", scheme=scheme)
        if _is_ip_label(ascii_host):
            return block("ip_literal", ascii_host, scheme)
        if not self._matches(ascii_host):
            return block("host_not_allowlisted", ascii_host, scheme)
        clean = sanitise_url(f"{scheme}://{ascii_host}{rest[2:][len(authority) :]}")
        decoded = unquote_plus(query)
        if query and (mask_text(query) != query or mask_text(decoded) != decoded):
            return Decision(False, "sensitive_query", clean, mask_text(ascii_host), scheme)
        return Decision(True, "allowed", clean, mask_text(ascii_host), scheme)

    def check(self, url: str, *, redirect_from: str | None = None) -> Decision:
        d = self._decide(url)
        if redirect_from is not None:
            d = Decision(d.allowed, d.reason, d.url, d.host, d.scheme, sanitise_url(redirect_from))
        self.decisions.append(d)
        if not d.allowed:
            self.blocked.append(d)
        return d
