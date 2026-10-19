"""Office output follows the same storage, manifest and redaction rules as PDF."""

from agt_output_support import RUN, SECRET, outcome, run_units
from tilo_harness.outputs import RenderedOffice

MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def office(spec="Verified report"):
    return RenderedOffice(media_type=MIME, content=b"PK\x03\x04offline", spec_text=spec)


def test_M1_RENDER_1_office_is_stored_as_render_with_manifest(tmp_path):
    output = office()
    ran = run_units(tmp_path, {"U1": outcome([output])}, with_archive=True)
    created = ran.of("artifact.created")
    assert len(created) == 1
    ref = created[0]["data"]["artifact"]
    record = ran.rig.store.head(ran.rig.scope, ref).record
    assert record["origin"] == {"kind": "render", "unit": "U1", "agent": None}
    assert record["media_type"] == MIME
    assert record["idempotency_key"] == f"{RUN}:U1:0:0"
    assert ran.rig.store.read(ran.rig.scope, ref) == output.content
    assert ran.rig.store.manifest_revisions(ran.rig.scope, ref)


def test_M1_RENDER_1_secret_spec_is_never_stored(tmp_path):
    ran = run_units(tmp_path, {"U1": outcome([office(SECRET)])}, with_archive=True)
    assert ran.of("artifact.created") == []
    assert not ran.result.outcomes["U1"].success


def test_M1_RENDER_1_modified_office_bytes_are_rechecked_before_storage(tmp_path):
    output = office()
    object.__setattr__(output, "content", b"not an Office file")
    ran = run_units(tmp_path, {"U1": outcome([output])}, with_archive=True)
    assert ran.of("artifact.created") == []
    assert not ran.result.outcomes["U1"].success
