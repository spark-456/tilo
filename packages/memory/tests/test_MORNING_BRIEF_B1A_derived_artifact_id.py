"""MORNING-BRIEF-B1A, MO-09: `ArtifactStore.with_new_id`, a request-local view that names a new artifact with a derived
id (one morning brief per local date). The id is still checked; the original store is unchanged; a later version of the
artifact keeps its id through `parent`."""

from __future__ import annotations

import dataclasses

import pytest
from _artifact_testlib import ARTICLE, make_rig
from tilo_memory.artifacts import ArtifactError


def test_MORNING_BRIEF_B1A_MO09_the_view_names_a_new_artifact_with_the_derived_id_and_leaves_the_store_alone():
    rig = make_rig("memory", None)
    first = rig.store.with_new_id(lambda: "art_mbrief_20261016").put(rig.scope, rig.new(ARTICLE))
    assert first.artifact_id == "art_mbrief_20261016" and first.version == 1
    second = rig.store.with_new_id(lambda: "art_other").put(
        rig.scope, dataclasses.replace(rig.new(ARTICLE + b" v2"), parent=first.ref)
    )
    assert (second.artifact_id, second.version) == ("art_mbrief_20261016", 2)  # a parent decides the id
    assert rig.store.put(rig.scope, rig.new(ARTICLE + b" other")).artifact_id != "art_mbrief_20261016"


@pytest.mark.parametrize("bad", ["", "mbrief", "art_has space", "art_" + "x" * 60])
def test_MORNING_BRIEF_B1A_MO09_a_malformed_derived_id_is_refused(bad):
    rig = make_rig("memory", None)
    with pytest.raises(ArtifactError):
        rig.store.with_new_id(lambda: bad).put(rig.scope, rig.new(ARTICLE))


def test_MORNING_BRIEF_B1A_MO09_artifact_ids_lists_the_owners_artifacts_of_the_scope_by_prefix():
    rig = make_rig("memory", None)
    for aid in ("art_mbrief_20260920", "art_mbrief_20261001", "art_other"):
        rig.store.with_new_id(lambda aid=aid: aid).put(rig.scope, rig.new(ARTICLE))
    first = rig.store.versions(rig.scope, "art_mbrief_20261001")[0].ref
    rig.store.with_new_id(lambda: "art_unused").put(
        rig.scope, dataclasses.replace(rig.new(ARTICLE + b"2"), parent=first)
    )
    assert rig.store.artifact_ids(rig.scope, "art_mbrief_") == ["art_mbrief_20260920", "art_mbrief_20261001"]
    assert rig.store.artifact_ids(rig.scope) == ["art_mbrief_20260920", "art_mbrief_20261001", "art_other"]
    other = dataclasses.replace(rig.scope, owner="u_someone_else")
    assert rig.store.artifact_ids(other, "art_mbrief_") == []
