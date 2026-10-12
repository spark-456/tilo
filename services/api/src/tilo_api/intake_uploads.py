"""I2: bind intake uploads to the existing run artifact and raw-archive seams."""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from tilo_archive import RunArchive
from tilo_memory.artifacts import ArtifactRefused, ArtifactStore, NewVersion, Origin, Scope, StoredVersion
from tilo_planning.artifacts import InMemoryArtifactStore, StoredArtifact
from tilo_planning.extraction import FILE_TYPES, Budget, ExtractionError, extract
from tilo_planning.intake import IntakeRejected
from tilo_providers.interfaces import SafetyProvider


class UploadStorageError(RuntimeError):
    """Only the run artifact/archive operations failed; no input or backend message is exposed."""


class RunUploads(InMemoryArtifactStore):
    """One request's adapter; the API generates scope before screening, never from multipart fields.

    Completed puts can be rolled back through scoped lookups. A failed backend put retains
    the artifact store's existing partial-write repair/retention semantics. The archive is
    append-only and keeps attempt metadata; raw file bytes are held only by ArtifactStore.
    """

    def __init__(
        self, *, org_id: str, artifacts: Callable[[], ArtifactStore], archive: Callable[..., RunArchive]
    ) -> None:
        super().__init__()
        self.org_id, self.get_artifacts, self.open_archive = org_id, artifacts, archive
        self.scope: Scope | None = None
        self.artifacts: ArtifactStore | None = None
        self.archive: RunArchive | None = None
        self.run_id = ""
        self.completed: list[StoredVersion] = []
        self.prepared: dict[tuple[str, str], StoredArtifact] = {}
        self.converted: dict[tuple[str, str], str] = {}
        self.task_id = ""

    def bind(self, *, world_id: str, run_id: str, owner: str) -> None:
        if self.scope == Scope(self.org_id, world_id, owner) and self.run_id == run_id and self.archive is not None:
            return  # submit_intake consumes this request's already screened versions
        self.scope = Scope(self.org_id, world_id, owner)
        self.run_id, self.completed = run_id, []
        self.prepared, self.converted = {}, {}
        self.artifacts = self.get_artifacts().with_upload_text(self._converted_text)
        self.archive = self.open_archive(org_id=self.org_id, run_id=run_id)
        self.archive.records()  # read-only probe before a file screen or Director call

    def _converted_text(self, content: bytes, mime: str) -> str:
        return self.converted[(mime, hashlib.sha256(content).hexdigest())]

    def peek_prepared(self, filename: str, content: bytes) -> StoredArtifact | None:
        return self.prepared.get((filename, hashlib.sha256(content).hexdigest()))

    def screen_file(
        self, name: str, content: bytes, _safety: SafetyProvider, budget: Budget
    ) -> tuple[str | None, str | None, bool, str | None]:
        """Validate before put; only the store's one safety verdict can reach the Director."""
        if not content:
            return None, "empty file", False, None
        kind, mime, _ = FILE_TYPES[PurePosixPath(name.lower()).suffix]
        if mime == "text/csv":
            try:
                content.decode("utf-8-sig")
            except UnicodeDecodeError:
                return None, "not valid UTF-8 text", False, None
        try:
            text = extract(name, content, budget)
        except ExtractionError as exc:
            return None, str(exc), False, None
        if text is not None and not text.strip():
            return None, "empty file", False, None
        if kind == "converted" and text is not None:
            self.converted[(mime, hashlib.sha256(content).hexdigest())] = text
        try:
            stored = self.put(
                artifact_id=None,
                filename=name,
                content=content,
                content_type=mime,
                task_id=self.task_id,
                received_at=datetime.now(UTC).isoformat(),
            )
        except IntakeRejected as exc:
            return None, exc.reason, False, None
        if stored.screening == "unscreened":
            return None, "the stored file could not be screened", False, None
        flagged = stored.screening == "flagged"
        if mime == "text/csv":
            text = stored.content.decode("utf-8-sig")  # the Director sees the exact redacted stored text
        return text, None, flagged, stored.screening_reason

    def put(
        self,
        *,
        artifact_id: str | None,
        filename: str,
        content: bytes,
        content_type: str | None,
        task_id: str,
        received_at: str,
        screening: str = "unscreened",
        screening_reason: str | None = None,
    ) -> StoredArtifact:
        if self.scope is None or self.artifacts is None or self.archive is None or artifact_id is not None:
            raise RuntimeError("upload store is not bound to a new intake")
        if (ready := self.peek_prepared(filename, content)) is not None:
            return ready
        refused = failed = False
        try:
            version = self.artifacts.put(
                self.scope, NewVersion(content_type or "", content, self.run_id, Origin("upload"), label=filename)
            )
        except ArtifactRefused:
            refused = True
        except Exception:
            failed = True
        if refused:
            raise IntakeRejected("the file exceeds the existing artifact limits")
        if failed:
            raise UploadStorageError("upload artifact storage failed")
        if version.written:
            self.completed.append(version)
        record = version.record
        failed = False
        try:
            data = self.artifacts.read(self.scope, version.ref)
            archive_ref = self.archive.append(
                "channel_in",
                {
                    "source": {"kind": "file", "ref": version.artifact_id, "label": filename},
                    "media_type": record["media_type"],
                    "size": record["size_bytes"],
                    "sha256": record["content_sha256"],
                    "screening": record["screening"],
                },
            )
        except Exception:
            failed = True
        if failed:
            raise UploadStorageError("upload archive storage failed")
        origin: dict[str, Any] = {
            "source": "upload",
            "filename": filename,
            "sha256": record["content_sha256"],
            "received_at": received_at,
            "task_id": task_id,
        }
        verdict = record["screening"]
        stored = StoredArtifact(
            version.artifact_id,
            version.version,
            filename,
            data,
            content_type,
            origin,
            verdict,
            screening_reason or ("flagged by stored-file safety screen" if verdict == "flagged" else None),
            archive_ref,
        )
        self.prepared[(filename, hashlib.sha256(content).hexdigest())] = stored
        return stored

    def abort(self) -> None:
        try:
            if self.scope is None or self.artifacts is None:
                return
            for version in reversed(self.completed):
                if self.artifacts.head(self.scope, version.ref) is not None:
                    prefix = f"orgs/{self.scope.org_id}/worlds/{self.scope.world_id}/artifacts/{version.artifact_id}"
                    self.artifacts.retention().delete(f"{prefix}/versions/{version.version:06d}")
        finally:
            # A retry must rebind and screen; cached references may now name deleted versions.
            self.completed.clear()
            self.prepared.clear()
            self.converted.clear()
            self.scope = self.artifacts = self.archive = None
