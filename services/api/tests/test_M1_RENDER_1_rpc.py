"""M1-RENDER-1: authenticated render RPC against an offline fake server."""

import json

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from tilo_api.render_rpc import RenderReply, RenderRpc, RenderRpcError
from tilo_render.spec import RequestDeliverableSpec

SPEC = RequestDeliverableSpec.model_validate(
    {
        "title": "Report",
        "date": "2026-10-14",
        "sections": [{"heading": "Summary", "blocks": [{"type": "paragraph", "text": "Verified sources."}]}],
    }
)
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


class FakeServer:
    def __init__(self):
        self.seen = []
        self.reply = RenderReply(200, PPTX, b"PK\x03\x04offline")
        app = FastAPI()

        @app.post("/render")
        async def render(request: Request):
            self.seen.append((dict(request.headers), await request.json()))
            return Response(self.reply.content, status_code=self.reply.status, media_type=self.reply.media_type)

        self.server = TestClient(app)

    def post(self, url, body, headers, timeout_s):
        assert url == "https://render.example/render"
        assert 0 < timeout_s <= 30
        response = self.server.post("/render", content=body, headers=headers, follow_redirects=False)
        return RenderReply(response.status_code, response.headers.get("content-type", ""), response.content)


def client(server, audiences):
    def token(audience):
        audiences.append(audience)
        return "fake-id-token"

    return RenderRpc("https://render.example/", transport=server, token_for=token)


def test_M1_RENDER_1_pptx_uses_oidc_and_sends_only_validated_spec():
    server, audiences = FakeServer(), []
    assert client(server, audiences).render(SPEC, "pptx") == b"PK\x03\x04offline"
    assert audiences == ["https://render.example"]
    headers, payload = server.seen[0]
    assert headers["authorization"] == "Bearer fake-id-token"
    assert headers["content-type"] == "application/json"
    assert payload == {"format": "pptx", "spec": json.loads(SPEC.model_dump_json())}


@pytest.mark.parametrize(
    "reply",
    [
        RenderReply(302, PPTX, b"PK\x03\x04offline"),
        RenderReply(403, PPTX, b"internal token or private text"),
        RenderReply(200, "text/html", b"PK\x03\x04offline"),
        RenderReply(200, PPTX, b"wrong bytes"),
    ],
)
def test_M1_RENDER_1_refusals_never_echo_server_content(reply):
    server = FakeServer()
    server.reply = reply
    with pytest.raises(RenderRpcError, match=r"^The report could not be rendered\.$"):
        client(server, []).render(SPEC, "pptx")


def test_M1_RENDER_1_pdf_content_type_and_magic_are_checked():
    server = FakeServer()
    server.reply = RenderReply(200, "application/pdf", b"%PDF-offline")
    assert client(server, []).render(SPEC, "pdf") == b"%PDF-offline"


def test_FR_MTG_03_docx_rpc_uses_its_mime_and_authenticated_payload():
    server, audiences = FakeServer(), []
    server.reply = RenderReply(
        200, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"PK\x03\x04offline"
    )
    assert client(server, audiences).render(SPEC, "docx") == server.reply.content
    assert audiences == ["https://render.example"]
    assert server.seen[0][1]["format"] == "docx"


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://render.example",
        "https://u:p@render.example",
        "https://render.example?q=x",
        "https://render.example/#token",
        "https://render.example/path",
    ],
)
def test_M1_RENDER_1_bad_configuration_never_fetches_credentials(url):
    with pytest.raises(RenderRpcError):
        RenderRpc(url, transport=FakeServer(), token_for=lambda _: pytest.fail("credential fetch"))


def test_M1_RENDER_1_oversized_output_is_refused(monkeypatch):
    from tilo_api import render_rpc

    monkeypatch.setattr(render_rpc, "MAX_OUTPUT_BYTES", 4)
    with pytest.raises(RenderRpcError):
        client(FakeServer(), []).render(SPEC, "pptx")


def test_M1_RENDER_1_token_failure_is_sanitized_and_does_not_call_server():
    server = FakeServer()

    def fail(_):
        raise RuntimeError("secret credentials")

    rpc = RenderRpc("https://render.example", transport=server, token_for=fail)
    with pytest.raises(RenderRpcError, match=r"^The report could not be rendered\.$"):
        rpc.render(SPEC, "pptx")
    assert server.seen == []
