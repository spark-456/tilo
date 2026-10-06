"""FR-AGT-02 / FR-MEM-06 (ADR-0018 T4 review follow-ups to #393):

- Text the store would refuse as invalid UTF-8 or blank (AR-04) is refused before the first put, so a sibling new
  version of an artifact is not left stored but unannounced.
- A `parent` is read once, as the store's own ref, and that ref is what the put gets: a runner's mapping that answers
  differently on a later read cannot swap in a version the world never recorded.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

import pytest
from agt_output_support import ARTICLE, RUN, created_ref, make_rig, outcome, run_units, unit_output


@pytest.mark.parametrize("bad", [b"\xff\xfe not utf-8", b" \n\t "], ids=["invalid_utf8", "whitespace_only"])
def test_FR_AGT_02_bad_text_after_a_new_version_is_refused_before_any_put(tmp_path, bad) -> None:
    def second(unit: Any, context: Any, events: Any) -> Any:
        return outcome([unit_output(b"# v2\n", parent=created_ref(events, "A_s0")), unit_output(bad)])

    ran = run_units(tmp_path, {"U1": outcome([unit_output(b"# v1\n")]), "U2": second}, depends={"U2": ["U1"]})

    assert ran.result.outcomes["U2"].success is False and ran.artifact_events_of("U2") == []
    x1 = created_ref(ran.events, "A_s0")
    held = [v.version for v in ran.rig.store.versions(ran.rig.scope, x1["artifact_id"])]
    assert held == [1], "nothing stored for the refused unit: the store's next version is still EV-15's"


class _Fickle(Mapping[str, Any]):
    """An artifact ref that names `first` on the first read of `artifact_id` and `then` on every later read."""

    def __init__(self, first: dict[str, Any], then: dict[str, Any]) -> None:
        self.first, self.then, self.reads = first, then, 0

    def __getitem__(self, key: str) -> Any:
        if key == "artifact_id":
            self.reads += 1
            return (self.first if self.reads == 1 else self.then)[key]
        return self.first[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.first)

    def __len__(self) -> int:
        return len(self.first)


def test_FR_AGT_02_a_parent_is_checked_once_and_the_put_gets_that_checked_ref(tmp_path) -> None:
    from tilo_memory.artifacts import NewVersion, Origin

    rig = make_rig()
    unannounced = rig.store.put(  # held in this Scope, never announced in the world
        rig.scope, NewVersion(media_type="text/markdown", content=ARTICLE, run_id=RUN, origin=Origin(kind="upload"))
    )

    def second(unit: Any, context: Any, events: Any) -> Any:
        parent = _Fickle(created_ref(events, "A_s0"), unannounced.ref)
        return outcome([unit_output(b"# v2\n", parent=parent)])

    ran = run_units(tmp_path, {"U1": outcome([unit_output(b"# v1\n")]), "U2": second}, depends={"U2": ["U1"]}, rig=rig)

    assert ran.result.outcomes["U2"].success is True
    (versioned,) = ran.of("artifact.versioned")
    x1 = created_ref(ran.events, "A_s0")
    assert versioned["data"]["artifact"] == {"artifact_id": x1["artifact_id"], "version": 2}
    assert [v.version for v in rig.store.versions(rig.scope, unannounced.ref["artifact_id"])] == [1]
