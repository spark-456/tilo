"""ADR-0042 amendment 1 (owner decision 21 Oct, BQ-MTG-ACTIONS-1): the bot side of tilo-api's meeting actions route.

Only under `LIVE=1`, with `TILO_API_URL` set and the action nonce the attend call carried (`X-Tilo-Meeting-Actions`,
present only while the owner has set `TILO_MEETING_ACTIONS=1` on tilo-api). One bounded POST per confirmed action with
the bot's own ID token; the answer is a fixed outcome word. The nonce, the token and any text are never logged: the
`bot.cloud_run` stage line carries the action name and the outcome word only."""

from __future__ import annotations

import json
import logging
import secrets
import time
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

import httpx

from .voice_meter import _API_URL, CLAIM_RE, IdentityToken

ACTIONS_HEADER = "X-Tilo-Meeting-Actions"
ROUTE = "/internal/meeting-actions/run"
ACTIONS = ("create_pin", "add_agenda_item", "create_meeting")
TIMEOUT_S, MAX_ANSWER, MAX_CONTEXT = 6.0, 2048, 16384
# The context read's fields (meeting_context on tilo-api), each list bounded; anything else in an answer is dropped.
_CONTEXT_LISTS = {
    "teams": (10, {"name": str, "lead": bool}),
    "teammates": (20, {"name": str, "lead": bool}),
    "pins": (15, {"title": str, "board": str}),
    "meetings": (8, {"title": str, "start": str, "status": str}),
    "worlds": (5, {"title": str, "status": str}),
}
_OUTCOMES = frozenset(
    {
        "done",
        "unknown_person",
        "ambiguous_person",
        "cap_reached",
        "team_unclear",
        "no_team",
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

    def context(self, one_on_one: bool) -> dict[str, Any] | None:
        """The meeting owner's workspace, compact (one-on-one: theirs; a group: what their teams share), or None."""
        body = {
            "meeting_id": self._meeting,
            "claim": self._claim,
            "key": secrets.token_urlsafe(12),
            "speaker": None,  # never a speaker: the read is always the owner's own view
            "action": "context",
            "args": {"one_on_one": one_on_one},
        }
        got = self._exchange(body, MAX_CONTEXT)
        raw = got[1].get("context") if got is not None and got[0] == 200 and isinstance(got[1], dict) else None
        context = _compact(raw) if isinstance(raw, dict) and got[1].get("outcome") == "done" else None
        ops.warning("stage workspace scope=%s ok=%s", "one_on_one" if one_on_one else "group", context is not None)
        return context

    def _post(self, body: dict[str, Any]) -> ActionResult:
        got = self._exchange(body, MAX_ANSWER)
        if got is None:
            return ActionResult(False, "unavailable", {})
        status, answer = got
        outcome = answer.get("outcome") if isinstance(answer, dict) else None
        if status == 200 and outcome == "done":
            info = {k: answer[k] for k in ("board", "start") if isinstance(answer.get(k), str)}
            return ActionResult(True, "done", info)
        word = outcome if isinstance(outcome, str) and outcome in _OUTCOMES and outcome != "done" else "refused"
        return ActionResult(False, word if status in (404, 409) else "unavailable", {})

    def _exchange(self, body: dict[str, Any], cap: int) -> tuple[int, Any] | None:
        """One bounded POST: (status, decoded answer), or None on any transport, size, time or decoding failure."""
        try:
            token = self._token_for(self._base)
        except Exception:
            return None
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
                    if len(data) > cap or time.monotonic() > deadline:
                        return None
                status = response.status_code
            return status, (json.loads(bytes(data)) if data else {})
        except Exception:  # transport, timeout, a non-JSON answer: nothing was confirmed
            return None


def _compact(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Only the known fields, strings cut to 80 characters, lists to their bound; everything else is dropped."""
    out: dict[str, Any] = {}
    for key in ("you", "role"):
        if isinstance(raw.get(key), str):
            out[key] = raw[key][:80]
    for key, (limit, shape) in _CONTEXT_LISTS.items():
        rows = raw.get(key)
        if not isinstance(rows, list):
            continue
        out[key] = [
            {f: (row[f][:80] if kind is str else row[f]) for f, kind in shape.items() if isinstance(row.get(f), kind)}
            for row in rows[:limit]
            if isinstance(row, dict)
        ]
    return out


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
