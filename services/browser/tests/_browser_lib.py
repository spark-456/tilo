"""Test doubles and plain data builders for services/browser acceptance tests
(FR-CON-07 isolation, allowlist egress and masking; FR-CON-08 login pages never filled).

Not a test module (leading underscore). No production code lives here (root CLAUDE.md
test-writer rule): everything below is a FAKE of a thing `tilo_browser` talks to (a headless
browser engine and the web it browses) or a literal builder for the data the tests feed it.
`tilo_browser` itself does not exist yet (see API.md in this directory); importing it is what
makes these tests fail until the builder ships P6.

This directory has no __init__.py, so pytest's default "prepend" import mode puts it on
sys.path (the same plain-module pattern services/connectors/tests uses). No real browser, no
network, no clock: every page, redirect and cookie below is scripted data.

Fake secrets are assembled at runtime (root CLAUDE.md: no secrets in code or fixtures; the
guard hook blocks secret-looking literals), from a fixed seed so failures reproduce.
"""

from __future__ import annotations

import base64
import json
import pathlib
import random
import string
from dataclasses import dataclass, field
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

WORLD = "w_01"
RUN = "r_01J8Z3K4M5"
HEADER = {"building": "B2", "agent": "A_s1"}
CARD_ID = "01J8Z3K4M5N6P7Q8R9S0T1V2W4"
NOW = "2026-10-02T09:30:00.000Z"
PNG = b"%PNG-fake"


# ---------------------------------------------------------------------------
# Fake secrets and PII, assembled at runtime from a fixed seed.


def _alnum(rnd: random.Random, n: int, alphabet: str = string.ascii_letters + string.digits) -> str:
    return "".join(rnd.choice(alphabet) for _ in range(n))


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _luhn_check_digit(body: str) -> str:
    total = 0
    for i, ch in enumerate(reversed(body)):
        d = int(ch)
        if i % 2 == 0:  # the digit that will sit next to the check digit is doubled
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


def luhn_valid_card(rnd: random.Random, prefix: str = "4", length: int = 16) -> str:
    body = prefix + "".join(rnd.choice(string.digits) for _ in range(length - len(prefix) - 1))
    return body + _luhn_check_digit(body)


def luhn_invalid_card(rnd: random.Random) -> str:
    good = luhn_valid_card(rnd)
    return good[:-1] + str((int(good[-1]) + 1) % 10)


def fake_secrets() -> dict[str, str]:
    """One runtime-assembled fake of each secret shape the masker must catch (PRD 16.1 rule 4,
    SEC-14). None of these is a real credential; none appears as a literal in this repo."""
    rnd = random.Random(20261002)
    header = _b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({"sub": "u_" + _alnum(rnd, 8), "iat": 1}).encode())
    return {
        "api_key": "s" + "k" + "-" + _alnum(rnd, 32),
        "github_token": "gh" + "p" + "_" + _alnum(rnd, 36),
        "aws_key_id": "AK" + "IA" + _alnum(rnd, 16, string.ascii_uppercase + string.digits),
        "jwt": f"{header}.{payload}.{_alnum(rnd, 43)}",
        "google_oauth": "ya" + "29" + "." + _alnum(rnd, 40),
        "bearer": _alnum(rnd, 40),
        "password": "pw-" + _alnum(rnd, 12),
        "kv_token": "tk_" + _alnum(rnd, 20),
    }


def fake_card_numbers() -> dict[str, str]:
    rnd = random.Random(7)
    plain = luhn_valid_card(rnd)
    return {
        "plain": plain,
        "spaced": " ".join(plain[i : i + 4] for i in range(0, 16, 4)),
        "dashed": "-".join(plain[i : i + 4] for i in range(0, 16, 4)),
        "invalid": luhn_invalid_card(rnd),
    }


EMAIL = "riya.sharma@example.org"
PHONE = "+65 9123 4567"


# ---------------------------------------------------------------------------
# Accessibility-tree builders (shape documented in API.md "Driver").


def node(role: str, label: str = "", *children: dict, value: str | None = None, **attrs: Any) -> dict:
    """`label` is the accessible name; DOM attributes (id, type, name, autocomplete, ...) go in attrs."""
    out: dict[str, Any] = {"role": role, "name": label, "attrs": dict(attrs), "children": list(children)}
    if value is not None:
        out["value"] = value
    return out


def textbox(ref: str, label: str, *, value: str | None = None, **attrs: Any) -> dict:
    attrs.setdefault("type", "text")
    return node("textbox", label, id=ref, value=value, **attrs)


def password_box(ref: str = "pw", label: str = "Password", *, value: str | None = None) -> dict:
    return textbox(ref, label, value=value, type="password", autocomplete="current-password")


def button(ref: str, label: str) -> dict:
    return node("button", label, id=ref)


def link(ref: str, label: str) -> dict:
    return node("link", label, id=ref)


def doc(*children: dict, title: str = "Page") -> dict:
    return node("document", title, *children)


# ---------------------------------------------------------------------------
# The fake web and the fake browser engine.


@dataclass
class Page:
    text: str = ""
    title: str = ""
    tree: dict | None = None
    redirect_to: str | None = None
    subrequests: tuple[str, ...] = ()
    cookies_set: dict[str, str] = field(default_factory=dict)
    local_storage_set: dict[str, str] = field(default_factory=dict)
    links: dict[str, str] = field(default_factory=dict)  # element ref -> URL a click navigates to
    screenshot_meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Request:
    url: str
    cookies: dict[str, str]
    context_index: int


