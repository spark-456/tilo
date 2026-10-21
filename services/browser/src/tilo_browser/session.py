"""Internal browser session RPC. One action and one masked frame per response."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlsplit

import yaml

from tilo_browser.egress import EgressPolicy, sanitise_url
from tilo_browser.login import is_secure_node, iter_nodes, node_ref, secure_nodes
from tilo_browser.masking import mask_text
from tilo_browser.worker import BrowserWorker


class SessionRefused(Exception):
    def __init__(self, reason: str, status: int = 409) -> None:
        super().__init__(reason)
        self.reason, self.status = reason, status


_CONFIG = Path(__file__).resolve().parents[4] / "config" / "browser.yaml"


def _idle_seconds() -> float:
    """BR-12: config/browser.yaml `idle_timeout_s`; 120 when the file cannot be read."""
    try:
        value = float(yaml.safe_load(_CONFIG.read_text(encoding="utf-8"))["idle_timeout_s"])
    except Exception:  # noqa: BLE001 - a missing or broken file keeps the contract's default
        return 120.0
    return value if 0 < value <= 3600 else 120.0


IDLE_SECONDS = _idle_seconds()  # a session no call touched for this long lost its caller (timed out or stopped)


def _read_text(text: str, search_line: str) -> str:
    """A read's text (the contract's 20,000 characters at most), the search line kept at its end."""
    return text[: 20000 - len(search_line)] + search_line


@dataclass
class _Session:
    worker: BrowserWorker
    viewport: dict[str, int]
    used: float
    step: int = 0
    blocked_seen: int = 0


_COMMIT = re.compile(
    r"\b(submit|post|send|buy|pay|purchase|checkout|sign[ -]?in|log[ -]?in|delete|confirm|book)\b", re.I
)
_SEARCHABLE = ("", "text", "search")  # input types an Enter may submit a GET form from (a site's search box)
_CONTROL_TAGS = frozenset({"input", "textarea", "select", "button", "a"})
_CONTROL_ROLES = frozenset(
    {"textbox", "searchbox", "combobox", "button", "link", "checkbox", "radio", "switch", "tab", "menuitem", "option"}
)


def _get_search_field(attrs: dict) -> bool:
    """BR-05: Enter in this field submits a GET form (a search), which is not a commit: a text or search input whose
    form's method is get. A field outside a form, in a post or dialog form, or of any other type is never submitted."""
    return str(attrs.get("form_method", "none")).lower() == "get" and str(attrs.get("type", "")).lower() in _SEARCHABLE


