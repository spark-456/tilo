"""ADR-0042 amendment 1 (owner decision 21 Oct, BQ-MTG-ACTIONS-1): the bot side of tilo-api's meeting actions route.

Only under `LIVE=1`, with `TILO_API_URL` set and the action nonce the attend call carried (`X-Tilo-Meeting-Actions`,
present only while the owner has set `TILO_MEETING_ACTIONS=1` on tilo-api). One bounded POST per confirmed action with
the bot's own ID token; the answer is a fixed outcome word. The nonce, the token and any text are never logged: the
`bot.cloud_run` stage line carries the action name and the outcome word only."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

import httpx

from .voice_meter import _API_URL, CLAIM_RE, IdentityToken

ACTIONS_HEADER = "X-Tilo-Meeting-Actions"
ROUTE = "/internal/meeting-actions/run"
ACTIONS = ("create_pin", "add_agenda_item", "create_meeting")
TIMEOUT_S, MAX_ANSWER = 6.0, 2048
_OUTCOMES = frozenset(
    {
        "done",
        "unknown_person",
        "ambiguous_person",
        "cap_reached",
        "team_unclear",
        "agenda_full",
        "refused",
        "not_attending",
        "unavailable",
    }
)
ops = logging.getLogger("bot.cloud_run")


class ActionResult(NamedTuple):
    ok: bool
    outcome: str  # one fixed word
    info: dict[str, Any]  # the 200 answer's board or start; empty otherwise


class MeetingActions:
    """The confirmed action, sent once (the key makes a retry safe on tilo-api)."""

    def __init__(
        self,
        base_url: str,
        meeting_id: str,
        claim: str,
        *,
        token_for: Callable[[str], str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if _API_URL.fullmatch(base_url) is None or CLAIM_RE.fullmatch(claim) is None:
            raise ValueError("MeetingActions: not a valid API url or claim")
        self._base, self._meeting, self._claim = base_url, meeting_id, claim
        self._token_for = token_for or IdentityToken()
        self._transport = transport

    def __repr__(self) -> str:
        return "MeetingActions()"

    def run(self, action: str, args: Mapping[str, Any], speaker: str | None, key: str) -> ActionResult:
        if action not in ACTIONS:
            return ActionResult(False, "refused", {})
        body = {
            "meeting_id": self._meeting,
            "claim": self._claim,
            "key": key,
            "speaker": speaker,
            "action": action,
            "args": dict(args),
        }
        result = self._post(body)
        ops.warning("stage action name=%s outcome=%s", action, result.outcome)
        return result

    def _post(self, body: dict[str, Any]) -> ActionResult:
        try:
            token = self._token_for(self._base)
        except Exception:
            return ActionResult(False, "unavailable", {})
        try:
            with (
                httpx.Client(
                    transport=self._transport, timeout=TIMEOUT_S, follow_redirects=False, trust_env=False
                ) as client,
                client.stream(
                    "POST",
                    self._base + ROUTE,
                    content=json.dumps(body, separators=(",", ":")).encode(),
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                ) as response,
            ):
                data, deadline = bytearray(), time.monotonic() + 2 * TIMEOUT_S
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_ANSWER or time.monotonic() > deadline:
                        return ActionResult(False, "unavailable", {})
                status = response.status_code
            answer = json.loads(bytes(data)) if data else {}
        except Exception:  # transport, timeout, a non-JSON answer: nothing was confirmed
            return ActionResult(False, "unavailable", {})
        outcome = answer.get("outcome") if isinstance(answer, dict) else None
        if status == 200 and outcome == "done":
            info = {k: answer[k] for k in ("board", "start") if isinstance(answer.get(k), str)}
            return ActionResult(True, "done", info)
        word = outcome if isinstance(outcome, str) and outcome in _OUTCOMES and outcome != "done" else "refused"
        return ActionResult(False, word if status in (404, 409) else "unavailable", {})


def actions_from_env(
    meeting_id: str, claim: str | None, env: Mapping[str, str], **kwargs: Any
) -> MeetingActions | None:
    """The client, or None (no actions this call): only under `LIVE=1`, with `TILO_API_URL` and the attend's nonce."""
    if env.get("LIVE") != "1" or not claim:
        return None
    try:
        return MeetingActions(env.get("TILO_API_URL", ""), meeting_id, claim, **kwargs)
    except Exception:
        return None
