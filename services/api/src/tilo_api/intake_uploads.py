"""I2: bind intake uploads to the existing run artifact and raw-archive seams."""

from collections.abc import Callable
from typing import Any

from tilo_archive import RunArchive
from tilo_memory.artifacts import ArtifactRefused, ArtifactStore, NewVersion, Origin, Scope, StoredVersion
from tilo_planning.artifacts import InMemoryArtifactStore, StoredArtifact
from tilo_planning.intake import IntakeRejected


class RunUploads(InMemoryArtifactStore):
    """One request's adapter; scope is supplied by submit_intake, never by multipart fields.

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

    def bind(self, *, world_id: str, run_id: str, owner: str) -> None:
        self.scope = Scope(self.org_id, world_id, owner)
        self.run_id, self.completed = run_id, []
        self.artifacts = self.get_artifacts()
        self.archive = self.open_archive(org_id=self.org_id, run_id=run_id)

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
        try:
            version = self.artifacts.put(
                self.scope, NewVersion(content_type or "", content, self.run_id, Origin("upload"), label=filename)
            )
        except ArtifactRefused:
            raise IntakeRejected("A file cannot be archived under the existing artifact limits.") from None
        if version.written:
            self.completed.append(version)
        record = version.record
        if screening != "clean" and record["screening"] != screening:
            raise IntakeRejected("A file could not be archived with its original screening status.")
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
        origin: dict[str, Any] = {
            "source": "upload",
            "filename": filename,
            "sha256": record["content_sha256"],
            "received_at": received_at,
            "task_id": task_id,
        }
        # Never upgrade the original screening verdict, even if a later screen differs.
        verdict = screening if screening != "clean" else record["screening"]
        return StoredArtifact(
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

    def abort(self) -> None:
        if self.scope is None or self.artifacts is None:
            return
        for version in reversed(self.completed):
            if self.artifacts.head(self.scope, version.ref) is not None:
                prefix = f"orgs/{self.scope.org_id}/worlds/{self.scope.world_id}/artifacts/{version.artifact_id}"
                self.artifacts.retention().delete(f"{prefix}/versions/{version.version:06d}")
        self.completed.clear()
