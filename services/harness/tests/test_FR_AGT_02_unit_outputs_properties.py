"""FR-AGT-02 / FR-MEM-06 property tests (ADR-0018 s5, s6): whatever a runner returns,

1. a unit is announced in full or not at all: either it succeeded and exactly one artifact event per output was
   written, each equal to its stored record, or it failed and no artifact event (and no handoff) was written;
2. `seq` is strictly increasing and gap-free and every event passes the validator, EV-15 included;
3. no event names a version the store does not hold with the hash the event carries (no stamp for a version never
   created, HR-1);
4. the unit's credits are on the first announced item only, so the world's meter is the unit's credits, once.
"""

from __future__ import annotations

import pytest
from agt_output_support import TEXT_TYPES, make_rig, outcome, run_in_scratch, sha, unit_output
from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st
from tilo_harness.validator import repo_validator

NO_SHRINK = (Phase.explicit, Phase.reuse, Phase.generate)  # a run of the executor is slow: report, do not shrink
MEDIA = (*TEXT_TYPES, "application/pdf", "image/svg+xml")  # the last two are never a unit's output
SIZES = (0, 1, 7, 64)

output_spec = st.tuples(st.sampled_from(MEDIA), st.sampled_from(SIZES), st.integers(0, 255))


def _content(size: int, salt: int) -> bytes:
    return bytes([65 + salt % 26]) * size + bytes([97 + salt % 26]) * (1 if size else 0)  # ASCII: valid text


def _valid(spec) -> bool:
    media, size, _ = spec
    return media in TEXT_TYPES and size > 0


@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture], phases=NO_SHRINK)
@given(
    specs=st.lists(output_spec, max_size=4),
    credits=st.sampled_from([0.0, 0.25, 1.5]),
    twin=st.booleans(),
)
def test_FR_AGT_02_a_unit_is_announced_in_full_or_not_at_all(specs, credits, twin) -> None:
    outputs = [unit_output(_content(size, salt), media) for media, size, salt in specs]
    script = {"U1": outcome(outputs, credits=credits), "U2": outcome([unit_output(b"neighbour")])}
    if twin:  # a second unit with the same bytes is its own version, never a reuse of U1's
        script["U3"] = outcome([unit_output(b"neighbour")])
    rig = make_rig()
    ran = run_in_scratch(script, rig=rig)

    all_valid = all(_valid(spec) for spec in specs)
    mine = ran.artifact_events_of("U1")
    if all_valid:
        assert ran.result.outcomes["U1"].success is True
        assert len(mine) == len(specs)
        for event, spec in zip(mine, specs, strict=True):
            ref = event["data"]["artifact"]
            record = rig.store.head(rig.scope, ref).record
            assert event["type"] == "artifact.created" and ref["version"] == 1
            assert event["data"] == {
                "artifact": ref,
                "content_sha256": record["content_sha256"],
                "media_type": record["media_type"],
                "size_bytes": record["size_bytes"],
            }
            assert record["content_sha256"] == sha(rig.store.read(rig.scope, ref))
        assert [e["credits"] for e in mine] == ([credits] + [0] * (len(specs) - 1) if specs else [])
    else:
        assert ran.result.outcomes["U1"].success is False
        assert mine == [] and ran.of("agent.handoff", actor=ran.workers["U1"]) == []

    assert ran.result.outcomes["U2"].success is True and len(ran.artifact_events_of("U2")) == 1
    events = ran.events
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    validator = repo_validator()
    assert {e["seq"]: validator.problems(e) for e in events if validator.problems(e)} == {}
    expected_credits = credits if (all_valid and specs) else 0
    assert sum(e["credits"] for e in events) == pytest.approx(expected_credits)

    for event in ran.of("artifact.created"):  # 3: every announced version is in the store with the event's hash
        head = rig.store.head(rig.scope, event["data"]["artifact"])
        assert head is not None and head.record["content_sha256"] == event["data"]["content_sha256"]
    created_ids = [e["data"]["artifact"]["artifact_id"] for e in ran.of("artifact.created")]
    assert len(set(created_ids)) == len(created_ids), "EV-15: no second created of a recorded id"
