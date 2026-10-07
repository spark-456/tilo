"""PROD-WIRE 2b (issue #522): the doors that open the durable artifact store and raw archive, and the two seams that use
them. The pattern is ADR-0023 / ADR-0026: an explicit switch (never implied by `K_SERVICE`), ADC only (the doors pass
no credentials), no client at import, none on a refusal.

Module: `tilo_api.run_stores`. The adapters take duck-typed clients, like `tilo_api.people_firestore`; `tilo_memory`
and `tilo_archive` stay pure (the archive package declares no dependencies) and `tilo_api` already holds the Firestore
adapters, the seams and `google-cloud-firestore`. New dependency: `google-cloud-storage`, imported lazily by the default
storage factory only (the tests run with or without it installed).

Pinned: `open_artifact_store(env=None, *, firestore_client_factory=None, storage_client_factory=None, redactor,
clock=None, archive_lookup=None, alert_sink=None) -> ArtifactStore` and `open_run_archive(env=None, *,
storage_client_factory=None, redactor) -> open_archive(*, org_id, run_id) -> RunArchive`; `redactor` has no default.
Env: `TILO_ARTIFACTS_STORE=gcs` + `TILO_ARTIFACTS_BUCKET`, `TILO_ARCHIVE_STORE=gcs` + `TILO_ARCHIVE_BUCKET`, and
`TILO_FIRESTORE_PROJECT` (one GCP project id for both). A factory is called as `factory(project)`; the default factories
are `firestore.Client(project=...)` and `storage.Client(project=...)`; the bucket is `client.bucket(name)` (no I/O).
Outside Cloud Run (no `K_SERVICE`) the default factories open only an emulator and a `demo-` project (`FIRESTORE_
EMULATOR_HOST` for Firestore, `STORAGE_EMULATOR_HOST` for GCS); an injected factory opens anywhere. A refusal is a
`RunStoreNotConfigured`, a `NotImplementedError`, which is how the seams already refuse. `archive_lookup` defaults to
"no record", so a put citing archive sources is refused (AR-03) until the lookup over the archive is wired.
`tilo_api.run_stores` does not exist yet: every test here fails at collection with `ModuleNotFoundError`.
"""

from __future__ import annotations

import re
import subprocess
import sys
import types
from unittest.mock import MagicMock

import pytest
from _prod_wire_2b_lib import PROJECT, SECRET, ClientSpy, FakeStorageClient, mask, patch_clients
from tilo_api import deps, runs
from tilo_api.run_stores import (
    FirestoreMetaBackend,
    GcsArchiveStore,
    GcsBlobBackend,
    RunStoreNotConfigured,
    open_artifact_store,
    open_run_archive,
    redact_leaves,
)
from tilo_archive import RunArchive
from tilo_memory.artifacts import ArtifactStore

LIVE = {"K_SERVICE": "tilo-api", "TILO_FIRESTORE_PROJECT": PROJECT, "TILO_ARTIFACTS_STORE": "gcs",
        "TILO_ARTIFACTS_BUCKET": f"{PROJECT}-artifacts", "TILO_ARCHIVE_STORE": "gcs",
        "TILO_ARCHIVE_BUCKET": f"{PROJECT}-archive"}  # fmt: skip
OFF = {k: v for k, v in LIVE.items() if k != "K_SERVICE"}
EMU = {"FIRESTORE_EMULATOR_HOST": "127.0.0.1:9", "STORAGE_EMULATOR_HOST": "http://127.0.0.1:9"}
NO_IO = re.compile(r"(collection|document)(\(\)\.(collection|document))*")
KINDS = {
    "artifacts": ("TILO_ARTIFACTS_STORE", "TILO_ARTIFACTS_BUCKET"),
    "archive": ("TILO_ARCHIVE_STORE", "TILO_ARCHIVE_BUCKET"),
}


REAL_GET_REDACTOR = deps.get_redactor


def without(env, *keys):
    return {k: v for k, v in env.items() if k not in keys}


def door(kind: str, env, **kwargs):
    if kind == "artifacts":
        return open_artifact_store(env, redactor=mask, **kwargs)
    return open_run_archive(
        env, redactor=lambda payload: payload, **{k: v for k, v in kwargs.items() if "storage" in k}
    )


