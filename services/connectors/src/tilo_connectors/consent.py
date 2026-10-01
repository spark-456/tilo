"""tilo_connectors.consent — incremental-scope consent for OAuth connectors (FR-CON-03, PRD 10.2, 12.1).

Asks for exactly the declared scopes of the capabilities a task needs, minus what the person already
granted; builds the consent card from the connector's own words; runs the Google authorisation-code
flow with PKCE (S256) and a single-use, 600 s state; and hands the exchanged tokens to the broker.
Only a person's Connect reaches `handle_callback`: building a card or a URL grants nothing (CR-13).
No token, code, verifier or client secret appears in a log, an error, an event or a repr. The state
table is in memory, so one `tilo-connectors` instance must serve a flow from start to callback until
the shared store lands with the Firestore adapter.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from ._time import add_seconds, parse_ts
from .tokens import TOKEN_URL, OAuthSettings, TokenBroker, post_form

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_ACCESS_LINE = "You sign in with Google; Tilo never sees your password."  # PRD 18.4, "Access"


class ConsentRefused(Exception):
    """The consent service will not do this. Messages are fixed text, never a code or a secret."""


@dataclass(frozen=True)
class ConsentResult:
    connector: str
    card_id: str
    granted_scopes: frozenset[str]


@dataclass(frozen=True)
class _Flow:
    user_id: str
    connector: str
    card_id: str
    verifier: str
    expires_at: str
    lines: dict[str, str]  # requested scope -> its plain-language line, in the order asked


class ConsentService:
    def __init__(
        self,
        *,
        connectors: Mapping[str, Mapping[str, Any]],
        broker: TokenBroker,
        http: Any,
        settings: OAuthSettings,
        clock: Callable[[], str],
        emit: Callable[[dict[str, Any]], None],
        state_ttl_s: int = 600,
    ) -> None:
        self._connectors, self._broker, self._http, self._settings = connectors, broker, http, settings
        self._clock, self._emit, self._ttl = clock, emit, state_ttl_s
        self._flows: dict[str, _Flow] = {}
        self._lock = threading.Lock()

    def scopes_needed(self, *, user_id: str, connector: str, capabilities: Sequence[str]) -> list[str]:
        return list(self._needed(user_id, connector, capabilities))

    def build_consent_card(
        self,
        *,
        user_id: str,
        connector: str,
        capabilities: Sequence[str],
        card_id: str,
        world_id: str,
        run_id: str,
        building: str,
        agent: str,
        what_happened: str,
        why_it_matters: str,
        timeout: int = 3600,
    ) -> dict[str, Any] | None:
        needed = self._needed(user_id, connector, capabilities)
        if not needed:
            return None
        lines = list(self._lines(connector, capabilities, needed).values())
        name = self._connectors[connector]["name"]
        reason = f"Tilo uses {name} only as listed above. {_ACCESS_LINE}"
        self._emit_part("connection.requested", user_id, {"connector": connector, "card_id": card_id})
        return {
            "id": card_id,
            "world_id": world_id,
            "run_id": run_id,
            "kind": "consent",
            "rung": "consent",
            "header": {"building": building, "agent": agent},
            "what_happened": what_happened,
            "why_it_matters": why_it_matters,
            "options": [
                {"id": "connect", "label": "Connect", "suggested": True, "reason": reason, "irreversible": False},
                {"id": "hold", "label": "Hold", "suggested": False, "irreversible": False},
            ],
            "add_context": False,
            "actions": ["show_me", "snooze"],
            "answer_channels": ["web", "mobile_web"],
            "created_at": self._clock(),
            "timeout": timeout,
            "safe_default": "hold",
            "gate": None,
            "consent": {"connector": connector, "scopes": lines},
        }

    def authorization_url(
        self, *, user_id: str, connector: str, capabilities: Sequence[str], card_id: str
    ) -> str | None:
        needed = self._needed(user_id, connector, capabilities)
        if not needed:
            return None
        verifier = secrets.token_urlsafe(48)  # 64 RFC 7636 characters
        state = secrets.token_urlsafe(32)
        flow = _Flow(
            user_id,
            connector,
            card_id,
            verifier,
            add_seconds(self._clock(), self._ttl),
            self._lines(connector, capabilities, needed),
        )
        with self._lock:
            now = parse_ts(self._clock())
            self._flows = {k: f for k, f in self._flows.items() if parse_ts(f.expires_at) >= now}  # drop stale
            self._flows[state] = flow
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=")
        query = {
            "client_id": self._settings.client_id,
            "redirect_uri": self._settings.redirect_uri,
            "response_type": "code",
            "scope": " ".join(needed),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "code_challenge": challenge.decode("ascii"),
            "code_challenge_method": "S256",
            "state": state,
        }
        return f"{AUTH_URL}?{urlencode(query)}"

    def handle_callback(
        self, *, user_id: str, state: str, code: str | None = None, error: str | None = None
    ) -> ConsentResult:
        with self._lock:  # every state is spent by its first use, whoever presents it
            flow = self._flows.pop(state, None)
        if flow is None or flow.user_id != user_id or parse_ts(self._clock()) > parse_ts(flow.expires_at):
            raise ConsentRefused("this consent link is not valid; start again")
        if error is not None or not code:
            raise ConsentRefused("consent was not granted")
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._settings.redirect_uri,
            "client_id": self._settings.client_id,
            "client_secret": self._settings.client_secret,
            "code_verifier": flow.verifier,
        }
        answer = post_form(self._http, TOKEN_URL, form)
        if answer is None or answer[0] != 200 or not isinstance(answer[1].get("access_token"), str):
            raise ConsentRefused("Google did not accept the sign-in; start again")
        response = answer[1]
        granted = frozenset(str(response.get("scope", "")).split())
        lines = [line for scope, line in flow.lines.items() if scope in granted]
        if not lines:
            raise ConsentRefused("none of the access asked for was granted")
        authz = {"by": "person", "ref": user_id, "at": self._clock()}
        data = {"connector": flow.connector, "card_id": flow.card_id, "scopes": lines}
        self._emit_part("connection.consented", user_id, data, authz)
        self._broker.store_tokens(user_id, flow.connector, response)
        return ConsentResult(flow.connector, flow.card_id, granted)

    # -- internals ------------------------------------------------------------------------------

    def _emit_part(
        self, event_type: str, user_id: str, data: dict[str, Any], authz: dict[str, Any] | None = None
    ) -> None:
        self._emit({"type": event_type, "authz": authz, "data": data, "user_id": user_id})

    def _declaration(self, connector: str, capabilities: Sequence[str]) -> Mapping[str, Any]:
        decl = self._connectors.get(connector)
        if decl is None or decl.get("auth") != "oauth2":
            raise ConsentRefused("this connector has no sign-in to consent to")
        declared = decl.get("scopes", {})
        if any(c not in declared for c in capabilities):
            raise ConsentRefused("this connector does not declare that capability")
        return decl

    def _needed(self, user_id: str, connector: str, capabilities: Sequence[str]) -> list[str]:
        decl = self._declaration(connector, capabilities)
        granted = self._broker.granted_scopes(user_id, connector)
        wanted = [s for c in capabilities for s in decl["scopes"][c]]
        return [s for i, s in enumerate(wanted) if s not in granted and s not in wanted[:i]]

    def _lines(self, connector: str, capabilities: Sequence[str], needed: list[str]) -> dict[str, str]:
        """scope -> the plain-language line: the description of the declared action(s) that need it."""
        decl = self._connectors[connector]
        lines: dict[str, list[str]] = {scope: [] for scope in needed}
        for capability in capabilities:
            for scope in decl["scopes"][capability]:
                for action in decl["actions"]:
                    text = action["description"]
                    if scope in lines and action["capability"] == capability and text not in lines[scope]:
                        lines[scope].append(text)
        return {scope: " ".join(texts) for scope, texts in lines.items()}