class BrowserSessions:
    def __init__(self, engine: Any, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.engine = engine
        self.sessions: dict[str, _Session] = {}
        self._lock = RLock()
        self._clock = clock

    def _close_idle(self) -> None:
        now = self._clock()
        for session, state in list(self.sessions.items()):
            if now - state.used > IDLE_SECONDS:
                del self.sessions[session]
                try:
                    state.worker.close()
                except Exception:  # noqa: BLE001 - a browser that already died has nothing left to close
                    pass

    def _touch(self, session: str) -> _Session:
        state = self.sessions.get(session)
        if state is None:
            raise SessionRefused("session_lost", 404)
        state.used = self._clock()
        return state

    @staticmethod
    def _viewport_box(viewport: dict[str, int]) -> dict[str, int]:
        return {"x": 0, "y": 0, "width": viewport["width"], "height": viewport["height"]}

    @staticmethod
    def _target(worker: BrowserWorker, at: dict[str, int], viewport: dict[str, int]) -> tuple[str, dict, dict]:
        """The element at the point (the contract's 0..999 grid; boxes are CSS pixels): of the nodes whose box holds it,
        a control (field, button, link) before a container with a role, then the smallest, as a person's click lands on
        the innermost thing under the mouse (live 21 Oct: a page's role="search" or role="main" holds every field and
        link in it). Two candidates alike in both are no one target: refused."""
        px = at["x"] * viewport["width"] / 999
        py = at["y"] * viewport["height"] / 999
        matches = []
        for node in iter_nodes(worker._driver.read_accessibility_tree()):
            box = node.get("attrs", {}).get("box")
            if not isinstance(box, dict) or not node_ref(node):
                continue
            if box["x"] <= px < box["x"] + box["width"] and box["y"] <= py < box["y"] + box["height"]:
                matches.append((node_ref(node), node, box))

        def rank(match: tuple[str, dict, dict]) -> tuple[int, int]:
            node, box = match[1], match[2]
            control = node.get("attrs", {}).get("tag") in _CONTROL_TAGS or node.get("role") in _CONTROL_ROLES
            return (0 if control else 1, box["width"] * box["height"])

        matches.sort(key=rank)
        if not matches or (len(matches) > 1 and rank(matches[0]) == rank(matches[1])):
            raise SessionRefused("target_changed")
        return matches[0]

    @staticmethod
    def _search_line(state: _Session) -> str:
        """DEMO-BROWSER: the site's own search address, told at the end of a read when it is inside this session's
        allowlist, so a reader can open a search like any page (a form submit itself stays a person's)."""
        find = getattr(state.worker._driver, "search_address", None)
        address = find() if find is not None else None
        if not isinstance(address, str) or address.count("{words}") != 1:
            return ""
        if not state.worker._policy._decide(address.replace("{words}", "words")).allowed:  # not counted as blocked
            return ""
        return mask_text(f"\nSearch this site: {address} (put the words to look for in place of {{words}})")

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
            "text": _read_text(capture.text, BrowserSessions._search_line(state)) if kind == "extract" else "",
            "masked": len(secure_nodes(state.worker._driver.read_accessibility_tree())),
            "blocked": blocked,
            "login_required": state.worker._login_wall,
        }

    def start(self, body: dict) -> dict:
        with self._lock:
            self._close_idle()
            session = body["session"]
            if session in self.sessions:
                raise SessionRefused("session_exists")
            policy = EgressPolicy(allow=body["allow_hosts"])
            engine = self.engine.for_viewport(body["viewport"]) if hasattr(self.engine, "for_viewport") else self.engine
            worker = BrowserWorker(engine, policy)
            state = _Session(worker, body["viewport"], self._clock())
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
            state = self._touch(session)
            step, action = body["step"], body["action"]
            if step != state.step + 1 or step > 60:
                raise SessionRefused("step_cap")
            kind = action["kind"]
            box = self._viewport_box(state.viewport)
            driver = state.worker._driver
            if kind in ("click", "type"):
                ref, node, box = self._target(state.worker, action["at"], state.viewport)
                if body.get("digest") != self._digest(state.worker, node):
                    raise SessionRefused("target_changed")
                if is_secure_node(node):
                    raise SessionRefused("secure_field")
                attrs = node.get("attrs", {})
                label = f"{node.get('name', '')} {attrs.get('value', '')}"
                # A click on a form's submit control is the person's; a click into one of its fields only focuses it.
                form_submit = kind == "click" and (
                    attrs.get("type") in ("submit", "image")
                    or (
                        node.get("role") == "button"
                        and str(attrs.get("form_method", "none")).lower() not in ("none", "")
                    )
                )
                if _COMMIT.search(label) or form_submit:
                    raise SessionRefused("needs_person")
                if kind == "type":
                    if action.get("submit") and not _get_search_field(attrs):
                        raise SessionRefused("needs_person")
                    value = action["text"]
                    if mask_text(value) != value:
                        raise SessionRefused("secret_text")
                    state.worker.type(ref, value)
                    if action.get("submit"):  # Enter in a site's search box: a GET search, each hop egress-gated
                        state.worker.press("Enter")
                else:
                    state.worker.click(ref)
                if getattr(driver, "posted", None):  # the page tried to post a form after all: that stays a person's
                    raise SessionRefused("needs_person")
            elif kind == "navigate":
                state.worker.navigate(action["url"])
            elif kind == "scroll":
                scroll = getattr(state.worker._driver, "scroll", None)
                if scroll is None:
                    raise SessionRefused("unsupported_action")
                scroll(action["direction"])
            elif kind != "extract":
                raise SessionRefused("unsupported_action")
            if kind in ("click", "type", "scroll"):  # where the mouse really acted, when the driver measured it
                box = getattr(driver, "last_box", None) or box
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
            "input_type": attrs.get("type") or None,
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
            state = self._touch(session)
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
