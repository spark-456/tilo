"""DriveAdapter: read the files a user picked, write deliverables to a Tilo folder (FR-CON-05, PRD 12.2).

Every call uses drive.file. A file is readable only when the user picked it, `list_folder` listed it from
a picked folder, or this adapter created it; anything else is `NotPicked` before any request names it.
Saving is the one side effect (SEC-03), into the folder named `Tilo` this adapter created, exactly once.
File names are data: returned verbatim, never logged, never a path.
"""

from __future__ import annotations

import json as jsonlib
import re
import secrets
import threading
from collections.abc import Iterable, Mapping
from typing import Any

from ..outbox import Grant
from ._google import GoogleAdapter, checked_id, side_effect_marker
from ._transport import FileTooLarge, NotPicked, SideEffectRefused

DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3/files"
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024  # one Drive download
FOLDER_MIME = "application/vnd.google-apps.folder"
TILO_FOLDER = "Tilo"
_FIELDS = "id,name,mimeType,size,parents"
_FOLDER_MARK = ("tilo_role", "folder")  # appProperties of the folder this adapter created
_SAVE_KEY = "tilo_save"  # appProperties key of a saved file: side_effect_marker(entry)
_MIME = re.compile(r"[A-Za-z0-9][\w.+-]*/[\w.+-]+")


class InMemoryPicks:
    """The files and folders a user picked in the Drive Picker."""

    def __init__(self) -> None:
        self._picked: dict[str, set[str]] = {}
        self._lock = threading.Lock()

    def add(self, user_id: str, ids: Iterable[str]) -> None:
        with self._lock:
            self._picked.setdefault(user_id, set()).update(str(i) for i in ids)

    def picked(self, user_id: str) -> frozenset[str]:
        with self._lock:
            return frozenset(self._picked.get(user_id, ()))


