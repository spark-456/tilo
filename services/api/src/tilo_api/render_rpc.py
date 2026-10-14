"""M1-RENDER-1: bounded, authenticated calls to the internal render door.

The caller supplies a validated spec. No redirects, retries, or provider calls are
made here; failures never include server bytes, credentials, or spec text.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlsplit

from tilo_render.spec import RequestDeliverableSpec

from tilo_api.meeting_host_rpc import metadata_id_token

MAX_OUTPUT_BYTES = 20 * 1024 * 1024
MAX_REQUEST_BYTES = 1024 * 1024
MIME = {
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
MAGIC = {"pdf": b"%PDF-", "pptx": b"PK\x03\x04"}


class RenderRpcError(Exception):
    def __init__(self) -> None:
        super().__init__("The report could not be rendered.")


@dataclass(frozen=True)
class RenderReply:
    status: int
    media_type: str
    content: bytes


class Transport(Protocol):
    def post(self, url: str, body: bytes, headers: Mapping[str, str], timeout_s: float) -> RenderReply: ...


class RequestsTransport:
    def post(self, url: str, body: bytes, headers: Mapping[str, str], timeout_s: float) -> RenderReply:
        import requests  # noqa: PLC0415

        with requests.post(
            url, data=body, headers=dict(headers), timeout=(5.0, timeout_s), stream=True, allow_redirects=False,
        ) as response:  # fmt: skip
            if response.status_code != 200:
                raise RenderRpcError
            content = response.raw.read(MAX_OUTPUT_BYTES + 1, decode_content=True)
            if len(content) > MAX_OUTPUT_BYTES:
                raise RenderRpcError
            return RenderReply(response.status_code, response.headers.get("content-type", ""), content)


class RenderRpc:
    def __init__(
        self,
        base_url: str,
        *,
        transport: Transport | None = None,
        token_for: Callable[[str], str] = metadata_id_token,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise RenderRpcError
        self._base = base_url.rstrip("/")
        self._transport = transport if transport is not None else RequestsTransport()
        self._token_for = token_for

    def render(self, spec: RequestDeliverableSpec, fmt: Literal["pdf", "pptx"]) -> bytes:
        try:
            # Revalidate even an object constructed without Pydantic validation, before credentials or I/O.
            checked = RequestDeliverableSpec.model_validate(spec.model_dump())
            if fmt not in MIME:
                raise RenderRpcError
            body = ('{"format":"' + fmt + '","spec":' + checked.model_dump_json() + "}").encode("utf-8")
            if len(body) > MAX_REQUEST_BYTES:
                raise RenderRpcError
            token = self._token_for(self._base)
            if not token or any(c.isspace() for c in token):
                raise RenderRpcError
            reply = self._transport.post(
                self._base + "/render",
                body,
                {"Authorization": "Bearer " + token, "Content-Type": "application/json"},
                30.0,
            )
            if (
                reply.status != 200
                or reply.media_type.split(";", 1)[0].strip().lower() != MIME[fmt]
                or not isinstance(reply.content, bytes)
                or not reply.content.startswith(MAGIC[fmt])
                or not len(MAGIC[fmt]) < len(reply.content) <= MAX_OUTPUT_BYTES
            ):
                raise RenderRpcError
            return reply.content
        except Exception:
            raise RenderRpcError from None
