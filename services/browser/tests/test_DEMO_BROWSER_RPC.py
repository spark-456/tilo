"""DEMO-BROWSER-RPC: fake-engine acceptance tests for the internal browser session."""

import asyncio

import httpx
from _browser_lib import FakeEngine, FakeWeb, doc, node, textbox

SESSION = "bs_01JB7A0000000000000000BRW1"
URL = "https://example.org/search"
BOX = {"x": 20, "y": 40, "width": 160, "height": 30}


def _app():
    from tilo_browser.app import create_app

    web = FakeWeb()
    web.add(
        URL,
        title="Search",
        text="Three public results",
        tree=doc(
            textbox("query", "Search", box=BOX),
            node("button", "Search", id="go", box={"x": 190, "y": 40, "width": 80, "height": 30}),
            node(
                "button",
                "Search",
                id="submit",
                box={"x": 300, "y": 40, "width": 80, "height": 30},
                form_method="get",
                type="submit",
            ),
            textbox("cc", "Card", autocomplete="cc-number"),
        ),
    )
    engine = FakeEngine(web)
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
    return app, engine


def _post(app, path, payload, auth=True):
    async def run():
        headers = {"Authorization": "Bearer fake"} if auth else {}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://browser.test") as client:
            return await client.post(path, json=payload, headers=headers)

    return asyncio.run(run())


def _start(app):
    return _post(
        app,
        "/sessions",
        {
            "session": SESSION,
            "world_id": "w_demo",
            "run_id": "r_demo",
            "unit_id": "U1",
            "allow_hosts": ["example.org"],
            "start_url": URL,
            "viewport": {"width": 1200, "height": 800},
        },
    )


def _act(app, action, *, at=None):
    digest = None
    if at is not None:
        inspected = _post(app, f"/sessions/{SESSION}/inspect", {"session": SESSION, "at": at})
        assert inspected.status_code == 200, inspected.text
        digest = inspected.json()["digest"]
    return _post(
        app,
        f"/sessions/{SESSION}/act",
        {"session": SESSION, "step": 1, "action": action, "digest": digest, "outbox_id": None},
    )


def test_DEMO_BROWSER_RPC_requires_internal_auth_before_start():
    app, engine = _app()
    assert _post(app, "/sessions", {"start_url": URL}, auth=False).status_code == 401
    assert engine.contexts == []


def test_DEMO_BROWSER_RPC_returns_target_box_and_masked_frame_for_each_action():
    app, engine = _app()
    started = _start(app)
    assert started.status_code == 200, started.text
    assert started.json()["target_box"] == {"x": 0, "y": 0, "width": 1200, "height": 800}
    assert started.json()["screenshot_artifact"]["mime_type"] == "image/png"
    at = {"x": 210, "y": 60}
    acted = _act(app, {"kind": "click", "at": at}, at=at)
    assert acted.status_code == 200, acted.text
    assert acted.json()["target_box"] == {"x": 190, "y": 40, "width": 80, "height": 30}
    assert acted.json()["screenshot_artifact"]["sha256"]
    assert engine.contexts[0].screenshot_mask_refs[-1] == ["cc"]
    assert engine.contexts[0].clicked == ["go"]


def test_DEMO_BROWSER_RPC_inspect_button_without_input_type_uses_null():
    from tilo_browser.session import BrowserSessions

    app, _ = _app()
    assert _start(app).status_code == 200
    inspected = _post(
        app, f"/sessions/{SESSION}/inspect", {"session": SESSION, "at": {"x": 210, "y": 60}}
    )
    assert inspected.status_code == 200
    assert inspected.json()["facts"]["input_type"] is None
    assert BrowserSessions._facts(node("button", "Search", id="go", type=""))["input_type"] is None


def test_DEMO_BROWSER_RPC_stops_commit_and_password_entry():
    app, engine = _app()
    assert _start(app).status_code == 200
    at = {"x": 25, "y": 60}
    submit = _act(app, {"kind": "type", "at": at, "text": "cats", "submit": True}, at=at)
    assert submit.status_code == 409
    assert submit.json()["reason"] == "needs_person"
    assert engine.contexts[0].typed == []
    secret = _act(app, {"kind": "type", "at": {"x": 0, "y": 0}, "text": "abc", "submit": False})
    assert secret.status_code == 409
    assert engine.contexts[0].typed == []
    at = {"x": 280, "y": 60}
    form = _act(app, {"kind": "click", "at": at}, at=at)
    assert form.status_code == 409
    assert form.json()["reason"] == "needs_person"
    assert engine.contexts[0].clicked == []


def test_DEMO_BROWSER_RPC_extract_scroll_and_end_use_the_same_isolated_context():
    app, engine = _app()
    assert _start(app).status_code == 200
    extracted = _act(app, {"kind": "extract"})
    assert extracted.status_code == 200, extracted.text
    assert extracted.json()["text"] == "Three public results"
    scrolled = _post(
        app,
        f"/sessions/{SESSION}/act",
        {
            "session": SESSION,
            "step": 2,
            "action": {"kind": "scroll", "direction": "down"},
            "digest": None,
            "outbox_id": None,
        },
    )
    assert scrolled.status_code == 200, scrolled.text
    assert scrolled.json()["target_box"]["width"] == 1200

    async def end():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://browser.test") as client:
            return await client.delete(f"/sessions/{SESSION}", headers={"Authorization": "Bearer fake"})

    ended = asyncio.run(end())
    assert ended.status_code == 200
    assert ended.json()["target_box"]["width"] == 1200
    assert ended.json()["screenshot_artifact"]["mime_type"] == "image/png"
    assert engine.contexts[0].closed


def test_DEMO_BROWSER_RPC_blocks_offsite_navigation_before_any_request():
    app, engine = _app()
    assert _start(app).status_code == 200
    refused = _act(app, {"kind": "navigate", "url": "https://outside.example.net/private"})
    assert refused.status_code == 403
    assert all("outside.example.net" not in request.url for request in engine.web.requests)