class DriveAdapter(GoogleAdapter):
    def __init__(self, *, picks: InMemoryPicks, max_download_bytes: int = MAX_DOWNLOAD_BYTES, **common: Any) -> None:
        super().__init__(**common)  # declaration, broker, transport, artifacts, owner_of, clock, emit, sleep, ...
        self._picks = picks
        self._max_download_bytes = max_download_bytes
        self._listed: dict[str, set[str]] = {}  # user -> ids listed from a picked folder
        self._created: dict[str, set[str]] = {}  # user -> the Tilo folder and the files saved in it
        self._lock = threading.Lock()

    # -- reads ------------------------------------------------------------------------------------

    def get_metadata(self, user_id: str, file_id: str) -> dict[str, Any]:
        path = f"/files/{self._readable(user_id, file_id)}"
        return _meta(self._get(user_id, self._scopes("read"), path, {"fields": _FIELDS}))

    def list_folder(self, user_id: str, folder_id: str, *, page_token: str | None = None) -> dict[str, Any]:
        if folder_id not in self._picks.picked(user_id) | self._known(self._created, user_id):
            raise NotPicked("the folder was not picked")
        folder = checked_id(folder_id)
        params = {
            "q": f"'{folder}' in parents and trashed = false",
            "pageSize": self._batch(100),
            "fields": f"nextPageToken,files({_FIELDS})",
            "pageToken": page_token,
        }
        body = self._get(user_id, self._scopes("list"), "/files", {k: v for k, v in params.items() if v is not None})
        files = [_meta(f) for f in body.get("files") or []]
        self._remember(self._listed, user_id, [f["id"] for f in files])
        return {"files": files, "next_page_token": body.get("nextPageToken")}

    def download(self, user_id: str, file_id: str) -> bytes:
        meta = self.get_metadata(user_id, file_id)
        if meta["size"] is not None and meta["size"] > self._max_download_bytes:
            raise FileTooLarge("the file is over the download limit")
        response = self._call(
            user_id, self._scopes("read"), "GET", f"{DRIVE_API}/files/{meta['id']}", params={"alt": "media"}
        )
        if len(response.content) > self._max_download_bytes:
            raise FileTooLarge("the file is over the download limit")
        return bytes(response.content)

    def _readable(self, user_id: str, file_id: str) -> str:
        known = self._picks.picked(user_id) | self._known(self._listed, user_id) | self._known(self._created, user_id)
        if not isinstance(file_id, str) or file_id not in known:
            raise NotPicked("the file is outside the files this user picked")
        return checked_id(file_id)

    def _known(self, table: dict[str, set[str]], user_id: str) -> frozenset[str]:
        with self._lock:
            return frozenset(table.get(user_id, ()))

    def _remember(self, table: dict[str, set[str]], user_id: str, ids: Iterable[str]) -> None:
        with self._lock:
            table.setdefault(user_id, set()).update(ids)

    def _get(self, user_id: str, scopes: list[str], path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        return self._json(user_id, scopes, "GET", DRIVE_API + path, params=params)

    # -- the one side-effect method (SEC-03) ------------------------------------------------------

    def execute_side_effect(self, entry: Mapping[str, Any], grant: Grant) -> dict[str, Any]:
        self._check_grant(entry, grant)
        return self._final_on_rejection(lambda: self._save(entry))

    def _save(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        if entry.get("action_type") != "save_file":
            raise SideEffectRefused("google_drive has no side effect for this action")
        item = self._artifact(entry.get("item"), "file")
        name, content, mime = item.get("name"), item.get("content"), str(item.get("mime_type", ""))
        if not isinstance(name, str) or not name or not isinstance(content, bytes | bytearray):
            raise SideEffectRefused("the file cannot be saved as written")
        mime = mime if _MIME.fullmatch(mime) else "application/octet-stream"
        user, scopes = self._owner_of(str(entry["world_id"])), self._scopes("write")
        destination = entry.get("destination")
        folder = self._tilo_folder(user, scopes, create=destination is None)
        if folder is None or (destination is not None and destination != folder):
            raise SideEffectRefused("files are saved only in the Tilo folder")
        marker = side_effect_marker(entry)
        mark = f"appProperties has {{ key='{_SAVE_KEY}' and value='{marker}' }}"
        q = f"'{folder}' in parents and trashed = false and {mark}"
        found = self._get(user, scopes, "/files", {"q": q, "fields": "files(id)"}).get("files") or []
        if found:  # OB-03: a lost response or another instance already saved it
            file_id = str(found[0]["id"])
        else:
            meta = {"name": name, "mimeType": mime, "parents": [folder], "appProperties": {_SAVE_KEY: marker}}
            boundary = "tilo-" + secrets.token_hex(16)
            while boundary.encode() in content:
                boundary = "tilo-" + secrets.token_hex(16)
            body = b"".join(
                [
                    f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode(),
                    jsonlib.dumps(meta).encode("utf-8"),
                    f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n".encode(),
                    bytes(content),
                    f"\r\n--{boundary}--\r\n".encode(),
                ]
            )
            params = {"uploadType": "multipart", "fields": "id"}
            headers = {"content-type": f"multipart/related; boundary={boundary}"}
            saved = self._json(user, scopes, "POST", DRIVE_UPLOAD_API, params=params, headers=headers, content=body)
            file_id = str(saved.get("id", ""))
        self._remember(self._created, user, [folder, file_id])
        return {"id": file_id, "folder_id": folder}

    def _tilo_folder(self, user: str, scopes: list[str], *, create: bool) -> str | None:
        """The `Tilo` folder in the Drive root that this adapter created: found again, never duplicated."""
        key, value = _FOLDER_MARK
        q = (
            f"'root' in parents and mimeType = '{FOLDER_MIME}' and name = '{TILO_FOLDER}' and trashed = false"
            f" and appProperties has {{ key='{key}' and value='{value}' }}"
        )
        found = self._get(user, scopes, "/files", {"q": q, "fields": "files(id)"}).get("files") or []
        if found:
            folder = checked_id(sorted(str(f["id"]) for f in found)[0])
        elif create:
            meta = {"name": TILO_FOLDER, "mimeType": FOLDER_MIME, "parents": ["root"], "appProperties": {key: value}}
            created = self._json(user, scopes, "POST", f"{DRIVE_API}/files", params={"fields": "id"}, json=meta)
            folder = checked_id(created.get("id"))
        else:
            return None
        self._remember(self._created, user, [folder])
        return folder


def _meta(raw: Mapping[str, Any]) -> dict[str, Any]:
    size = raw.get("size")
    return {
        "id": str(raw.get("id", "")),
        "name": str(raw.get("name", "")),
        "mime_type": str(raw.get("mimeType", "")),
        "size": int(size) if isinstance(size, str | int) and str(size).isdigit() else None,
        "parents": [str(p) for p in raw.get("parents") or []],
    }