class FakeWeb:
    """URL -> Page. Unknown URLs are a blank page. `requests` records every request that was
    actually sent, in order, with the cookies the context held at that moment."""

    def __init__(self) -> None:
        self.pages: dict[str, Page] = {}
        self.requests: list[Request] = []

    def add(self, url: str, **page: Any) -> Page:
        self.pages[url] = Page(**page)
        return self.pages[url]

    def get(self, url: str) -> Page:
        return self.pages.get(url, Page())


class FakeDriver:
    """The per-run browser context `tilo_browser.worker.BrowserWorker` drives. Honours the
    request gate for EVERY request (navigation, each redirect hop, each subresource, a click's
    navigation): a request proceeds only if `gate(url)` is true."""

    MAX_HOPS = 10

    def __init__(self, web: FakeWeb, gate: Any, index: int) -> None:
        self.web = web
        self.gate = gate
        self.index = index
        self.cookies: dict[str, str] = {}
        self.local_storage: dict[str, str] = {}
        self.sent: list[str] = []
        self.blocked_subrequests: list[str] = []
        self.typed: list[tuple[str, str]] = []
        self.clicked: list[str] = []
        self.uploaded: list[tuple[str, str]] = []
        self.screenshot_mask_refs: list[list[str]] = []
        self.close_calls = 0
        self.closed = False
        self.current_url: str | None = None
        self.page = Page()

    # -- internals
    def _alive(self) -> None:
        if self.closed:
            raise RuntimeError("driver used after close")

    def _fetch(self, url: str) -> Page:
        self.sent.append(url)
        self.web.requests.append(Request(url, dict(self.cookies), self.index))
        page = self.web.get(url)
        self.cookies.update(page.cookies_set)
        self.local_storage.update(page.local_storage_set)
        return page

    def _load(self, url: str) -> dict[str, Any]:
        chain: list[str] = []
        target = url
        previous: str | None = None
        for _ in range(self.MAX_HOPS):
            allowed = self.gate(target) if previous is None else self.gate(target, redirect_from=previous)
            if not allowed:
                return {"chain": [*chain, target], "aborted": target, "final_url": self.current_url}
            chain.append(target)
            page = self._fetch(target)
            if page.redirect_to is not None:
                previous, target = target, page.redirect_to
                continue
            break
        self.current_url = target
        self.page = page
        for sub in page.subrequests:
            if self.gate(sub):
                self._fetch(sub)
            else:
                self.blocked_subrequests.append(sub)
        return {"chain": chain, "aborted": None, "final_url": target}

    def _find_node(self, ref: str, tree: dict | None = None) -> dict | None:
        tree = tree if tree is not None else self.page.tree
        if tree is None:
            return None
        if tree.get("attrs", {}).get("id") == ref:
            return tree
        for child in tree.get("children", []):
            found = self._find_node(ref, child)
            if found is not None:
                return found
        return None

    # -- the driver protocol (API.md)
    def goto(self, url: str) -> dict[str, Any]:
        self._alive()
        return self._load(url)

    def click(self, ref: str) -> dict[str, Any]:
        self._alive()
        self.clicked.append(ref)
        target = self.page.links.get(ref)
        if target is None:
            return {"chain": [], "aborted": None, "final_url": self.current_url}
        return self._load(target)

    def type(self, ref: str, text: str) -> None:
        self._alive()
        self.typed.append((ref, text))

    def find(self, selector: str) -> str:
        self._alive()
        assert selector.startswith("#"), "the fake driver understands '#id' selectors only"
        ref = selector[1:]
        if self._find_node(ref) is None:
            raise LookupError(selector)
        return ref

    def read_accessibility_tree(self) -> dict:
        self._alive()
        tree = self.page.tree if self.page.tree is not None else doc(title=self.page.title)
        return json.loads(json.dumps(tree))  # a copy: the worker may not mutate the fake's page

    def page_text(self) -> str:
        self._alive()
        return self.page.text

    def page_title(self) -> str:
        self._alive()
        return self.page.title

    def screenshot(self, mask_refs: list[str]) -> bytes:
        self._alive()
        self.screenshot_mask_refs.append(list(mask_refs))
        return PNG

    def screenshot_meta(self) -> dict[str, Any]:
        self._alive()
        return json.loads(json.dumps(self.page.screenshot_meta))

    def upload(self, ref: str, path: str) -> dict[str, Any]:
        self._alive()
        self.uploaded.append((ref, path))
        return {"uploaded": path}

    def download(self, ref: str) -> bytes:
        self._alive()
        return b"downloaded-bytes"

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True
        self.cookies.clear()  # a closed context takes its storage with it
        self.local_storage.clear()


class FakeEngine:
    """`new_context(gate)` is the ONLY way to get a driver; each call is a fresh, isolated
    context (own cookie jar and storage). `contexts` lets tests see which contexts exist."""

    def __init__(self, web: FakeWeb) -> None:
        self.web = web
        self.contexts: list[FakeDriver] = []

    def new_context(self, gate: Any) -> FakeDriver:
        driver = FakeDriver(self.web, gate, len(self.contexts))
        self.contexts.append(driver)
        return driver


def login_page(web: FakeWeb, url: str, *children: dict, text: str = "", title: str = "Sign in") -> Page:
    return web.add(url, text=text, title=title, tree=doc(*children, title=title))


# ---------------------------------------------------------------------------
# contracts/card.schema.json validation (the login card must be a real card).


def _registry() -> Registry:
    resources = []
    for path in sorted((REPO_ROOT / "contracts").glob("**/*.schema.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        resources.append(
            (
                data.get("$id") or path.resolve().as_uri(),
                Resource.from_contents(data, default_specification=DRAFT202012),
            )
        )
    return Registry().with_resources(resources)


def card_schema_errors(card: dict) -> list[str]:
    schema = json.loads((REPO_ROOT / "contracts" / "card.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema, registry=_registry())
    return [e.message for e in validator.iter_errors(card)]
