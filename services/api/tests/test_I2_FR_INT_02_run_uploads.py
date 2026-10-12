"""I2: intake references name owner-scoped run artifacts, not a separate byte store."""

from datetime import UTC, datetime

import pytest
from tilo_api import app, intake
from tilo_api.intake_uploads import RunUploads
from tilo_archive.archive import LocalDirStore, RunArchive
from tilo_memory.artifacts import ArtifactNotFound, ArtifactStore, MemoryBlobBackend, MemoryMetaBackend, Scope


class Clean:
    def check(self, *_args, **_kwargs):
        return {"flagged": False}


@pytest.mark.parametrize(
    "error,status,code", [("spend", 403, "spend_cap_reached"), ("model", 503, "model_unavailable")]
)
def test_I2_FR_INT_02_files_preserve_model_or_spend_failure(uploads, monkeypatch, error, status, code):
    from tilo_api import deps, spend

    client, _, artifacts, _ = uploads

    def fail(*_args, **_kwargs):
        raise spend.SpendCapReached() if error == "spend" else deps.ModelUnavailable()

    monkeypatch.setattr(intake, "extract_brief", fail)
    response = post(client)
    assert response.status_code == status
    assert response.json()["code"] == code
    assert artifacts.retention().records() == []


@pytest.mark.parametrize("status,detail", [(429, "demo_capacity"), (503, "store_unavailable"), (409, "stale")])
def test_I2_FR_INT_02_commit_preserves_http_failure_and_cleans_only_uncommitted(uploads, monkeypatch, status, detail):
    from fastapi import HTTPException

    client, _, artifacts, _ = uploads

    def fail(*_args, **_kwargs):
        raise HTTPException(status_code=status, detail=detail)

    monkeypatch.setattr(intake, "create_task", fail)
    response = post(client)
    assert response.status_code == status
    assert response.json() == {"detail": detail}
    assert artifacts.retention().records() == []


def test_I2_FR_INT_02_an_unknown_commit_that_landed_keeps_its_uploads(uploads, store, monkeypatch):
    from fastapi import HTTPException

    client, _, artifacts, _ = uploads
    create = intake.create_task

    def landed(*args, **kwargs):
        create(*args, **kwargs)
        raise HTTPException(status_code=503, detail="store_unavailable")

    monkeypatch.setattr(intake, "create_task", landed)
    assert post(client).status_code == 503
    task = next(iter(store.tasks.values()))
    ref = next(s["ref"] for s in task.brief["sources"] if s["kind"] == "file")
    assert artifacts.read(Scope("org_tilo", task.world_id, task.owner), {"artifact_id": ref, "version": 1})


@pytest.fixture
def uploads(client, tmp_path):
    meta, blobs, raw = MemoryMetaBackend(), MemoryBlobBackend(), LocalDirStore(tmp_path)
    artifacts = ArtifactStore(
        meta,
        blobs,
        clock=lambda: datetime(2026, 10, 12, tzinfo=UTC),
        redactor=lambda s: s,
        archive_lookup=lambda *_: None,
        alert_sink=lambda _: None,
        screener=Clean(),
    )
    archives = {}

    def archive(**scope):
        archives[scope["run_id"]] = RunArchive(raw, **scope, redactor=lambda p: p)
        return archives[scope["run_id"]]

    bridge = RunUploads(org_id="org_tilo", artifacts=lambda: artifacts, archive=archive)
    app.dependency_overrides[intake.get_store] = lambda: bridge
    return client, bridge, artifacts, archives


def post(client, files=None):
    return client.post(
        "/intake",
        data={"text": "Use the attached data."},
        files=files or [("files", ("data.csv", b"month,total\nMay,42", "text/csv"))],
    )


def test_I2_FR_INT_02_upload_ref_resolves_in_its_principal_world(uploads, store):
    client, bridge, artifacts, archives = uploads
    response = post(client)
    assert response.status_code == 201, response.text
    body = response.json()
    ref = body["files"][0]["artifact"]
    scope = Scope("org_tilo", body["world_id"], "u_intake")
    assert artifacts.read(scope, ref) == b"month,total\nMay,42"
    record = artifacts.head(scope, ref).record
    assert record["origin"]["kind"] == "upload"
    assert record["sources"] == []  # AR-03: upload versions have no archive sources
    assert record["run_id"] == body["run_id"]
    assert store.tasks[body["task_id"]].brief["sources"][-1]["ref"] == ref["artifact_id"]
    event = next(e for e in store.events[body["world_id"]] if e["type"] == "artifact.created")
    assert event["trace"]["archive_ref"] == body["run_id"] + "/1"
    payload = archives[body["run_id"]].records()[0]["payload"]
    assert payload["sha256"] == record["content_sha256"]
    assert "content" not in payload  # bytes live in the artifact store, never a JSON archive copy
    assert bridge.list_ids() == []


