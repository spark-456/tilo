"""A taught browse step: call the isolated browser and record each observed action."""

from __future__ import annotations

import base64
import hashlib
import json
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


class BrowseStepExecutor:
    def __init__(self, run: Any, rpc: Any, propose: Callable[[str, bytes, str], dict]) -> None:
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
        extracted: list[str] = []
        last: dict | None = None
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
            for step in range(1, max_steps + 1):
                screenshot = base64.b64decode(last["screenshot_artifact"]["base64"], validate=True)
                action = self.propose(goal, screenshot, "\n\n".join(extracted)[-_MAX_TEXT:])
                if not isinstance(action, dict) or not _ACTION.is_valid(action):
                    self._record_refusal(session, step, unit, agent, building, last, "navigate", "invalid_action")
                    return UnitOutcome(False, reason="The browser proposed an invalid action.")
                kind = action["kind"]
                if kind in ("done", "ask"):
                    outcome = "done" if kind == "done" else "needs_person"
                    break
                if kind not in ("navigate", "click", "type", "scroll", "extract"):
                    self._record_refusal(session, step, unit, agent, building, last, kind, "invalid_action")
                    return UnitOutcome(False, reason="The browser proposed an unsupported action.")
                digest, target_name, target_box = None, "", None
                if kind in ("click", "type"):
                    found = self.rpc.inspect(session, action["at"])
                    digest, target_name, target_box = found["digest"], found["facts"]["name"], found["target_box"]
                try:
                    last = self.rpc.act(
                        session,
                        {"session": session, "step": step, "action": action, "digest": digest, "outbox_id": None},
                    )
                except SessionRefused as exc:
                    gated = exc.reason == "needs_person"
                    self._record_refusal(
                        session,
                        step,
                        unit,
                        agent,
                        building,
                        last,
                        kind,
                        None if gated else exc.reason,
                        gated=gated,
                        box=target_box,
                    )
                    outcome = "needs_person" if gated else "error"
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
                )
                if last["login_required"]:
                    outcome = "needs_person"
                    return UnitOutcome(False, reason="This site needs you to sign in; Tilo never enters credentials.")
                if kind == "extract" and last["text"]:
                    extracted.append(last["text"])
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
                self.rpc.end(session)
                self.run.put(
                    "browser.stopped",
                    agent,
                    building,
                    "Tilo closed the browser.",
                    {"session": session, "outcome": outcome, "steps": step},
                    district=unit["district"],
                )

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
        )
