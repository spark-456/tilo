"""WEB-2 / WS-10, WS-11, WS-13, WS-14, AR-10 (contracts/website.rules.md): tilo-api serves the fixed preview shell at
`GET /preview/website` (no data, no token, no sign-in: the same bytes for every caller) with the exact WS-10 headers,
and the owner-scoped result route serves a website version as an attachment under the same CSP. No model, no network."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tilo_api import deps
from tilo_api import preview as preview_module
from tilo_api.preview import router as preview_router
from tilo_api.results import result_store, router
from tilo_memory.artifacts import ArtifactStore, MemoryBlobBackend, MemoryMetaBackend, NewVersion, Origin, Scope
from tilo_providers.safety import FakeSafetyProvider

ORIGINS = "https://app.example,https://alt.example:8443"
CSP = (
    "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src data:; font-src data:; media-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'; "
    "frame-src 'none'; worker-src 'none'; object-src 'none'; manifest-src 'none'; "
    "frame-ancestors https://app.example https://alt.example:8443"
)
OWNER, OTHER, WORLD, RUN = "u_owner", "u_other", "w_site", "r_site"
PAGE = b"<!doctype html><html><body><h1>Clocks</h1><script>setInterval(function(){}, 1000)</script></body></html>"


@pytest.fixture(autouse=True)
def web_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("K_SERVICE", "CLOUD_RUN_JOB", "TILO_API_DEV"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TILO_API_CORS_ORIGINS", ORIGINS)


def shell() -> object:
    app = FastAPI()
    app.include_router(preview_router)
    with TestClient(app) as client:
        return client.get("/preview/website")


def test_WEB_2_WS_10_the_shell_headers_are_exact() -> None:
    response = shell()
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/html")
    assert response.headers["content-security-policy"] == CSP
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert "x-frame-options" not in response.headers and "set-cookie" not in response.headers
    policy = response.headers["permissions-policy"]
    assert all(f"{feature}=()" in policy for feature in ("camera", "microphone", "geolocation", "payment", "usb"))
    assert "=(self)" not in policy and "*" not in policy


def test_WEB_2_WS_10_the_shell_is_the_same_bytes_for_every_caller() -> None:
    first, second = shell(), shell()
    assert first.content == second.content
    app = FastAPI()
    app.include_router(preview_router)
    with TestClient(app) as client:
        signed = client.get("/preview/website", headers={"Authorization": "Bearer x", "X-Tilo-Channel": "web"})
        queried = client.get("/preview/website?world=w_x&token=abc")
    assert signed.content == queried.content == first.content


def test_WEB_2_WS_11_the_shell_script_does_the_handshake_once() -> None:
    body = shell().text
    assert body.count("<script>") == 1
    assert '"tilo":"preview-ready"' in body.replace(" ", "") or "tilo: 'preview-ready'" in body
    for needle in ("524288", "document.open()", "document.write(", "document.close()", "removeEventListener", '"*"'):
        assert needle in body
    assert '"https://app.example"' in body and '"https://alt.example:8443"' in body  # the same list as the CSP
    for banned in ("fetch", "XMLHttpRequest", "localStorage", "eval(", "src=", "href="):
        assert banned not in body


def test_WEB_2_WS_10_deployed_the_ancestors_are_the_two_hosting_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    policy = shell().headers["content-security-policy"]
    assert policy.endswith(
        "frame-ancestors https://essential-wares-510320-f0.web.app https://essential-wares-510320-f0.firebaseapp.com"
    )


def test_WEB_2_WS_10_with_no_web_origin_nothing_may_frame_the_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TILO_API_CORS_ORIGINS")
    response = shell()
    assert response.headers["content-security-policy"].endswith("frame-ancestors 'none'")
    assert "[]" in response.text


def test_WEB_2_WS_10_the_route_is_public_and_the_only_one_without_frame_protection() -> None:
    from tilo_api import access, appcheck

    assert ("GET", "/preview/website") in access.PUBLIC_ROUTES and ("GET", "/preview/website") in appcheck.EXEMPT_ROUTES
    assert preview_module.PATH == "/preview/website"


def test_WEB_2_WS_10_deployed_with_app_check_enforced_the_real_app_still_serves_the_shell_to_a_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tilo_api import app

    monkeypatch.setenv("K_SERVICE", "tilo-api")
    monkeypatch.setenv("TILO_APPCHECK_ENFORCE", "1")
    with TestClient(app) as client:
        shell_response = client.get("/preview/website")
        other = client.get("/worlds")
    assert shell_response.status_code == 200 and "x-frame-options" not in shell_response.headers
    assert shell_response.headers["content-security-policy"].startswith("sandbox allow-scripts; default-src 'none'")
    assert other.status_code in {401, 403}  # everything else still needs the gates


# --- the result route: a website version is an attachment under the same CSP (WS-13) -----------------------------


def make_case(title_of: str = "Time zones"):
    artifacts = ArtifactStore(
        MemoryMetaBackend(),
        MemoryBlobBackend(),
        clock=lambda: datetime(2026, 10, 16, tzinfo=UTC),
        redactor=lambda text: text,
        archive_lookup=lambda *_: None,
        alert_sink=lambda _: None,
        screener=FakeSafetyProvider(),
    )
    scope = Scope(deps.ORG_ID, WORLD, OWNER)
    keys = iter(range(10))

    def put(content: bytes, media: str):
        return artifacts.put(
            scope,
            NewVersion(media, content, RUN, Origin("unit", "U1", "A_s1"), idempotency_key=f"{RUN}:U1:{next(keys)}:0"),
        )

    site, notes = put(PAGE, "text/html"), put(b"# notes", "text/markdown")
    state = deps.Store(worlds={WORLD: deps.WorldRecord(OWNER, {}, run_id=RUN)})

    def created(v):
        keep = {k: v.record[k] for k in ("media_type", "content_sha256")}
        return {"type": "artifact.created", "actor": "A_s1", "data": {"artifact": v.ref, **keep}}

    def delivered(v, fmt):
        return {"type": "artifact.delivered", "actor": "A_s2", "data": {"artifact": v.ref, "format": fmt}}

    state.events[WORLD] = [
        created(site), created(notes), delivered(site, "website"), delivered(notes, "in_app"),
        {"type": "world.completed", "data": {"credits_used": 0}},
    ]  # fmt: skip
    state.runs[WORLD] = type(
        "R", (), {"titles": {site.ref["artifact_id"]: title_of, notes.ref["artifact_id"]: "Notes"}}
    )()
    app = FastAPI()
    app.include_router(router)
    app.include_router(preview_router)
    app.dependency_overrides.update(
        {
            deps.get_store: lambda: state,
            deps.get_artifact_store: lambda: artifacts,
            result_store: lambda: lambda: artifacts,
            deps.get_current_principal: lambda: deps.Principal(OWNER, "owner", WORLD),
        }
    )
    return app, site, notes


def test_WEB_2_WS_13_the_owner_gets_the_page_as_an_attachment_with_the_same_csp() -> None:
    app, site, _ = make_case()
    with TestClient(app) as client:
        response = client.get(f"/worlds/{WORLD}/result", params={"artifact": site.ref["artifact_id"], "version": 1})
    assert response.status_code == 200 and response.content == PAGE
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="Time zones.html"'
    assert response.headers["x-content-type-options"] == "nosniff" and response.headers["cache-control"] == "no-store"
    assert response.headers["content-security-policy"] == CSP
    assert hashlib.sha256(response.content).hexdigest() == site.record["content_sha256"]


@pytest.mark.parametrize("title", ['a"b\r\nSet-Cookie: x=1', "../../etc/passwd", "   ", "名前", "x" * 300])
def test_WEB_2_WS_13_the_filename_is_a_safe_title(title: str) -> None:
    app, site, _ = make_case(title)
    with TestClient(app) as client:
        response = client.get(f"/worlds/{WORLD}/result", params={"artifact": site.ref["artifact_id"]})
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="') and disposition.endswith('.html"')
    name = disposition[len('attachment; filename="') : -1]
    assert len(name) <= 85 and all(c.isalnum() or c in " ._-" for c in name) and ".." not in name and "/" not in name
    assert "set-cookie" not in response.headers


def test_WEB_2_AR_10_other_types_keep_their_old_headers_and_have_no_csp() -> None:
    app, _, notes = make_case()
    with TestClient(app) as client:
        response = client.get(f"/worlds/{WORLD}/result", params={"artifact": notes.ref["artifact_id"]})
    assert response.headers["content-disposition"] == 'attachment; filename="tilo-result"'
    assert "content-security-policy" not in response.headers


def test_WEB_2_WS_14_a_named_version_that_was_not_delivered_is_absent() -> None:
    app, site, _ = make_case()
    with TestClient(app) as client:
        response = client.get(f"/worlds/{WORLD}/result", params={"artifact": site.ref["artifact_id"], "version": 2})
    assert response.status_code == 404


@pytest.mark.parametrize("flaw", ["other_user", "viewer", "email", "other_world"])
def test_WEB_2_WS_15_another_person_gets_404_on_the_bytes_and_storage_stays_closed(flaw: str) -> None:
    app, site, _ = make_case()

    def storage_must_not_open():
        raise AssertionError("an unauthorised request must not open storage")

    app.dependency_overrides[result_store] = lambda: storage_must_not_open
    principal = deps.Principal(
        OTHER if flaw == "other_user" else OWNER,
        "viewer" if flaw == "viewer" else "owner",
        "w_else" if flaw == "other_world" else WORLD,
        channel="email" if flaw == "email" else "web",
    )
    app.dependency_overrides[deps.get_current_principal] = lambda: principal
    with TestClient(app) as client:
        response = client.get(f"/worlds/{WORLD}/result", params={"artifact": site.ref["artifact_id"], "version": 1})
    assert response.status_code == 404 and PAGE not in response.content


def test_WEB_2_WS_11_the_delivered_list_names_the_media_type_and_the_hash_for_the_check() -> None:
    from tilo_api.runs import router as runs_router

    app, site, notes = make_case()
    app.include_router(runs_router)
    app.dependency_overrides[deps.get_people_provider] = lambda: lambda: None
    app.dependency_overrides[deps.get_clock] = lambda: lambda: "2026-10-16T00:00:00.000Z"
    with TestClient(app) as client:
        body = client.get(f"/worlds/{WORLD}/delivery").json()
    by_id = {a["id"]: a for a in body["artifacts"]}
    assert by_id[site.ref["artifact_id"]] == {
        "id": site.ref["artifact_id"], "title": "Time zones", "kind": "website", "version": 1,
        "media_type": "text/html", "content_sha256": site.record["content_sha256"],
    }  # fmt: skip
    assert by_id[notes.ref["artifact_id"]]["media_type"] == "text/markdown"
