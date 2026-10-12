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


def post(client, files=None, *, key=None):
    return client.post(
        "/intake",
        data={"text": "Use the attached data."},
        headers={"Idempotency-Key": key} if key else {},
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


def test_I2_FR_INT_02_director_failure_cleans_prepared_uploads(uploads, monkeypatch):
    from tilo_planning.brief import BriefExtractionError

    client, _, artifacts, archives = uploads

    def fail(*_args, **_kwargs):
        raise BriefExtractionError("unavailable")

    monkeypatch.setattr(intake, "extract_brief", fail)
    assert post(client).status_code == 502
    assert artifacts.retention().records() == []
    # Supervisor 13:35: both stores are probed before the Director; attempt metadata is append-only.
    assert archives and all("content" not in r["payload"] for a in archives.values() for r in a.records())


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
        def records(self):
            return []  # bind succeeds; exercise failure after the artifact version was actually written

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


def test_I2_FR_INT_02_original_flag_cannot_be_lost_in_archival(uploads, store):
    from _api_contracts_lib import INJECTION_PHRASE, make_safety_provider

    client, _, artifacts, archives = uploads
    # The store owns the single file verdict; use the real fake safety policy rather than an always-clean stub.
    artifacts._screener = make_safety_provider()
    response = post(client, [("files", ("flagged.csv", INJECTION_PHRASE.encode(), "text/csv"))])
    assert response.status_code == 201
    body = response.json()
    assert body["files"][0]["safety_flagged"]
    assert (
        artifacts.head(Scope("org_tilo", body["world_id"], "u_intake"), body["files"][0]["artifact"]).record[
            "screening"
        ]
        == "flagged"
    )
    assert next(iter(archives.values())).records()[0]["payload"]["screening"] == "flagged"
    assert all(s["kind"] != "file" for s in store.tasks[body["task_id"]].brief["sources"])


@pytest.mark.parametrize(
    "ext,part", [("docx", "word/document.xml"), ("pptx", "ppt/slides/slide1.xml"), ("xlsx", "xl/worksheets/sheet1.xml")]
)
def test_I2_FR_INT_02_office_uses_one_media_gated_text_screen(uploads, monkeypatch, ext, part):
    import io
    import zipfile

    from tilo_providers.interfaces import SafetyProvider

    client, _, artifacts, _ = uploads
    calls, inputs = [], []

    class Gated(SafetyProvider):
        def _check(self, text, *, content, mime_type):
            calls.append((text, content, mime_type))
            return {"flagged": False, "reason": None}

    artifacts._screener = Gated()
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as package:
        package.writestr(part, "<root><t>quarterly sales</t></root>")
    extract = intake.extract_brief

    def director(*args, **kwargs):
        inputs.append(kwargs["source_text"])
        return extract(*args, **kwargs)

    monkeypatch.setattr(intake, "extract_brief", director)
    response = post(client, [("files", (f"data.{ext}", data.getvalue(), "application/octet-stream"))])
    assert response.status_code == 201, response.text
    assert response.json()["files"][0]["status"] == "ok"
    assert calls == [("quarterly sales", None, None)]
    assert "quarterly sales" in inputs[0]


@pytest.mark.parametrize("verdict", ["flagged", "unscreened"])
def test_I2_FR_INT_02_stored_unsafe_file_never_reaches_director(uploads, monkeypatch, verdict):
    client, _, artifacts, _ = uploads
    inputs = []

    class Flagged:
        def check(self, *_args, **_kwargs):
            return {"flagged": True}

    artifacts._screener = Flagged() if verdict == "flagged" else None
    extract = intake.extract_brief

    def director(*args, **kwargs):
        inputs.append((kwargs["source_text"], kwargs["parts"]))
        return extract(*args, **kwargs)

    monkeypatch.setattr(intake, "extract_brief", director)
    assert post(client).status_code == 201
    assert inputs == [("", [])]


@pytest.mark.parametrize("backend", ["artifacts", "archive"])
def test_I2_FR_INT_02_store_failure_precedes_director(uploads, monkeypatch, backend):
    client, bridge, artifacts, _ = uploads

    def fail(*_args, **_kwargs):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(bridge, "get_artifacts" if backend == "artifacts" else "open_archive", fail)
    monkeypatch.setattr(intake, "extract_brief", lambda *_a, **_k: pytest.fail("Director must not run"))
    assert post(client).status_code == 503
    assert artifacts.retention().records() == []


@pytest.mark.parametrize(
    "name,data,error",
    [
        ("data.csv", b"\xff", "not valid UTF-8 text"),
        ("data.csv", b"", "empty file"),
        ("data.csv", b"  \n", "empty file"),
        ("data.png", b"bad", "native file is unreadable"),
        ("data.docx", b"PK\x03\x04bad", "unreadable package"),
    ],
)
def test_I2_FR_INT_02_invalid_file_refuses_before_put(uploads, monkeypatch, name, data, error):
    client, _, artifacts, _ = uploads
    monkeypatch.setattr(artifacts, "put", lambda *_a, **_k: pytest.fail("invalid bytes must not be put"))
    response = post(client, [("files", (name, data, "application/octet-stream"))])
    assert response.status_code == 201, response.text
    file = response.json()["files"][0]
    assert file["status"] == "failed" and error in file["error"]
    assert file["artifact"] == {} and artifacts.retention().records() == []


def test_I2_FR_INT_02_retry_is_single_world_and_body_scoped(uploads, store):
    from tilo_api import deps

    client, _, artifacts, _ = uploads
    first = post(client, key="retry-1")
    assert first.status_code == 201, first.text
    assert post(client, key="retry-1").json() == first.json()
    assert len(store.tasks) == len(artifacts.retention().records()) == 1
    changed = post(client, [("files", ("data.csv", b"different", "text/csv"))], key="retry-1")
    assert changed.status_code == 422
    app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(user_id="u_other", role="owner")
    other = post(client, key="retry-1")
    assert other.status_code == 201 and other.json()["world_id"] != first.json()["world_id"]


def test_I2_FR_INT_02_failed_retry_rebinds_deleted_prepared_versions(uploads, monkeypatch):
    client, bridge, artifacts, _ = uploads
    create = intake.create_task

    def fail(*_args, **_kwargs):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(intake, "create_task", fail)
    assert post(client, key="retry-1").status_code == 503
    assert not bridge.prepared and bridge.scope is None
    monkeypatch.setattr(intake, "create_task", create)
    response = post(client, key="retry-1")
    assert response.status_code == 201, response.text
    body = response.json()
    assert artifacts.read(Scope("org_tilo", body["world_id"], "u_intake"), body["files"][0]["artifact"])


def test_I2_FR_INT_02_unknown_landed_retry_makes_no_second_world(uploads, store, monkeypatch):
    client, _, artifacts, _ = uploads
    create = intake.create_task

    def landed(*args, **kwargs):
        create(*args, **kwargs)
        raise RuntimeError("commit acknowledgement lost")

    monkeypatch.setattr(intake, "create_task", landed)
    assert post(client, key="retry-1").status_code == 503
    monkeypatch.setattr(intake, "extract_brief", lambda *_a, **_k: pytest.fail("committed retry must not run Director"))
    response = post(client, key="retry-1")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "intake_already_committed"
    assert len(store.tasks) == len(artifacts.retention().records()) == 1


def test_I2_FR_INT_02_failed_commit_read_retains_owned_versions(uploads, store, monkeypatch):
    client, _, artifacts, _ = uploads

    def fail(*_args, **_kwargs):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(intake, "create_task", fail)
    monkeypatch.setattr(store, "load_path", fail)
    assert post(client).status_code == 503
    assert len(artifacts.retention().records()) == 1


@pytest.mark.parametrize("reason", ["refused", "nothing", "provider", "submit"])
def test_I2_FR_INT_02_precommit_refusals_clean_prepared_versions(uploads, monkeypatch, reason):
    from tilo_planning.gaps import NothingPossible
    from tilo_planning.refusal import TaskRefused
    from tilo_providers.errors import ProviderError

    client, bridge, artifacts, _ = uploads
    errors = {
        "refused": TaskRefused("test", "refused", "alternative"),
        "nothing": NothingPossible((), "nothing possible"),
        "provider": ProviderError("unavailable"),
        "submit": RuntimeError("unavailable"),
    }

    def fail(*_args, **_kwargs):
        raise errors[reason]

    monkeypatch.setattr(intake, "submit_intake" if reason == "submit" else "extract_brief", fail)
    response = post(client)
    assert response.status_code == (422 if reason in {"refused", "nothing"} else 503)
    assert artifacts.retention().records() == [] and not bridge.prepared


def test_I2_FR_INT_02_cancelled_commit_retains_owned_versions(uploads, monkeypatch):
    import asyncio
    from concurrent.futures import CancelledError

    client, _, artifacts, _ = uploads

    def cancel(*_args, **_kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(intake, "create_task", cancel)
    with pytest.raises(CancelledError):
        post(client)
    assert len(artifacts.retention().records()) == 1
