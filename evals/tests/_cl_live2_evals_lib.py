"""Helpers for the CL-LIVE-2 tests of `--allow-writes` / `--allow-send` in `just live-e2e` / `just live-run`. API pinned
in services/connectors/tests/API_CL_LIVE_2.md. Fake Google only (a stateful Drive that keeps what is uploaded), the
REAL `real_adapters` over it, a scripted terminal (the `read` and `tty` seams of `live_topic.main`); no network.
"""

from __future__ import annotations

import secrets
from typing import Any

from _cl_live_evals_lib import SCOPES, USER, ConnectorFactory, PlantedTransport, Resp, real
from tilo_connectors.real_writes import SEND_SCOPE

DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
YES_ANSWERS = ("", "y", "ok", "yes")  # recommended approach, approve it, reason; then the typed yes at the write gate


class WriteTransport(PlantedTransport):
    """Planted reads as before, plus the Drive requests of one save (and the Gmail lookups of a draft or send)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.folder: str | None = None

    def uploads(self) -> list[tuple[str, str, dict[str, str]]]:
        return [r for r in self.requests if r[0] == "POST" and r[1] == DRIVE_UPLOAD]

    def request(self, method: str, url: str, *, params: Any = None, headers: Any = None, json: Any = None,
                content: bytes | None = None) -> Resp:  # fmt: skip
        q = str(dict(params or {}).get("q", ""))
        if url == DRIVE_UPLOAD:
            super().request(method, url, params=params, headers=headers, json=json, content=content)
            return Resp(200, {"id": "file_" + secrets.token_hex(3), "shared": False})
        if url.endswith("/drive/v3/files") and method.upper() == "POST":  # the Tilo folder is made
            super().request(method, url, params=params, headers=headers, json=json, content=content)
            self.folder = "folder_1"
            return Resp(200, {"id": self.folder})
        if url.endswith("/drive/v3/files") and method.upper() == "GET" and "mimeType" in q:
            super().request(method, url, params=params, headers=headers, json=json, content=content)
            return Resp(200, {"files": [{"id": self.folder}] if self.folder else []})
        if url.endswith("/drive/v3/files") and method.upper() == "GET" and "tilo_save" in q:
            super().request(method, url, params=params, headers=headers, json=json, content=content)
            return Resp(200, {"files": []})
        if url.endswith("/files/folder_1"):
            super().request(method, url, params=params, headers=headers, json=json, content=content)
            return Resp(200, {"id": "folder_1", "shared": False})
        return super().request(method, url, params=params, headers=headers, json=json, content=content)


class WriteFactory(ConnectorFactory):
    """`real_connectors_factory` for write mode: the real factory with `allow_writes` (and `allow_send`)."""

    def __init__(self, *, allow_send: bool = False, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.flags = {"allow_writes": True, "allow_send": allow_send}
        self.transport = WriteTransport(set(self.access.values()), self.markers)
        if allow_send:  # the grant that includes the send scope, as a consent for it would leave
            self.broker.store_tokens(USER, "gmail", {"access_token": self.access["gmail"],
                                     "refresh_token": self.refresh["gmail"], "expires_in": 3599,
                                     "scope": " ".join([*SCOPES["gmail"], SEND_SCOPE])})  # fmt: skip

    def __call__(self) -> dict[str, Any]:
        from _cl_live_evals_lib import SpyAdapter  # noqa: PLC0415
        from tilo_connectors.adapters import InMemoryPicks  # noqa: PLC0415

        self.calls += 1
        self.model_calls_at_call.append(len(self.world.calls) if self.world is not None else 0)
        built = real().real_adapters(self.broker, self.registry, self.transport, user_id=USER, environ=self.environ,
                                     picks=InMemoryPicks(), emit=self.events.append, **self.flags)  # fmt: skip
        self.adapters = {k: SpyAdapter(v) for k, v in built.items()}
        return self.adapters
