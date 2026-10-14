"""Unsigned deployment checks use only fake HTTP and never send credentials."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/smoke_unsigned.py"
API = "https://tilo-api-123.asia-southeast1.run.app"
WEB = "https://essential-wares-510320-f0.web.app"


def load():
    spec = importlib.util.spec_from_file_location("smoke_unsigned", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("payload", ["invalid", "[]", '{"status":{"traffic":[null]}}'])
def test_FR_MTG_08_release_bad_snapshot_fails_closed(tmp_path, payload):
    path = tmp_path / "traffic.json"
    path.write_text(payload)
    assert load().release_target(API, "tilo-api-new", str(path)) == (False, "")


@pytest.mark.parametrize("broken", [None, "traffic", "revision", "new-health", "bundle-changed", "foreign"])
def test_FR_MTG_08_release_checks(tmp_path, capsys, broken):
    revision = "tilo-api-00042-new"
    tagged = "https://release---tilo-api-abc-as.a.run.app"
    snapshot = {
        "status": {
            "url": API,
            "latestReadyRevisionName": revision,
            "traffic": [
                {"revisionName": revision, "percent": 99 if broken == "traffic" else 100},
                {"revisionName": revision, "tag": "release", "url": tagged},
            ],
        }
    }
    if broken == "revision":
        snapshot["status"]["latestReadyRevisionName"] = "tilo-api-old"
    if broken == "foreign":
        snapshot["status"]["traffic"][1]["url"] = "https://foreign.example"
    path = tmp_path / "traffic.json"
    path.write_text(json.dumps(snapshot))
    module = load()
    source = f'Continue with Google "{API}"'
    previous = module.bundle_hash([(WEB + "/assets/main.js", source)]) if broken == "bundle-changed" else "0" * 64

    def server(request):
        assert request.method in ("GET", "OPTIONS")
        assert "authorization" not in request.headers and "cookie" not in request.headers
        assert request.url.host != "foreign.example"
        if str(request.url) == tagged + "/health":
            return httpx.Response(500 if broken == "new-health" else 200)
        if request.url.path == "/":
            return httpx.Response(200, text='<script src="/assets/main.js"></script>')
        if request.url.path == "/assets/main.js":
            return httpx.Response(200, text=source)
        if request.url.path == "/intake":
            return httpx.Response(
                200,
                headers={
                    "access-control-allow-origin": WEB,
                    "access-control-allow-methods": "POST",
                    "access-control-allow-headers": "authorization,content-type,x-tilo-channel",
                },
            )
        return httpx.Response(401 if request.url.path == "/v1/plate" else 200)

    assert module.main([API, revision, str(path), previous], transport=httpx.MockTransport(server)) == (
        0 if broken is None else 1
    )
    output = capsys.readouterr().out
    assert (
        "PASS api-revision-100" in output
        if broken not in ("traffic", "revision", "foreign")
        else "FAIL api-revision-100" in output
    )
    assert "FAIL new-health" in output if broken in ("new-health", "foreign") else "PASS new-health" in output
    assert "FAIL bundle-changed" in output if broken == "bundle-changed" else "PASS bundle-changed" in output


@pytest.mark.parametrize("broken", [None, "sign-in", "bundle-api", "health", "cors-intake", "plate-auth"])
def test_FR_MTG_08_unsigned_checks_fail_each_boundary_and_never_send_tokens(broken, capsys, monkeypatch):
    seen = []
    monkeypatch.setenv("TILO_SMOKE_ID_TOKEN", "must-never-send")

    def server(request):
        seen.append(request)
        assert request.method in ("GET", "OPTIONS")
        assert "authorization" not in request.headers and "cookie" not in request.headers
        path = request.url.path
        if path == "/":
            return httpx.Response(200, text='<script type="module" src="/assets/main.js"></script>')
        if path == "/assets/main.js":
            return httpx.Response(
                200,
                text=("" if broken == "sign-in" else "Continue with Google")
                + (' "https://wrong.example"' if broken == "bundle-api" else f' "{API}"'),
            )
        if path in ("/health", "/healthz"):
            return httpx.Response(500 if broken == path[1:] else 200)
        if path == "/intake":
            assert request.method == "OPTIONS" and request.headers["origin"] == WEB
            assert request.headers["access-control-request-method"] == "POST"
            return httpx.Response(
                200,
                headers={
                    "access-control-allow-origin": "*" if broken == "cors-intake" else WEB,
                    "access-control-allow-methods": "POST",
                    "access-control-allow-headers": "authorization,content-type,x-tilo-channel",
                },
            )
        assert path == "/v1/plate"
        return httpx.Response(500 if broken == "plate-auth" else 401)

    result = load().main([API], transport=httpx.MockTransport(server))
    assert result == (0 if broken is None else 1)
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 5
    assert ("FAIL " + broken in output) if broken else output.count("PASS ") == 5
    assert "must-never-send" not in output and len(seen) == 5


@pytest.mark.parametrize("asset", ["https://other.example/private.js", "//other.example/private.js"])
def test_FR_MTG_08_cross_origin_assets_are_not_fetched(asset, capsys):
    seen = []

    def server(request):
        seen.append(request)
        if request.url.host == "essential-wares-510320-f0.web.app":
            assert request.url.path == "/"
            return httpx.Response(200, text=f'<script src="{asset}"></script>')
        return httpx.Response(500)

    assert load().main([API], transport=httpx.MockTransport(server)) == 1
    assert all(str(request.url) != asset for request in seen)


def test_FR_MTG_08_invalid_url_is_refused_before_http(capsys):
    assert load().main(["http://localhost"], transport=httpx.MockTransport(lambda _: pytest.fail("HTTP"))) == 1


@pytest.mark.parametrize("variant", ["nested", "suffix", "redirect", "cap", "asset-cap", "network"])
def test_FR_MTG_08_asset_hardening(variant, capsys, monkeypatch):
    module = load()
    seen = []
    if variant == "cap":
        monkeypatch.setattr(module, "MAX_BYTES", 1)
    if variant == "asset-cap":
        monkeypatch.setattr(module, "MAX_ASSETS", 0)

    def server(request):
        seen.append(str(request.url))
        assert "cookie" not in request.headers
        path = request.url.path
        if path == "/":
            if variant == "network":
                raise httpx.ConnectError("private details must not print")
            return httpx.Response(
                302 if variant == "redirect" else 200,
                headers={"location": "https://other.example", "set-cookie": "secret=value"},
                text='<script src="/assets/main.js"></script>',
            )
        if path == "/assets/main.js":
            text = 'import("./signin.js")' if variant == "nested" else f'Continue with Google "{API}.evil"'
            return httpx.Response(200, text=text, headers={"set-cookie": "secret=value"})
        if path == "/assets/signin.js":
            return httpx.Response(200, text=f'Continue with Google "{API}"')
        if path == "/v1/plate":
            return httpx.Response(401)
        return httpx.Response(
            200,
            headers={
                "access-control-allow-origin": WEB,
                "access-control-allow-methods": "POST",
                "access-control-allow-headers": "authorization,content-type,x-tilo-channel",
            },
        )

    result = module.main([API], transport=httpx.MockTransport(server))
    assert result == (0 if variant == "nested" else 1)
    assert "https://other.example" not in seen
    assert "private details" not in capsys.readouterr().out


@pytest.mark.parametrize("broken", [None, "api", "sign-in", "asset"])
def test_vite_preloads_and_large_chunk_graph_are_verified(broken, capsys):
    seen = []

    def server(request):
        seen.append(request.url.path)
        assert request.method in ("GET", "OPTIONS")
        assert "authorization" not in request.headers and "cookie" not in request.headers
        assert request.url.host in ("essential-wares-510320-f0.web.app", "tilo-api-123.asia-southeast1.run.app")
        path = request.url.path
        if path == "/":
            return httpx.Response(
                200, text='<script src="/assets/main.js"></script><link rel="modulepreload" href="/assets/preload.js">'
            )
        if path == "/assets/main.js":
            return httpx.Response(200, text='["assets/chunk0.js"]')
        if path == "/assets/preload.js":
            return httpx.Response(200, text='"https://tilo-api-wrong-as.a.run.app"' if broken == "api" else f'"{API}"')
        if path.startswith("/assets/chunk"):
            index = int(path.split("chunk")[1].split(".")[0])
            if broken == "asset" and index == 39:
                return httpx.Response(404)
            source = (
                f'import("./chunk{index + 1}.js")'
                if index < 39
                else ('"Continue with Google"' if broken != "sign-in" else '"Sign-in is off"')
            )
            return httpx.Response(200, text=source)
        if path == "/v1/plate":
            return httpx.Response(401)
        return httpx.Response(
            200,
            headers={
                "access-control-allow-origin": WEB,
                "access-control-allow-methods": "POST",
                "access-control-allow-headers": "authorization,content-type,x-tilo-channel",
            },
        )

    assert load().main([API], transport=httpx.MockTransport(server)) == (0 if broken is None else 1)
    output = capsys.readouterr().out
    assert "/assets/preload.js" in seen and "/assets/chunk39.js" in seen
    assert "/assets/assets/chunk0.js" not in seen
    if broken is None:
        assert "PASS sign-in" in output and "PASS bundle-api" in output
