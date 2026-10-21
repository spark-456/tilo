"""DEMO-BROWSER (owner, 21 Oct: "the agentic browser isnt working like an agentic browser, but rather like a screenshot
playlist ... the cursor must do some real work, not just pretend").

The browser acts as a person would: the mouse clicks the element at its middle, clicks into a field and the keyboard
types the words, Enter in a site's search box submits its GET form, the wheel scrolls over the page's content. Each act
answers with the box where the mouse really acted (the cursor the person sees).

BR-05 holds as written: Enter in a text or search field of a GET form is a search, not a commit; a click on a form's
submit control, Enter anywhere else (a post form, a field outside a form) and any page navigation sent with another
method than GET (a posted form) stay a person's (`needs_person`). The page a search opens passes the egress gate.
"""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from _browser_lib import FakeDriver, FakeEngine, FakeWeb, doc, link, node, textbox

SESSION = "bs_01JB7A0000000000000000RACT"
HOME = "https://example.org/"
RESULTS = "https://example.org/search?q=cats"
SEARCH_BOX = {"x": 330, "y": 70, "width": 400, "height": 36}
NAME_BOX = {"x": 330, "y": 300, "width": 300, "height": 30}
LINK_BOX = {"x": 40, "y": 400, "width": 200, "height": 24}
MEASURED = {"x": 41, "y": 401, "width": 198, "height": 22}


class ActingDriver(FakeDriver):
    """The fake browser with Enter: it opens the page the focused form would (`links["enter"]`), and it reports where
    the mouse acted (`last_box`) and a page navigation it would have posted (`posted`), as PlaywrightDriver does."""

    def __init__(self, web, gate, index):
        super().__init__(web, gate, index)
        self.pressed: list[str] = []
        self.last_box: dict | None = None
        self.posted: str | None = None

    def click(self, ref):
        self.last_box = MEASURED
        if ref == "post-link":
            self.clicked.append(ref)
            self.posted = "https://example.org/order"
            return {"chain": [], "aborted": None, "final_url": self.current_url}
        return super().click(ref)

    def type(self, ref, text):
        self.last_box = SEARCH_BOX
        super().type(ref, text)

    def press(self, key):
        self.pressed.append(key)
        target = self.page.links.get("enter")
        return self._load(target) if target else {"chain": [], "aborted": None, "final_url": self.current_url}


class ActingEngine(FakeEngine):
    def new_context(self, gate):
        driver = ActingDriver(self.web, gate, len(self.contexts))
        self.contexts.append(driver)
        return driver


def _app(enter_to=RESULTS):
    from tilo_browser.app import create_app

    web = FakeWeb()
    web.add(
        HOME,
        title="Example",
        text="An example site",
        tree=doc(
            # a role container round everything, as real pages have (role="main", role="search")
            node("main", "Content", id="main", box={"x": 0, "y": 0, "width": 1200, "height": 800}),
            textbox("q", "Search", box=SEARCH_BOX, type="search", form_method="get"),
            node("button", "Search", id="go", box={"x": 740, "y": 70, "width": 80, "height": 36}, form_method="get"),
            textbox("who", "Your name", box=NAME_BOX, form_method="post"),
            textbox("loose", "Filter", box={"x": 330, "y": 200, "width": 300, "height": 30}),
            node("link", "Example result", id="r1", box=LINK_BOX, href="/wiki/Cats"),
            node("link", "Order now please", id="post-link", box={"x": 40, "y": 500, "width": 200, "height": 24}),
        ),
        links={"enter": enter_to, "r1": "https://example.org/wiki/Cats"},
    )
    web.add(RESULTS, title="Results", text="Cats: three results", tree=doc(link("r2", "Cats")))
    web.add("https://example.org/wiki/Cats", title="Cats", text="Cats are small.", tree=doc())
    engine = ActingEngine(web)
    app = create_app(
        browser_engine=engine,
        oidc_verifier=lambda token, audience: {
            "iss": "https://accounts.google.com",
            "email": "caller@example.org",
            "email_verified": True,
            "aud": audience,
        },
        audience="https://browser.example.org",
        allowed_callers=["caller@example.org"],
    )
    return app, engine, web


