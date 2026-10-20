"""A taught browse step: call the isolated browser and record each observed action."""

from __future__ import annotations

import base64
import hashlib
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import jsonschema
from tilo_browser.session import SessionRefused
from tilo_harness.executor import UnitOutcome
from tilo_harness.outputs import UnitOutput
from tilo_memory.artifacts import NewVersion, Origin

from tilo_api.events import new_part_id

_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[4] / "contracts/browser.schema.json").read_text(encoding="utf-8")
)
_ACTION = jsonschema.Draft202012Validator({"$defs": _SCHEMA["$defs"], "$ref": "#/$defs/action"})
_MAX_TEXT = 30_000
_MAX_INVALID = 3  # BR-01: an invalid reply counts as a step; this many in a row end the session


class BrowseStepExecutor:
    def __init__(self, run: Any, rpc: Any, propose: Callable[[str, bytes, str], Any]) -> None:
        self.run, self.rpc, self.propose = run, rpc, propose

    def _save(self, session: str, step: int, unit: str, agent: str, result: dict) -> dict:
        artifact = result["screenshot_artifact"]
        frame = base64.b64decode(artifact["base64"], validate=True)
        if hashlib.sha256(frame).hexdigest() != artifact["sha256"]:
            raise ValueError("the browser frame did not match its digest")
        ident = f"art_bs{session[3:]}_{step}"
        ref = {"artifact_id": ident, "version": 1}
        store, scope = self.run.seams.artifacts, self.run.scope
        existing = store.head(scope, ref)
        if existing is not None:
            if store.read(scope, ref) != frame:
                raise ValueError("a browser frame changed on retry")
            return ref
        made = store.with_new_id(lambda: ident).put(
            scope,
            NewVersion(
                media_type="image/png",
                content=frame,
                run_id=self.run.run_id,
                origin=Origin(kind="browser", unit=unit, agent=agent),
                idempotency_key=None,
            ),
        )
        return made.ref

    def execute(
        self, *, unit: dict, agent: str, building: str, goal: str, hosts: list[str], max_steps: int = 12
    ) -> UnitOutcome:
        if not hosts or not 1 <= max_steps <= 60:
            return UnitOutcome(False, reason="The browser has no approved site or step limit.")
        session = "bs_" + new_part_id()
        opened, step, outcome = False, 0, "error"
        stop_charge = 0.0
        extracted: list[str] = []
        history: list[str] = []
        last: dict | None = None
        try:
            try:
                last = self.rpc.start(
                    {
                        "session": session,
                        "world_id": self.run.world_id,
                        "run_id": self.run.run_id,
                        "unit_id": unit["id"],
                        "allow_hosts": hosts,
                        "start_url": f"https://{hosts[0]}/",
                        "viewport": {"width": 1200, "height": 800},
                    }
                )
            except SessionRefused as exc:
                return UnitOutcome(False, reason=f"The browser service is unavailable ({exc.reason}).")
            opened = True
            frame = self._save(session, 0, unit["id"], agent, last)
            self.run.put(
                "browser.started",
                agent,
                building,
                "Tilo opened the browser.",
                {
                    "session": session,
                    "host": urlsplit(last["url"]).hostname,
                    "hosts": len(hosts),
                    "max_steps": max_steps,
                    "frame": frame,
                },
                district=unit["district"],
            )
            if last["login_required"]:
                outcome = "needs_person"
                return UnitOutcome(False, reason="This site needs you to sign in; Tilo never enters credentials.")
            served, invalid, finishing = 0, 0, False  # acts tilo-browser carried out; invalid replies in a row
            for step in range(1, max_steps + 1):
                if getattr(self.run, "paused", lambda: False)():
                    outcome = "stopped"
                    step -= 1
                    return UnitOutcome(False, reason="The world was paused.")
                control = getattr(getattr(self.run, "store", None), "browser_controls", {}).pop(session, None)
                if control == "stop":
                    self.run.put(
                        "browser.controlled",
                        self.run.owner,
                        building,
                        "You stopped the browser.",
                        {"session": session, "op": "stop", "step": step - 1},
                        district=unit["district"],
                    )
                    outcome = "stopped"
                    step -= 1
                    return UnitOutcome(False, reason="You stopped the browser.")
                screenshot = base64.b64decode(last["screenshot_artifact"]["base64"], validate=True)
                proposed = self.propose(
                    goal
                    + "\nApproved hosts: "
                    + ", ".join(hosts)
                    + "\nCompleted browser actions: "
                    + ", ".join(history),
                    screenshot,
                    "\n\n".join(extracted)[-_MAX_TEXT:],
                )
                action, charge = proposed if isinstance(proposed, tuple) and len(proposed) == 2 else (proposed, 0.0)
                if not isinstance(charge, (int, float)) or not math.isfinite(charge) or charge < 0:
                    raise ValueError("browser model returned an invalid charge")
                if not isinstance(action, dict) or not _ACTION.is_valid(action):
                    self._record_refusal(
                        session, step, unit, agent, building, last, "navigate", "invalid_action", credits=charge
                    )
                    invalid += 1
                    if invalid >= _MAX_INVALID:
                        return UnitOutcome(False, reason="The browser model gave no usable action.")
                    history.append("invalid")
                    continue
                invalid = 0
                kind = action["kind"]
                if kind == "done" and not extracted:  # code reads the page the person watched it reach, then ends
                    action, kind, finishing = {"kind": "extract"}, "extract", True
                if kind in ("done", "ask"):
                    outcome = "done" if kind == "done" else "needs_person"
                    stop_charge = charge
                    break
                if kind not in ("navigate", "click", "type", "scroll", "extract"):
                    self._record_refusal(
                        session, step, unit, agent, building, last, kind, "invalid_action", credits=charge
                    )
                    return UnitOutcome(False, reason="The browser proposed an unsupported action.")
                digest, target_name, target_box = None, "", None
                try:
                    if kind in ("click", "type"):
                        found = self.rpc.inspect(session, action["at"])
                        digest, target_name, target_box = (found["digest"], found["facts"]["name"], found["target_box"])
                    last = self.rpc.act(
                        session,
                        {"session": session, "step": served + 1, "action": action, "digest": digest, "outbox_id": None},
                    )
                    served += 1
                except SessionRefused as exc:
                    gated = exc.reason == "needs_person"
                    event_reason = exc.reason if exc.reason in _SCHEMA["$defs"]["reason"]["enum"] else "engine_error"
                    self._record_refusal(
                        session,
                        step,
                        unit,
                        agent,
                        building,
                        last,
                        kind,
                        None if gated else event_reason,
                        gated=gated,
                        box=target_box,
                        credits=charge,
                    )
                    outcome = "needs_person" if gated else "session_lost" if exc.reason == "session_lost" else "error"
                    return UnitOutcome(
                        False, reason="This browser action needs you." if gated else "The browser stopped safely."
                    )
                frame = self._save(session, step, unit["id"], agent, last)
                host = urlsplit(last["url"]).hostname
                caption = self._caption(kind, target_name, host, action)
                self.run.put(
                    "browser.acted",
                    agent,
                    building,
                    caption,
                    {
                        "session": session,
                        "step": step,
                        "kind": kind,
                        "verdict": "done",
                        "reason": None,
                        "host": host,
                        "chars": len(action["text"]) if kind == "type" else None,
                        "masked": last["masked"],
                        "blocked": last["blocked"],
                        "frame": frame,
                        "target_box": last["target_box"],
                        "caption": caption,
                    },
                    district=unit["district"],
                    credits=charge,
                )
                if last["login_required"]:
                    outcome = "needs_person"
                    return UnitOutcome(False, reason="This site needs you to sign in; Tilo never enters credentials.")
                if kind == "extract" and last["text"]:
                    extracted.append(last["text"])
                history.append(kind)
                if finishing:
                    outcome = "done"
                    break
            else:
                outcome = "cap_steps"
            if outcome == "done" and extracted:
                body = "\n\n".join(extracted)[:_MAX_TEXT]
                return UnitOutcome(
                    True, "Read the allowlisted pages.", outputs=(UnitOutput("text/markdown", body.encode()),)
                )
            return UnitOutcome(False, reason="The browser stopped before it had page text to summarize.")
        finally:
            if opened:
                try:
                    self.rpc.end(session)
                except SessionRefused as exc:
                    outcome = "session_lost" if exc.reason == "session_lost" else "error"
                if not getattr(self.run, "paused", lambda: False)():
                    self.run.put(
                        "browser.stopped",
                        agent,
                        building,
                        "Tilo closed the browser.",
                        {"session": session, "outcome": outcome, "steps": step},
                        district=unit["district"],
                        credits=stop_charge,
                    )

    def read_page(
        self, *, unit: dict, agent: str, building: str, url: str, host: str, also: tuple[str, ...] = ()
    ) -> str:
        """P0-RUNS-FIX: a research unit reads one allowlisted page in the visible browser, read-only and with no model:
        open it, extract its text, close. Each step is a recorded browser.* event with its real frame, so the World's
        browser panel shows exactly what Tilo read. Raises SessionRefused when the browser cannot read it (the caller
        then fetches the page directly and says so); returns the page text, possibly empty."""
        session = "bs_" + new_part_id()
        district = unit["district"]
        allow = list(dict.fromkeys((host, *also)))[:20]  # `also`: the known hosts a result link may redirect to
        last = self.rpc.start(
            {
                "session": session,
                "world_id": self.run.world_id,
                "run_id": self.run.run_id,
                "unit_id": unit["id"],
                "allow_hosts": allow,
                "start_url": url,
                "viewport": {"width": 1200, "height": 800},
            }
        )
        outcome, steps = "error", 0
        try:
            frame = self._save(session, 0, unit["id"], agent, last)
            started = {"session": session, "host": host, "hosts": len(allow), "max_steps": 1, "frame": frame}
            self.run.put("browser.started", agent, building, "Tilo opened the browser.", started, district=district)
            if last["login_required"]:
                outcome = "login_wall"
                raise SessionRefused("login_wall")
            action = {"kind": "extract"}
            last = self.rpc.act(
                session, {"session": session, "step": 1, "action": action, "digest": None, "outbox_id": None}
            )
            steps = 1
            frame = self._save(session, 1, unit["id"], agent, last)
            caption = f"Reading {host}"[:120]
            acted = {
                "session": session,
                "step": 1,
                "kind": "extract",
                "verdict": "done",
                "reason": None,
                "host": urlsplit(last["url"]).hostname,
                "chars": None,
                "masked": last["masked"],
                "blocked": last["blocked"],
                "frame": frame,
                "target_box": last["target_box"],
                "caption": caption,
            }
            self.run.put("browser.acted", agent, building, caption, acted, district=district)
            outcome = "done"
            return str(last["text"] or "")[:_MAX_TEXT]
        finally:
            try:
                self.rpc.end(session)
            except SessionRefused:
                outcome = "error" if outcome == "done" else outcome
            stopped = {"session": session, "outcome": outcome, "steps": steps}
            self.run.put("browser.stopped", agent, building, "Tilo closed the browser.", stopped, district=district)

    @staticmethod
    def _caption(kind: str, name: str, host: str | None, action: dict) -> str:
        if kind == "click":
            return f"Clicking {name or 'target'}"[:120]
        if kind == "type":
            return f"Typing in {name or 'field'}"[:120]
        if kind == "navigate":
            return f"Opening {host or 'page'}"[:120]
        if kind == "scroll":
            return f"Scrolling {action['direction']}"
        return "Reading page"

    def _record_refusal(
        self,
        session: str,
        step: int,
        unit: dict,
        agent: str,
        building: str,
        last: dict,
        kind: str,
        reason: str | None,
        *,
        gated: bool = False,
        box: dict | None = None,
        credits: float = 0.0,
    ) -> None:
        self.run.put(
            "browser.acted",
            agent,
            building,
            "Waiting for you" if gated else "Browser action stopped",
            {
                "session": session,
                "step": step,
                "kind": kind,
                "verdict": "gated" if gated else "refused",
                "reason": reason,
                "host": urlsplit(last["url"]).hostname,
                "chars": None,
                "masked": 0,
                "blocked": 0,
                "frame": None,
                **({"target_box": box} if box is not None else {}),
                "caption": "Waiting for you" if gated else "Browser action stopped",
            },
            district=unit["district"],
            credits=credits,
        )