def test_I2_FR_INT_02_second_owner_cannot_read_upload(uploads):
    client, _, artifacts, _ = uploads
    body = post(client).json()
    with pytest.raises(ArtifactNotFound):
        artifacts.read(Scope("org_tilo", body["world_id"], "u_other"), body["files"][0]["artifact"])
    with pytest.raises(ArtifactNotFound):
        artifacts.read(Scope("org_other", body["world_id"], "u_intake"), body["files"][0]["artifact"])


def test_I2_FR_INT_02_director_failure_never_opens_upload_stores(uploads, monkeypatch):
    from tilo_planning.brief import BriefExtractionError

    client, _, artifacts, archives = uploads

    def fail(*_args, **_kwargs):
        raise BriefExtractionError("unavailable")

    monkeypatch.setattr(intake, "extract_brief", fail)
    assert post(client).status_code == 502
    assert artifacts.retention().records() == []
    assert archives == {}


def test_I2_FR_INT_02_task_failure_cleans_completed_upload_versions(uploads, monkeypatch):
    client, _, artifacts, archives = uploads

    def fail(*_args, **_kwargs):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(intake, "create_task", fail)
    assert post(client).status_code == 503
    assert artifacts.retention().records() == []
    # The raw archive is append-only: metadata of a failed attempt is retained, with no file bytes.
    assert all("content" not in r["payload"] for a in archives.values() for r in a.records())


def test_I2_FR_INT_02_archive_failure_cleans_upload_bytes(uploads, monkeypatch):
    client, bridge, artifacts, _ = uploads

    class Broken:
        def append(self, *_):
            raise RuntimeError("archive unavailable")

    monkeypatch.setattr(bridge, "open_archive", lambda **_: Broken())
    assert post(client).status_code == 503
    assert artifacts.retention().records() == []


def test_I2_FR_INT_02_preserves_other_scopes_on_rollback(uploads, monkeypatch):
    client, _, artifacts, _ = uploads
    first = post(client).json()
    ref = first["files"][0]["artifact"]

    def fail(*_args, **_kwargs):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(intake, "create_task", fail)
    assert post(client).status_code == 503
    assert artifacts.read(Scope("org_tilo", first["world_id"], "u_intake"), ref) == b"month,total\nMay,42"


@pytest.mark.parametrize("verdict", ["flagged", "unscreened"])
def test_I2_FR_INT_02_stored_verdict_cannot_be_upgraded_to_clean(uploads, store, verdict):
    client, _, artifacts, _ = uploads

    class Flagged:
        def check(self, *_args, **_kwargs):
            return {"flagged": True}

    artifacts._screener = Flagged() if verdict == "flagged" else None
    response = post(client)
    assert response.status_code == 201
    body = response.json()
    file = body["files"][0]
    assert file["safety_flagged"] if verdict == "flagged" else file["status"] == "failed"
    assert all(s.get("ref") != file["artifact"]["artifact_id"] for s in store.tasks[body["task_id"]].brief["sources"])


def test_I2_FR_INT_02_quick_mode_opens_no_upload_store(uploads):
    client, bridge, artifacts, archives = uploads
    response = client.post(
        "/intake",
        data={"text": "Read the file.", "mode": "quick"},
        files=[("files", ("data.csv", b"a,b", "text/csv"))],
    )
    assert response.status_code == 200
    assert bridge.scope is None and archives == {}
    assert artifacts.retention().records() == []


def test_I2_FR_INT_02_deployed_factory_is_lazy_and_demo_stays_ephemeral(monkeypatch):
    from types import SimpleNamespace

    from tilo_api import ephemeral
    from tilo_planning.artifacts import InMemoryArtifactStore

    monkeypatch.setenv("K_SERVICE", "fake-api")
    monkeypatch.setattr(ephemeral, "for_request", lambda _: None)
    assert isinstance(intake.get_store(SimpleNamespace()), RunUploads)
    memory = InMemoryArtifactStore()
    monkeypatch.setattr(ephemeral, "for_request", lambda _: SimpleNamespace(uploads=memory))
    assert intake.get_store(SimpleNamespace()) is memory


def test_I2_FR_INT_02_original_flag_cannot_be_lost_in_archival(uploads):
    from _api_contracts_lib import INJECTION_PHRASE

    client, _, artifacts, archives = uploads
    response = post(client, [("files", ("flagged.csv", INJECTION_PHRASE.encode(), "text/csv"))])
    assert response.status_code == 422
    assert artifacts.retention().records() == []
    assert all(a.records() == [] for a in archives.values())