@pytest.fixture(autouse=True)
def _cold_process(monkeypatch):
    for name in [*LIVE, *EMU, "TILO_SCHEDULES_STORE", "TILO_PEOPLE_STORE", "TILO_API_STORE"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(deps, "get_redactor", lambda: mask)
    for seam in (deps.get_artifact_store, deps.get_run_archive):
        seam.cache_clear()
    yield
    for seam in (deps.get_artifact_store, deps.get_run_archive):
        seam.cache_clear()


def test_PROD_WIRE_2b_door_importing_builds_no_client():
    code = (
        "import sys, types\n"
        "try:\n    import google.cloud.storage as s\nexcept ImportError:\n"
        "    import google.cloud\n    s = types.ModuleType('google.cloud.storage')\n"
        "    sys.modules['google.cloud.storage'] = s\n    google.cloud.storage = s\n"
        "import google.cloud.firestore as f\n"
        "def bomb(*a, **k):\n    raise SystemExit('a cloud client was built')\n"
        "s.Client = bomb\nf.Client = bomb\n"
        "import tilo_api.deps, tilo_api.run_stores as m\n"
        "names = ('FirestoreMetaBackend', 'GcsBlobBackend', 'GcsArchiveStore', 'RunStoreNotConfigured',\n"
        "         'open_artifact_store', 'open_run_archive', 'redact_leaves')\n"
        "print('ok' if all(hasattr(m, n) for n in names) else 'missing')\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert done.stdout.strip() == "ok", (done.stdout, done.stderr[-500:])


BAD = {
    "nothing": {}, "K_SERVICE alone": {"K_SERVICE": "tilo-api"}, "no project": without(LIVE, "TILO_FIRESTORE_PROJECT"),
    "bad project": {**LIVE, "TILO_FIRESTORE_PROJECT": "X"}, "bare demo": {**LIVE, "TILO_FIRESTORE_PROJECT": "demo"},
    "other stores' switches": {
        **without(LIVE, *[k for v in KINDS.values() for k in v]),
        **{name: "firestore" for name in ("TILO_SCHEDULES_STORE", "TILO_PEOPLE_STORE", "TILO_API_STORE")},
    },
}  # fmt: skip


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("env", BAD.values(), ids=BAD)
def test_PROD_WIRE_2b_door_refuses_without_explicit_config_and_builds_no_client(monkeypatch, kind, env):
    fs, st = patch_clients(monkeypatch)
    with pytest.raises(RunStoreNotConfigured, match=KINDS[kind][0]):
        door(kind, env)
    assert fs.calls == [] and st.calls == []


CASES = [("switch", v) for v in (None, "", "memory", "firestore", "GCS", "gcs ", "true")]
CASES += [("bucket", None), ("bucket", ""), ("both", None)]  # "both": only the other store is configured


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("part,value", CASES)
def test_PROD_WIRE_2b_door_needs_its_own_switch_set_to_exactly_gcs_and_its_own_bucket(monkeypatch, kind, part, value):
    fs, st = patch_clients(monkeypatch)
    switch, bucket = KINDS[kind]
    keys = {"switch": [switch], "bucket": [bucket], "both": [switch, bucket]}[part]
    with pytest.raises(RunStoreNotConfigured):
        door(kind, without(LIVE, *keys) if value is None else {**LIVE, keys[0]: value})
    assert fs.calls == [] and st.calls == []


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "name",
    ["", "ab", "x" * 64, "UPPER-case", "has space", "-lead", "_lead", "trail-", "a..b", "192.168.0.1"]
    + ["goog-bucket", "my-google-bucket", "gs://b", "a/b", "b\n", "ünï-bucket"],
)
def test_PROD_WIRE_2b_door_refuses_a_bucket_name_that_breaks_the_gcs_naming_rules(monkeypatch, kind, name):
    fs, st = patch_clients(monkeypatch)
    with pytest.raises(RunStoreNotConfigured):
        door(kind, {**LIVE, KINDS[kind][1]: name})
    assert fs.calls == [] and st.calls == []


def wire(monkeypatch, via: str):
    """Fake clients reached by the door's default factories ("default") or by injected ones ("injected")."""
    fs_client, st_client = MagicMock(name="firestore"), FakeStorageClient()
    if via == "default":
        fs_spy, st_spy = patch_clients(monkeypatch, fs_client, st_client)
        return fs_client, st_client, fs_spy, st_spy, {}
    patch_clients(monkeypatch)  # every default factory is a bomb
    fs_spy, st_spy = ClientSpy(fs_client), ClientSpy(st_client)
    return fs_client, st_client, fs_spy, st_spy, {"firestore_client_factory": fs_spy, "storage_client_factory": st_spy}


@pytest.mark.parametrize("via", ["default", "injected"])
def test_PROD_WIRE_2b_door_opens_the_artifact_store_in_cloud_run_over_firestore_and_gcs_with_no_io(monkeypatch, via):
    fs_client, st_client, fs_spy, st_spy, kwargs = wire(monkeypatch, via)
    store = open_artifact_store(LIVE, redactor=mask, **kwargs)
    assert isinstance(store, ArtifactStore)
    assert isinstance(store._meta, FirestoreMetaBackend) and isinstance(store._blobs, GcsBlobBackend)
    assert len(fs_spy.calls) == 1 and PROJECT in repr(fs_spy.calls[0]) and len(st_spy.calls) == 1
    assert (
        st_client.requested == [f"{PROJECT}-artifacts"] and st_client.buckets[f"{PROJECT}-artifacts"].upload_log == []
    )
    assert all(NO_IO.fullmatch(str(c[0])) for c in fs_client.mock_calls), fs_client.mock_calls


@pytest.mark.parametrize("via", ["default", "injected"])
def test_PROD_WIRE_2b_door_opens_the_raw_archive_in_cloud_run_over_gcs(monkeypatch, via):
    _, st_client, fs_spy, st_spy, kwargs = wire(monkeypatch, via)
    open_archive = open_run_archive(LIVE, redactor=lambda p: p, **{k: v for k, v in kwargs.items() if "storage" in k})
    assert len(st_spy.calls) == 1 and PROJECT in repr(st_spy.calls[0]) and st_client.requested == [f"{PROJECT}-archive"]
    assert fs_spy.calls == [], "the archive needs no Firestore client"
    run = open_archive(org_id="org_acme", run_id="r_1")
    assert isinstance(run, RunArchive) and isinstance(run._store, GcsArchiveStore)
    assert st_client.buckets[f"{PROJECT}-archive"].live_names() == []
    assert run.append("model_call", {"x": 1}) == "r_1/1"
    assert st_client.buckets[f"{PROJECT}-archive"].live_names() == ["org_acme/r_1/00000001.jsonl"]
    assert open_archive(org_id="org_acme", run_id="r_1").head() == run.head()
    with pytest.raises(TypeError):
        open_archive("org_acme", "r_1")  # keyword-only, as `Seams.open_archive` is called


DEMO = {"TILO_FIRESTORE_PROJECT": "demo-tilo"}
OUTSIDE_REFUSED = {
    "live project": OFF, "demo project, no emulator": {**OFF, **DEMO},
    "demo project, firestore host only": {**OFF, **DEMO, "FIRESTORE_EMULATOR_HOST": EMU["FIRESTORE_EMULATOR_HOST"]},
    "emulator hosts, live project": {**OFF, **EMU},
}  # fmt: skip


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("env", OUTSIDE_REFUSED.values(), ids=OUTSIDE_REFUSED)
def test_PROD_WIRE_2b_door_outside_cloud_run_never_builds_a_live_client(monkeypatch, kind, env):
    fs, st = patch_clients(monkeypatch)
    with pytest.raises(RunStoreNotConfigured):
        door(kind, env)
    with pytest.raises(RunStoreNotConfigured):  # GCS has no Firestore emulator to stand in for
        door("artifacts", {**OFF, **DEMO, "STORAGE_EMULATOR_HOST": EMU["STORAGE_EMULATOR_HOST"]})
    assert fs.calls == [] and st.calls == []


def test_PROD_WIRE_2b_door_outside_cloud_run_opens_the_emulators_on_a_demo_project(monkeypatch):
    _, _, fs_spy, st_spy, _ = wire(monkeypatch, "default")
    door("artifacts", {**OFF, **DEMO, **EMU})
    assert len(fs_spy.calls) == 1 and "demo-tilo" in repr(fs_spy.calls[0]) and len(st_spy.calls) == 1
    door("archive", {**OFF, **DEMO, "STORAGE_EMULATOR_HOST": EMU["STORAGE_EMULATOR_HOST"]})
    assert len(st_spy.calls) == 2 and len(fs_spy.calls) == 1


@pytest.mark.parametrize("kind", KINDS)
def test_PROD_WIRE_2b_door_outside_cloud_run_opens_over_a_test_injected_client(monkeypatch, kind):
    _, _, _, st_spy, kwargs = wire(monkeypatch, "injected")
    door(kind, OFF, **kwargs)  # the caller's own client is not a live one the door built
    assert len(st_spy.calls) == 1


def test_PROD_WIRE_2b_door_has_no_default_redactor(monkeypatch):
    _, _, _, _, kwargs = wire(monkeypatch, "injected")
    with pytest.raises(TypeError):
        open_artifact_store(LIVE, **kwargs)
    with pytest.raises(TypeError):
        open_run_archive(LIVE, storage_client_factory=kwargs["storage_client_factory"])
    assert kwargs["firestore_client_factory"].calls == [] and kwargs["storage_client_factory"].calls == []


def test_PROD_WIRE_2b_redact_leaves_masks_every_string_and_key_and_fails_closed():
    redact = redact_leaves(lambda text: text.replace("TOPSECRETWORD", "[R]"))
    payload = {"k TOPSECRETWORD": ["TOPSECRETWORD", {"n": 1, "f": 1.5, "b": True, "z": None, "s": "a TOPSECRETWORD"}]}
    assert redact(payload) == {"k [R]": ["[R]", {"n": 1, "f": 1.5, "b": True, "z": None, "s": "a [R]"}]}
    assert payload["k TOPSECRETWORD"][0] == "TOPSECRETWORD"

    def broken(text: str) -> str:
        raise RuntimeError("redactor down")

    with pytest.raises(RuntimeError):
        redact_leaves(broken)({"a": "b"})


# --- the seams ---------------------------------------------------------------------------------------------------

OTHERS = "plan_compiler layout_builder unit_runner action_resolver skill_registry connector_registry connector_adapters"
OTHERS += " outbox_store event_writer must_ask_providers"


def request_with_every_other_seam():
    overrides = {getattr(deps, f"get_{name}"): (lambda: object()) for name in OTHERS.split()}
    return types.SimpleNamespace(app=types.SimpleNamespace(dependency_overrides=overrides))


def deploy(monkeypatch, env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)


def test_PROD_WIRE_2b_seams_still_refuse_when_deployed_with_no_config_and_no_run_starts(monkeypatch):
    fs, st = patch_clients(monkeypatch)
    deploy(monkeypatch, {"K_SERVICE": "tilo-api"})
    for seam in (deps.get_artifact_store, deps.get_run_archive):
        with pytest.raises(NotImplementedError):
            seam()
    assert runs.run_seams(request_with_every_other_seam(), "replay") is None
    assert fs.calls == [] and st.calls == []


def test_PROD_WIRE_2b_seams_refuse_while_the_redactor_does_not_exist_and_build_no_client(monkeypatch):
    monkeypatch.setattr(deps, "get_redactor", REAL_GET_REDACTOR)  # refuses until FR-MEM-05 (BQ-109) lands
    fs, st = patch_clients(monkeypatch)
    deploy(monkeypatch, LIVE)
    for seam in (deps.get_artifact_store, deps.get_run_archive):
        with pytest.raises(NotImplementedError):
            seam()
    assert runs.run_seams(request_with_every_other_seam(), "replay") is None
    assert fs.calls == [] and st.calls == []


def test_PROD_WIRE_2b_seams_return_the_durable_store_and_archive_once_configured_and_cache_a_success(monkeypatch):
    fs_client, st_client, fs_spy, st_spy, _ = wire(monkeypatch, "default")
    deploy(monkeypatch, {"K_SERVICE": "tilo-api"})
    with pytest.raises(NotImplementedError):
        deps.get_artifact_store()  # a refusal is never cached
    deploy(monkeypatch, LIVE)
    store, open_archive = deps.get_artifact_store(), deps.get_run_archive()
    assert isinstance(store._meta, FirestoreMetaBackend) and isinstance(store._blobs, GcsBlobBackend)
    assert deps.get_artifact_store() is store and deps.get_run_archive() is open_archive and len(fs_spy.calls) == 1
    run = open_archive(org_id=deps.ORG_ID, run_id="r_1")
    run.append("tool_call", {"text": f"the key is {SECRET}"})  # the seam's archive redacts string leaves of a payload
    body = st_client.buckets[f"{PROJECT}-archive"].live_bytes(f"{deps.ORG_ID}/r_1/00000001.jsonl")
    assert b"[REDACTED]" in body and SECRET.encode() not in body
    seams = runs.run_seams(request_with_every_other_seam(), "replay")
    assert seams is not None and isinstance(seams.artifacts, ArtifactStore) and seams.open_archive is open_archive
    deploy(monkeypatch, {"TILO_ARTIFACTS_BUCKET": f"{PROJECT}-artifacts-two"})
    assert deps.get_artifact_store() is not store  # a changed config is a new store, over the new bucket
    assert f"{PROJECT}-artifacts-two" in st_client.requested
