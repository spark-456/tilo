"""FR-MEM-06 AR-07 with `NewVersion.screening_hint` (FR-MTG-02 / BQ-MTG02-3): a producer that screened its own input
in pieces (transcript ingest) may say `"flagged"`; the store takes `flagged` if its own verdict or the hint says so.
The hint can only RAISE the stored verdict: it never makes a version clean, never lowers a verdict, and any value other
than `"flagged"` is refused. A replay (same idempotency key) returns the stored version: the first bytes and the first
verdict win, a stored version is never edited."""

from __future__ import annotations

import dataclasses

import pytest
from _artifact_testlib import ARTICLE, FakeSafety, iso, make_rig
from tilo_memory.artifacts import ArtifactRefused


def _hinted(rig, hint, **kw):
    return dataclasses.replace(rig.new(ARTICLE, **kw), screening_hint=hint)


def test_FR_MEM_06_a_flagged_hint_raises_a_clean_verdict_to_flagged_with_a_screen_time():
    rig = make_rig("memory", None, safety=FakeSafety(flagged=False))
    stored = rig.store.put(rig.scope, _hinted(rig, "flagged"))
    assert stored.record["screening"] == "flagged"
    assert stored.record["screened_at"] == iso(rig.clock())  # as for a normal flagged verdict
    assert rig.store.head(rig.scope, stored.ref).record["screening"] == "flagged"


@pytest.mark.parametrize(
    "safety",
    [None, FakeSafety(error=RuntimeError("down")), FakeSafety(result={"flagged": "yes"})],
    ids=["no-screener", "screener-error", "malformed-verdict"],
)
def test_FR_MEM_06_a_flagged_hint_raises_unscreened_to_flagged_never_to_clean(safety):
    rig = make_rig("memory", None, safety=safety)
    plain = rig.store.put(rig.scope, rig.new(ARTICLE))
    assert plain.record["screening"] == "unscreened" and plain.record["screened_at"] is None
    hinted = rig.store.put(rig.scope, _hinted(rig, "flagged"))
    assert hinted.record["screening"] == "flagged" and hinted.record["screened_at"] is not None


def test_FR_MEM_06_a_flagged_verdict_stays_flagged_with_or_without_the_hint():
    rig = make_rig("memory", None, safety=FakeSafety(flagged=True))
    assert rig.store.put(rig.scope, rig.new(ARTICLE)).record["screening"] == "flagged"
    assert rig.store.put(rig.scope, _hinted(rig, "flagged")).record["screening"] == "flagged"
    assert rig.store.put(rig.scope, _hinted(rig, None)).record["screening"] == "flagged"


def test_FR_MEM_06_no_hint_leaves_every_verdict_as_the_screener_gave_it():
    clean = make_rig("memory", None, safety=FakeSafety(flagged=False))
    assert clean.store.put(clean.scope, _hinted(clean, None)).record["screening"] == "clean"
    bare = make_rig("memory", None, safety=None)
    assert bare.store.put(bare.scope, _hinted(bare, None)).record["screening"] == "unscreened"


@pytest.mark.parametrize("hint", ["clean", "unscreened", "FLAGGED", "flagged ", "", True, 1, ["flagged"]])
def test_FR_MEM_06_a_hint_other_than_flagged_is_refused_and_nothing_is_stored(hint):
    rig = make_rig("memory", None, safety=FakeSafety(flagged=False))
    with pytest.raises(ArtifactRefused):
        rig.store.put(rig.scope, _hinted(rig, hint))
    assert rig.blobs.inner.keys() == [] and rig.meta.inner.paths() == []


def test_FR_MEM_06_a_replay_returns_the_stored_version_whatever_the_second_hint_says():
    rig = make_rig("memory", None, safety=FakeSafety(flagged=False))
    first = rig.store.put(rig.scope, _hinted(rig, None, attempt=1))
    again = rig.store.put(rig.scope, _hinted(rig, "flagged", attempt=1))  # same key, same bytes, a hint this time
    assert again.ref == first.ref and again.record == first.record and again.record["screening"] == "clean"
    assert len(rig.store.versions(rig.scope, first.artifact_id)) == 1  # no second version, no edit of the first

    flagged = rig.store.put(rig.scope, _hinted(rig, "flagged", attempt=2))
    back = rig.store.put(rig.scope, _hinted(rig, None, attempt=2))  # the hint is not needed to keep it flagged
    assert back.ref == flagged.ref and back.record["screening"] == "flagged"


def test_FR_MEM_06_a_hint_on_a_new_version_does_not_flag_its_parent_or_the_next_version():
    rig = make_rig("memory", None, safety=FakeSafety(flagged=False))
    v1 = rig.store.put(rig.scope, rig.new(ARTICLE, attempt=1))
    v2 = rig.store.put(rig.scope, _hinted(rig, "flagged", attempt=2, parent=v1.ref))
    v3 = rig.store.put(rig.scope, rig.new(ARTICLE + b"more", attempt=3, parent=v2.ref))
    states = [rig.store.head(rig.scope, v.ref).record["screening"] for v in (v1, v2, v3)]
    assert states == ["clean", "flagged", "clean"]  # a verdict belongs to its own bytes
