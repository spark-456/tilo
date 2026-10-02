"""Egress allowlist for browser workers (PRD 12.3, 16.2, SEC-09). Deterministic, no network.

`EgressPolicy.check` is the one gate every request passes (navigation, each redirect hop,
subresources, a click's navigation). Anything it cannot parse unambiguously is blocked. A
`Decision` never holds userinfo, query or fragment, so the log and `EgressBlocked` messages
cannot leak them.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import unquote_plus

from tilo_browser.masking import mask_text

_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):(.*)$", re.S)
_HOST = re.compile(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)*$")
_NUMERIC_LABEL = re.compile(r"^(?:\d+|0[xX][0-9a-fA-F]*)$")
_UNSAFE_LOG = re.compile(r"[^A-Za-z0-9._~:/%!$&'()*+,;=-]")


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str  # allowed | host_not_allowlisted | scheme_not_allowed | ip_literal | invalid_url | sensitive_query
    url: str  # sanitised: no userinfo, no query, no fragment
    host: str | None  # lower-case, IDNA A-label form
    scheme: str | None
    redirect_from: str | None = None


class EgressBlocked(Exception):
    def __init__(self, decision: Decision) -> None:
        super().__init__(f"egress blocked ({decision.reason}): {decision.url}")
        self.decision = decision


def sanitise_url(raw: str) -> str:
    """Best-effort log form of any string: cut query, fragment and userinfo, replace odd characters."""
    base = re.split(r"[?#]", raw, maxsplit=1)[0][:200]
    m = re.match(r"^([^/\\]*://)([^/\\]*)(.*)$", base, re.S)
    if m:
        base = m.group(1) + m.group(2).rsplit("@", 1)[-1] + m.group(3)
    return _UNSAFE_LOG.sub("_", base)


def _is_ip_label(host: str) -> bool:
    return _NUMERIC_LABEL.match(host.rsplit(".", 1)[-1]) is not None


def _normalise_host(host: str) -> str | None:
    """Lower-case IDNA A-label form, or None if it is not a plain DNS name."""
    try:
        ascii_host = host.lower().encode("idna").decode("ascii")
        ascii_host.encode("ascii").decode("idna")  # an invalid A-label does not round-trip
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
            return Decision(False, reason, sanitise_url(raw), host, scheme)

        if not raw or any(ch.isspace() or ch == "\\" or ord(ch) < 32 or ord(ch) == 127 for ch in raw):
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
            return Decision(False, "sensitive_query", clean, ascii_host, scheme)
        return Decision(True, "allowed", clean, ascii_host, scheme)

    def check(self, url: str, *, redirect_from: str | None = None) -> Decision:
        d = self._decide(url)
        if redirect_from is not None:
            d = Decision(d.allowed, d.reason, d.url, d.host, d.scheme, sanitise_url(redirect_from))
        self.decisions.append(d)
        if not d.allowed:
            self.blocked.append(d)
        return d
