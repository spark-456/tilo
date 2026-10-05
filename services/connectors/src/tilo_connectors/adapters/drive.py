"""DriveAdapter: read the files a user picked, write deliverables to a Tilo folder (FR-CON-05, PRD 12.2).

Every call uses drive.file. A file is readable only when the user picked it, `list_folder` listed it from
a picked folder, or this adapter created it; anything else is `NotPicked` before any request names it.
Saving is the one side effect (SEC-03), into the folder named `Tilo` this adapter created, exactly once.
`save_as_google_file` (FR-CON-11) is the same save with Drive's upload-with-conversion: a PPTX, DOCX or XLSX
artifact becomes a native Slides, Docs or Sheets file, still on drive.file, with no new method or scope.
File names are data: returned verbatim, never logged, never a path.
"""

from __future__ import annotations

import json as jsonlib
import re
import secrets
import threading
from collections.abc import Iterable, Mapping
from typing import Any

from ..errors import PossiblySent
from ..outbox import Grant
from ._google import GoogleAdapter, checked_id, side_effect_marker
from ._transport import AdapterError, FileTooLarge, NotPicked, SideEffectRefused

DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3/files"
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024  # one Drive download
FOLDER_MIME = "application/vnd.google-apps.folder"
TILO_FOLDER = "Tilo"
_FIELDS = "id,name,mimeType,size,parents"
_FOLDER_MARK = ("tilo_role", "folder")  # appProperties of the folder this adapter created
_SAVE_KEY = "tilo_save"  # appProperties key of a saved file: side_effect_marker(entry)
_MIME = re.compile(r"[A-Za-z0-9][\w.+-]*/[\w.+-]+")
_OOXML = "application/vnd.openxmlformats-officedocument."
_NATIVE = {  # tilo-render's OOXML type -> (the native Google type Drive converts it to, its editor URL segment)
    _OOXML + "presentationml.presentation": ("application/vnd.google-apps.presentation", "presentation"),
    _OOXML + "wordprocessingml.document": ("application/vnd.google-apps.document", "document"),
    _OOXML + "spreadsheetml.sheet": ("application/vnd.google-apps.spreadsheet", "spreadsheets"),
}
_OOXML_EXTENSION = re.compile(r"\.(pptx|docx|xlsx)\Z", re.IGNORECASE | re.ASCII)


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
        fid = self._readable(user_id, file_id)
        meta = self.get_metadata(user_id, fid)
        if meta["id"] != fid:  # only the checked id is ever fetched, whatever Google's answer names
            raise AdapterError("the metadata names another file")
        if meta["size"] is not None and meta["size"] > self._max_download_bytes:
            raise FileTooLarge("the file is over the download limit")
        response = self._call(user_id, self._scopes("read"), "GET", f"{DRIVE_API}/files/{fid}", params={"alt": "media"})
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

    def _get(
        self, user_id: str, scopes: list[str], path: str, params: Mapping[str, Any], patient: bool = True
    ) -> dict[str, Any]:
        return self._json(user_id, scopes, "GET", DRIVE_API + path, params=params, patient=patient)

    # -- the one side-effect method (SEC-03) ------------------------------------------------------

    def execute_side_effect(self, entry: Mapping[str, Any], grant: Grant) -> dict[str, Any]:
        self._check_grant(entry, grant)
        return self._final_on_rejection(lambda: self._save(entry))

    def _save(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        action = entry.get("action_type")
        if action not in ("save_file", "save_as_google_file"):
            raise SideEffectRefused("google_drive has no side effect for this action")
        item = self._artifact(entry.get("item"), "file")
        name, content, mime = item.get("name"), item.get("content"), str(item.get("mime_type", ""))
        if not isinstance(name, str) or not name or not isinstance(content, bytes | bytearray):
            raise SideEffectRefused("the file cannot be saved as written")
        mime = mime if _MIME.fullmatch(mime) else "application/octet-stream"
        native = None
        if action == "save_as_google_file":  # FR-CON-11: only a deck, doc or sheet from tilo-render converts
            origin = item.get("origin")  # a converted Sheet runs formulas (IMPORTXML): never an upload or a third party
            if not isinstance(origin, Mapping) or origin.get("kind") != "render":
                raise SideEffectRefused("only a file tilo-render made becomes a Slides, Docs or Sheets file")
            if mime not in _NATIVE:
                raise SideEffectRefused("only a PPTX, DOCX or XLSX file becomes a Slides, Docs or Sheets file")
            native, name = _NATIVE[mime], _OOXML_EXTENSION.sub("", name) or name
        user, scopes = self._owner_of(str(entry["world_id"])), self._scopes("write")
        marker = side_effect_marker(entry)
        q = f"trashed = false and appProperties has {{ key='{_SAVE_KEY}' and value='{marker}' }}"  # in any folder
        found = self._get(user, scopes, "/files", {"q": q, "fields": "files(id,parents)"}, patient=False)
        if earlier := found.get("files") or []:  # OB-03: a lost response or another instance already saved it
            file_id, parents = _final_id(earlier[0].get("id")), earlier[0].get("parents") or []
            folder = _final_id(parents[0]) if parents else ""
        else:
            destination = entry.get("destination")
            folders = self._tilo_folders(user, scopes, create=destination is None)
            if not folders or (destination is not None and destination not in folders):
                raise SideEffectRefused("files are saved only in the Tilo folder")
            folder = destination if destination is not None else folders[0]
            shared = self._get(user, scopes, f"/files/{checked_id(folder)}", {"fields": "id,shared"}, patient=False)
            if shared.get("shared") is not False:  # a save there reaches other people: external sharing, a T3 act
                raise SideEffectRefused("the Tilo folder is shared; a save there is external sharing")
            stored = native[0] if native else mime  # the type Drive stores; the media part keeps the source type
            meta = {"name": name, "mimeType": stored, "parents": [folder], "appProperties": {_SAVE_KEY: marker}}
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
            params = {"uploadType": "multipart", "fields": "id,shared"}
            headers = {"content-type": f"multipart/related; boundary={boundary}"}
            saved = self._json(
                user, scopes, "POST", DRIVE_UPLOAD_API, params=params, headers=headers, content=body, patient=False
            )
            file_id = _final_id(saved.get("id"))  # the file exists, so a bad id is final, never retried (alerts)
            if saved.get("shared") is not False:  # it was shared between the check and the upload (or Drive said
                raise PossiblySent("the saved file is shared; a person checks who can see it")  # nothing): fail closed
        self._remember(self._created, user, [i for i in (folder, file_id) if i])
        if native:  # the editor link is built from the checked id, never taken from an answer
            url = f"https://docs.google.com/{native[1]}/d/{checked_id(file_id)}/edit"
            return {"id": file_id, "folder_id": folder, "mime_type": native[0], "open_url": url}
        return {"id": file_id, "folder_id": folder}

    def _tilo_folders(self, user: str, scopes: list[str], *, create: bool) -> list[str]:
        """The `Tilo` folders in the Drive root that this adapter created, smallest id first. Two racing
        first saves can each create one; both re-list after creating, so both adopt the smallest id."""
        key, value = _FOLDER_MARK
        q = (
            f"'root' in parents and mimeType = '{FOLDER_MIME}' and name = '{TILO_FOLDER}' and trashed = false"
            f" and appProperties has {{ key='{key}' and value='{value}' }}"
        )

        def listed() -> list[str]:
            found = self._get(user, scopes, "/files", {"q": q, "fields": "files(id)"}, patient=False)
            return sorted(checked_id(f.get("id")) for f in found.get("files") or [])

        folders = listed()
        if not folders and create:
            meta = {"name": TILO_FOLDER, "mimeType": FOLDER_MIME, "parents": ["root"], "appProperties": {key: value}}
            made = self._json(
                user, scopes, "POST", f"{DRIVE_API}/files", params={"fields": "id"}, json=meta, patient=False
            )
            folders = listed() or [checked_id(made.get("id"))]
        self._remember(self._created, user, folders)
        return folders


def _final_id(value: Any) -> str:
    """The id of a file that exists (just uploaded, or found by an earlier attempt). A bad id cannot be used or
    retried, but the file is there: PossiblySent, so the outbox alerts a person instead of failing quietly."""
    try:
        return checked_id(value)
    except AdapterError:
        raise PossiblySent("Drive answered with an id that is not a valid id; the file may exist") from None


def _meta(raw: Mapping[str, Any]) -> dict[str, Any]:
    size = raw.get("size")
    return {
        "id": str(raw.get("id", "")),
        "name": str(raw.get("name", "")),
        "mime_type": str(raw.get("mimeType", "")),
        "size": int(size) if isinstance(size, str | int) and str(size).isdigit() else None,
        "parents": [str(p) for p in raw.get("parents") or []],
    }