def _post(app, path, payload):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://browser.test") as client:
            return await client.post(path, json=payload, headers={"Authorization": "Bearer fake"})

    return asyncio.run(run())


def _start(app):
    body = {
        "session": SESSION, "world_id": "w_demo", "run_id": "r_demo", "unit_id": "U1",
        "allow_hosts": ["example.org"], "start_url": HOME, "viewport": {"width": 1200, "height": 800},
    }  # fmt: skip
    started = _post(app, "/sessions", body)
    assert started.status_code == 200, started.text


def _act(app, action, at=None):
    digest = None
    if at is not None:
        inspected = _post(app, f"/sessions/{SESSION}/inspect", {"session": SESSION, "at": at})
        assert inspected.status_code == 200, inspected.text
        digest = inspected.json()["digest"]
    body = {"session": SESSION, "step": 1, "action": action, "digest": digest, "outbox_id": None}
    return _post(app, f"/sessions/{SESSION}/act", body)


def _grid(box):
    """The 0..999 grid point at the middle of a box in the 1200 x 800 window."""
    return {
        "x": round((box["x"] + box["width"] / 2) * 999 / 1200),
        "y": round((box["y"] + box["height"] / 2) * 999 / 800),
    }


def test_DEMO_BROWSER_enter_in_a_get_search_box_searches_the_site():
    app, engine, web = _app()
    _start(app)
    at = _grid(SEARCH_BOX)
    acted = _act(app, {"kind": "type", "at": at, "text": "cats", "submit": True}, at)
    assert acted.status_code == 200, acted.text
    driver = engine.contexts[0]
    assert driver.typed == [("q", "cats")] and driver.pressed == ["Enter"]
    assert web.requests[-1].url == RESULTS, "the search page opened, through the egress gate"
    assert acted.json()["target_box"] == SEARCH_BOX, "the cursor is on the field the keys went into"


@pytest.mark.parametrize(
    "box",
    [NAME_BOX, {"x": 330, "y": 200, "width": 300, "height": 30}],
    ids=["a post form's field", "a field outside any form"],
)
def test_DEMO_BROWSER_enter_anywhere_else_stays_a_persons(box):
    app, engine, _web = _app()
    _start(app)
    at = _grid(box)
    refused = _act(app, {"kind": "type", "at": at, "text": "Ada", "submit": True}, at)
    assert refused.status_code == 409 and refused.json()["reason"] == "needs_person"
    assert engine.contexts[0].typed == [] and engine.contexts[0].pressed == []


def test_DEMO_BROWSER_a_search_that_lands_off_the_allowlist_is_blocked():
    app, engine, web = _app(enter_to="https://elsewhere.example.net/search?q=cats")
    _start(app)
    at = _grid(SEARCH_BOX)
    blocked = _act(app, {"kind": "type", "at": at, "text": "cats", "submit": True}, at)
    assert blocked.status_code == 403 and blocked.json()["reason"] == "offsite_host"
    assert all("elsewhere.example.net" not in request.url for request in web.requests)


def test_DEMO_BROWSER_a_click_into_a_forms_field_only_focuses_it_but_its_button_is_a_persons():
    app, engine, _web = _app()
    _start(app)
    at = _grid(SEARCH_BOX)
    assert _act(app, {"kind": "click", "at": at}, at).status_code == 200
    assert engine.contexts[0].clicked == ["q"]
    app, engine, _web = _app()
    _start(app)
    at = _grid({"x": 740, "y": 70, "width": 80, "height": 36})
    refused = _act(app, {"kind": "click", "at": at}, at)
    assert refused.status_code == 409 and refused.json()["reason"] == "needs_person"
    assert engine.contexts[0].clicked == []


def test_DEMO_BROWSER_a_click_answers_where_the_mouse_clicked():
    app, engine, web = _app()
    _start(app)
    at = _grid(LINK_BOX)
    clicked = _act(app, {"kind": "click", "at": at}, at)
    assert clicked.status_code == 200, clicked.text
    assert clicked.json()["target_box"] == MEASURED, "the element's box as the mouse found it, not the inspect's"
    assert web.requests[-1].url == "https://example.org/wiki/Cats"


