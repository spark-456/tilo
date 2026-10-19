"""Internal browser session RPC. One action and one masked frame per response."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from threading import RLock
from typing import Any
from urllib.parse import urlsplit

from tilo_browser.egress import EgressPolicy, sanitise_url
from tilo_browser.login import is_secure_node, iter_nodes, node_ref, secure_nodes
from tilo_browser.masking import mask_text
from tilo_browser.worker import BrowserWorker


class SessionRefused(Exception):
    def __init__(self, reason: str, status: int = 409) -> None:
        super().__init__(reason)
        self.reason, self.status = reason, status


@dataclass
class _Session:
    worker: BrowserWorker
    viewport: dict[str, int]
    step: int = 0
    blocked_seen: int = 0


_COMMIT = re.compile(
    r"\b(submit|post|send|buy|pay|purchase|checkout|sign[ -]?in|log[ -]?in|delete|confirm|book)\b", re.I
)


class BrowserSessions:
    def __init__(self, engine: Any) -> None:
        self.engine = engine
        self.sessions: dict[str, _Session] = {}
        self._lock = RLock()

    @staticmethod
    def _viewport_box(viewport: dict[str, int]) -> dict[str, int]:
        return {"x": 0, "y": 0, "width": viewport["width"], "height": viewport["height"]}

    @staticmethod
    def _target(worker: BrowserWorker, at: dict[str, int], viewport: dict[str, int]) -> tuple[str, dict, dict]:
        # Point is the contract's 0..999 grid; boxes are CSS pixels.
        px = at["x"] * viewport["width"] / 999
        py = at["y"] * viewport["height"] / 999
        matches = []
        for node in iter_nodes(worker._driver.read_accessibility_tree()):
            box = node.get("attrs", {}).get("box")
            if not isinstance(box, dict) or not node_ref(node):
                continue
            if box["x"] <= px < box["x"] + box["width"] and box["y"] <= py < box["y"] + box["height"]:
                matches.append((node_ref(node), node, box))
        if len(matches) != 1:
            raise SessionRefused("target_changed")
        return matches[0]

    @staticmethod
    def _result(session: str, step: int, kind: str, state: _Session, box: dict) -> dict:
        capture = state.worker.capture()  # worker masks secure fields before returning bytes
        frame = capture.screenshot
        blocked_total = len(state.worker._policy.blocked)
        blocked = blocked_total - state.blocked_seen
        state.blocked_seen = blocked_total
        return {
            "session": session,
            "step": step,
            "kind": kind,
            "url": capture.url,
            "target_box": box,
            "screenshot_artifact": {
                "mime_type": "image/png",
                "sha256": hashlib.sha256(frame).hexdigest(),
                "base64": base64.b64encode(frame).decode("ascii"),
            },
            "text": capture.text[:20000] if kind == "extract" else "",
            "masked": len(secure_nodes(state.worker._driver.read_accessibility_tree())),
            "blocked": blocked,
            "login_required": state.worker._login_wall,
        }

    def start(self, body: dict) -> dict:
        with self._lock:
            session = body["session"]
            if session in self.sessions:
                raise SessionRefused("session_exists")
            policy = EgressPolicy(allow=body["allow_hosts"])
            engine = self.engine.for_viewport(body["viewport"]) if hasattr(self.engine, "for_viewport") else self.engine
            worker = BrowserWorker(engine, policy)
            state = _Session(worker, body["viewport"])
            try:
                worker.navigate(body["start_url"])
                result = self._result(session, 0, "start", state, self._viewport_box(state.viewport))
            except Exception:
                worker.close()
                raise
            self.sessions[session] = state
            return result

    def act(self, session: str, body: dict) -> dict:
        with self._lock:
            state = self.sessions.get(session)
            if state is None:
                raise SessionRefused("session_lost", 404)
            step, action = body["step"], body["action"]
            if step != state.step + 1 or step > 60:
                raise SessionRefused("step_cap")
            kind = action["kind"]
            box = self._viewport_box(state.viewport)
            if kind in ("click", "type"):
                ref, node, box = self._target(state.worker, action["at"], state.viewport)
                if body.get("digest") != self._digest(state.worker, node):
                    raise SessionRefused("target_changed")
                if is_secure_node(node):
                    raise SessionRefused("secure_field")
                attrs = node.get("attrs", {})
                label = f"{node.get('name', '')} {attrs.get('value', '')}"
                form_submit = kind == "click" and (
                    attrs.get("type") == "submit" or attrs.get("form_method", "none").lower() not in ("none", "")
                )
                if _COMMIT.search(label) or form_submit:
                    raise SessionRefused("needs_person")
                if kind == "type":
                    if action.get("submit"):
                        raise SessionRefused("needs_person")
                    value = action["text"]
                    if mask_text(value) != value:
                        raise SessionRefused("secret_text")
                    state.worker.type(ref, value)
                else:
                    state.worker.click(ref)
            elif kind == "navigate":
                state.worker.navigate(action["url"])
            elif kind == "scroll":
                scroll = getattr(state.worker._driver, "scroll", None)
                if scroll is None:
                    raise SessionRefused("unsupported_action")
                scroll(action["direction"])
            elif kind != "extract":
                raise SessionRefused("unsupported_action")
            result = self._result(session, step, kind, state, box)
            state.step = step
            return result

    @staticmethod
    def _facts(node: dict) -> dict:
        attrs = node.get("attrs", {})
        role = str(node.get("role", ""))
        return {
            "tag": str(attrs.get("tag", "input" if role == "textbox" else role or "div")),
            "role": role,
            "name": mask_text(str(node.get("name", "")))[:120],
            "input_type": attrs.get("type"),
            "editable": role in ("textbox", "searchbox"),
            "secure": is_secure_node(node),
            "form_method": str(attrs.get("form_method", "none")).lower(),
            "link_host": urlsplit(str(attrs.get("href", ""))).hostname or None,
            "download": bool(attrs.get("download", False)),
        }

    @classmethod
    def _digest(cls, worker: BrowserWorker, node: dict) -> str:
        facts = cls._facts(node)
        payload = json.dumps([sanitise_url(worker._url), facts], sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def inspect(self, session: str, at: dict[str, int]) -> dict:
        with self._lock:
            state = self.sessions.get(session)
            if state is None:
                raise SessionRefused("session_lost", 404)
            _, node, box = self._target(state.worker, at, state.viewport)
            return {
                "session": session,
                "facts": self._facts(node),
                "digest": self._digest(state.worker, node),
                "target_box": box,
            }

    def end(self, session: str) -> dict:
        with self._lock:
            state = self.sessions.pop(session, None)
            if state is None:
                raise SessionRefused("session_lost", 404)
            try:
                return self._result(session, state.step, "end", state, self._viewport_box(state.viewport))
            finally:
                state.worker.close()