def test_DEMO_BROWSER_the_target_is_the_control_under_the_point_and_a_tie_is_refused():
    app, engine, _web = _app()
    _start(app)
    at = _grid(LINK_BOX)
    inspected = _post(app, f"/sessions/{SESSION}/inspect", {"session": SESSION, "at": at}).json()
    assert inspected["facts"]["name"] == "Example result", "the link, not the page-wide container round it"
    page = engine.web.pages[HOME]
    page.tree["children"].append(node("link", "Twin", id="twin", box=LINK_BOX))
    tied = _post(app, f"/sessions/{SESSION}/inspect", {"session": SESSION, "at": at})
    assert tied.status_code == 409 and tied.json()["reason"] == "target_changed"


def test_DEMO_BROWSER_a_page_that_posts_a_form_after_a_click_is_stopped_for_a_person():
    app, engine, _web = _app()
    _start(app)
    at = _grid({"x": 40, "y": 500, "width": 200, "height": 24})
    refused = _act(app, {"kind": "click", "at": at}, at)
    assert refused.status_code == 409 and refused.json()["reason"] == "needs_person"


# --- the real driver (headless Chromium, a local page): the mouse, the keys and the wheel act for real ---


class _Pages(BaseHTTPRequestHandler):
    posted: list[str] = []

    def do_GET(self) -> None:  # noqa: N802 - http.server's name
        filler = "".join(f"<p>Line {n} of the page.</p>" for n in range(120))
        pages = {
            "/": "<main><form action='/results' method='get'><input type='search' name='q' aria-label='Search'>"
            "</form><form method='post' action='/login'><input type='text' name='who' aria-label='Who'></form>"
            f"{filler}</main>",
            "/results": f"<main><h1>Results</h1><a href='/item'>Item one</a>{filler}</main>",
            "/item": f"<main><h1>Item one</h1>{filler}</main>",
        }
        body = pages.get(self.path.split("?")[0], "<p>nothing</p>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_POST(self) -> None:  # noqa: N802 - http.server's name
        _Pages.posted.append(self.path)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture()
def server():
    _Pages.posted = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Pages)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _ref(driver, name):
    nodes = driver.read_accessibility_tree()["children"]
    return next(n for n in nodes if n["name"] == name)["attrs"]


def _near(box, other):
    return all(abs(box[k] - other[k]) <= 1 for k in ("x", "y", "width", "height"))


@pytest.mark.slow
def test_DEMO_BROWSER_the_real_driver_types_presses_enter_clicks_and_scrolls(server):
    from tilo_browser.playwright_engine import PlaywrightDriver

    try:
        driver = PlaywrightDriver(lambda url, **_: True, {"width": 1200, "height": 800})
    except Exception as exc:  # no Chromium in this environment
        pytest.skip(f"headless Chromium is not available: {type(exc).__name__}")
    try:
        driver.goto(f"{server}/")
        field = _ref(driver, "Search")
        driver.type(field["id"], "cats")
        assert _near(driver.last_box, field["box"]), "the cursor is on the search box"
        assert driver.page.locator("input[name=q]").input_value() == "cats"
        driver.press("Enter")
        assert driver.page.url == f"{server}/results?q=cats" and driver.posted is None

        item = _ref(driver, "Item one")
        driver.click(item["id"])
        assert _near(driver.last_box, item["box"]), "the cursor is where the mouse clicked the link"
        assert driver.page.url == f"{server}/item"

        driver.scroll("down")
        assert driver.page.evaluate("window.scrollY") > 0
        main = driver.page.locator("main").bounding_box()
        middle_x = driver.last_box["x"] + driver.last_box["width"] / 2
        assert main["x"] <= middle_x <= main["x"] + main["width"], "the wheel turned over the page's content"

        driver.goto(f"{server}/")
        who = _ref(driver, "Who")
        driver.type(who["id"], "Ada")
        driver.press("Enter")
        assert driver.posted == f"{server}/login" and _Pages.posted == [], "a posted form never leaves the browser"
        assert driver.page.url == f"{server}/"
    finally:
        driver.close()
