"""FR-CON-10 follow-ups from the PR #183 reviews (issue #187, items 1, 3, 4, 5 and 9).

1. An anchored archive chain: given `archive_head`, a consistently rewritten archive, a forged
   tail or a truncated archive is refused with rule "archive".
3. The MF-06 redactor sees every string, ids included.
4. parents and inputs are deduplicated in linear time and capped before schema validation.
5. Artifact refs compare type-strictly: version True or 1.0 never matches version 1.
9. Malformed caller types are refused with rule "schema", never a raw TypeError.
"""

from __future__ import annotations

import time

import pytest
from _provenance_lib import (
    AGENT,
    DECK,
    DECK_BYTES,
    DECK_V1,
    OWNER,
    RUN,
    TABLE,
    WRITER,
    approval_resolved,
    artifact_created,
    fake_redact,
    fake_token,
    make_archive,
    read_payload,
    skill_loaded,
    transfer_out,
    ulid,
)

WEB_URL = "https://example.com/quarterly-report"
CELL_REF = "art_research_table@1#Sheet1!B2"
PERSON_AUTHZ = {"by": "person", "ref": OWNER, "at": "2026-09-29T09:40:00.000Z"}
ENTRIES = [
    ("tool_call", read_payload("web", WEB_URL, "Revenue grew 12% quarter over quarter.", tool="web_fetch")),
    ("tool_call", read_payload("cell", CELL_REF, "1200", tool="read_cell")),
    ("model_call", {"role": "writer", "profile": "flash-37", "prompt": "Draft slide 3.", "response": "ok"}),
]


def _scenario(tmp_path, entries=ENTRIES, **overrides):
    refs, records = make_archive(tmp_path / "archive", entries)
    kwargs = {
        "run_id": RUN,
        "artifact": dict(DECK),
        "content": DECK_BYTES,
        "parents": [dict(DECK_V1)],
        "agent": dict(AGENT),
        "inputs": [dict(TABLE)],
        "sources": [{"id": "src_report", "archive_ref": refs[0]}, {"id": "src_cell", "archive_ref": refs[1]}],
        "claims": [
            {
                "id": "cl_growth",
                "location": "slide3/cell:B2",
                "text": "Revenue grew 12% quarter over quarter.",
                "source_ids": ["src_report", "src_cell"],
                "verified": True,
            }
        ],
        "events": [
            skill_loaded(10, WRITER, "deck-writing", "0.1.0"),
            artifact_created(20, DECK),
            approval_resolved(30, PERSON_AUTHZ["at"]),
            transfer_out(31, DECK, PERSON_AUTHZ),
        ],
        "archive": records,
        "redact": fake_redact,
    }
    kwargs.update(overrides)
    return kwargs, refs, records


def _head(records):
    return records[-1]["seq"], records[-1]["hash"]


def _build(**kwargs):
    from tilo_connectors.provenance import build_manifest

    return build_manifest(**kwargs)


def _refused(rule, **kwargs):
    from tilo_connectors.provenance import ManifestRefused

    with pytest.raises(ManifestRefused) as info:
        _build(**kwargs)
    assert info.value.rule == rule, f"refused for {info.value.rule!r}, expected {rule!r}: {info.value}"
    return info.value


# ---------------------------------------------------------------------------
# Item 1: the chain is checked against an independently anchored head


def test_FR_CON_10_archive_head_that_matches_builds(tmp_path):
    kwargs, _refs, records = _scenario(tmp_path)
    assert _build(**kwargs, archive_head=_head(records))["sources"]


def test_FR_CON_10_consistently_rewritten_archive_is_refused_given_the_head(tmp_path):
    kwargs, _refs, records = _scenario(tmp_path)
    rewritten = [("tool_call", read_payload("web", WEB_URL, "Revenue grew 40%.", tool="web_fetch")), *ENTRIES[1:]]
    _r, forged = make_archive(tmp_path / "rewritten", rewritten)
    kwargs["archive"] = forged
    _build(**kwargs)  # the rewritten chain is internally consistent, so only the anchor can catch it
    _refused("archive", **kwargs, archive_head=_head(records))


def test_FR_CON_10_forged_tail_is_refused_given_the_head(tmp_path):
    kwargs, _refs, records = _scenario(tmp_path)
    extra = ("tool_call", read_payload("web", "https://evil.example/never-read", "made up", tool="web_fetch"))
    forged_refs, forged = make_archive(tmp_path / "forged", [*ENTRIES, extra])
    assert forged[: len(records)] == records
    kwargs["archive"] = forged
    kwargs["sources"].append({"id": "src_forged", "archive_ref": forged_refs[-1]})
    _build(**kwargs)
    _refused("archive", **kwargs, archive_head=_head(records))


def test_FR_CON_10_truncated_archive_is_refused_given_the_head(tmp_path):
    kwargs, _refs, records = _scenario(tmp_path)
    kwargs["archive"] = records[:-1]
    _build(**kwargs)
    _refused("archive", **kwargs, archive_head=_head(records))


@pytest.mark.parametrize("head", ["abc", (1,), ("1", "x"), (True, "x"), 7])
def test_FR_CON_10_malformed_archive_head_is_refused(tmp_path, head):
    kwargs, _refs, _records = _scenario(tmp_path)
    _refused("schema", **kwargs, archive_head=head)


# ---------------------------------------------------------------------------
# Item 4: linear dedupe and size caps before schema validation


def _cpu_seconds(fn):
    start = time.process_time()
    fn()
    return time.process_time() - start


def test_FR_CON_10_ten_thousand_parents_are_refused_fast(tmp_path):
    kwargs, _refs, _records = _scenario(tmp_path)
    kwargs["artifact"] = {"artifact_id": DECK["artifact_id"], "version": 20000}
    kwargs["parents"] = [{"artifact_id": DECK["artifact_id"], "version": v} for v in range(1, 10001)]
    assert _cpu_seconds(lambda: _refused("schema", **kwargs)) < 1.0


def test_FR_CON_10_ten_thousand_inputs_are_refused_fast(tmp_path):
    kwargs, _refs, _records = _scenario(tmp_path)
    kwargs["inputs"] = [dict(TABLE)] + [{"artifact_id": f"art_t{i}", "version": 1} for i in range(9999)]
    assert _cpu_seconds(lambda: _refused("schema", **kwargs)) < 1.0


def test_FR_CON_10_duplicate_input_version_is_refused_fast(tmp_path):
    kwargs, _refs, _records = _scenario(tmp_path)
    many = [{"artifact_id": f"art_t{i}", "version": 1} for i in range(4000)]
    kwargs["inputs"] = [dict(TABLE), *many, {"artifact_id": "art_t7", "version": 1, "label": "same version again"}]
    assert _cpu_seconds(lambda: _refused("schema", **kwargs)) < 1.0


def test_FR_CON_10_duplicate_parent_version_is_refused(tmp_path):
    kwargs, _refs, _records = _scenario(tmp_path, parents=[dict(DECK_V1), DECK_V1 | {"label": "again"}])
    _refused("schema", **kwargs)


def test_FR_CON_10_refs_at_the_caps_still_build(tmp_path):
    kwargs, _refs, _records = _scenario(tmp_path)
    kwargs["artifact"] = {"artifact_id": DECK["artifact_id"], "version": 1001}
    kwargs["parents"] = [{"artifact_id": DECK["artifact_id"], "version": v} for v in range(1, 1001)]
    kwargs["inputs"] = [dict(TABLE)] + [{"artifact_id": f"art_t{i}", "version": 1} for i in range(4999)]
    built = {}
    assert _cpu_seconds(lambda: built.update(_build(**kwargs))) < 5.0
    assert len(built["parents"]) == 1000
    assert len(built["inputs"]) == 5000


# ---------------------------------------------------------------------------
# Item 3: the redactor gets every string


@pytest.mark.parametrize(
    "flagged",
    [WRITER, "flash-37", "deck-writing", "0.1.0", OWNER, ulid(30), "src_report", "cl_growth", "art_research_table"],
    ids=["agent_id", "profile", "skill_id", "skill_version", "authz_ref", "event_id", "source_id", "claim_id", "input"],
)
def test_FR_CON_10_redactor_change_to_any_string_is_refused(tmp_path, flagged):
    kwargs, _refs, _records = _scenario(tmp_path, redact=lambda text: "[REDACTED]" if text == flagged else text)
    err = _refused("MF-06", **kwargs)
    assert flagged not in str(err)


def test_FR_CON_10_redactor_sees_the_model_role(tmp_path):
    seen: list[str] = []
    kwargs, _refs, _records = _scenario(tmp_path, agent=AGENT | {"model_role": "drafter"})
    _build(**kwargs | {"redact": lambda text: seen.append(text) or text})
    assert "drafter" in seen


@pytest.mark.parametrize("field", ["agent", "inputs"])
def test_FR_CON_10_token_in_an_id_is_refused_without_echoing_it(tmp_path, field):
    token = fake_token()
    kwargs, _refs, _records = _scenario(tmp_path)
    if field == "agent":
        kwargs["agent"] = AGENT | {"agent_id": "A_" + token}
    else:
        kwargs["inputs"].append({"artifact_id": "art_" + token, "version": 1})
    err = _refused("MF-06", **kwargs)
    assert token not in str(err)


# ---------------------------------------------------------------------------
# Item 5: type-strict artifact ref comparison


def test_FR_CON_10_float_input_version_does_not_admit_a_cell_source(tmp_path):
    kwargs, _refs, _records = _scenario(tmp_path, inputs=[{"artifact_id": TABLE["artifact_id"], "version": 1.0}])
    _refused("schema", **kwargs)


@pytest.mark.parametrize(
    ("artifact", "sent_version"), [(DECK, 2.0), (DECK_V1, True), (DECK_V1, 1.0)], ids=["2.0", "True", "1.0"]
)
def test_FR_CON_10_send_of_a_look_alike_version_does_not_authorise(tmp_path, artifact, sent_version):
    sent = {"artifact_id": artifact["artifact_id"], "version": sent_version}
    kwargs, _refs, _records = _scenario(tmp_path, artifact=dict(artifact), parents=[])
    kwargs["events"] = [*kwargs["events"][:3], transfer_out(31, sent, PERSON_AUTHZ)]
    assert _build(**kwargs)["authz"] is None


# ---------------------------------------------------------------------------
# Item 9: malformed caller types are schema refusals


def _malformed(kwargs, case):
    if case == "unhashable_input_id":
        kwargs["inputs"] = [{"artifact_id": ["art_x"], "version": 1}]
    elif case == "unhashable_input_version":
        kwargs["inputs"] = [{"artifact_id": "art_x", "version": [1]}]
    elif case == "non_mapping_input":
        kwargs["inputs"] = ["art_x@1"]
    elif case == "non_mapping_artifact":
        kwargs["artifact"] = "art_quarterly_deck@2"
    elif case == "non_mapping_authz":
        kwargs["events"][3]["authz"] = ["person", OWNER]
    elif case == "non_dict_event_data":
        kwargs["events"][0]["data"] = "deck-writing"
    elif case == "non_mapping_event":
        kwargs["events"].append("not an event")
    elif case == "non_mapping_source":
        kwargs["sources"].append("src_extra")
    elif case == "non_mapping_claim":
        kwargs["claims"].append(1)
    elif case == "non_mapping_agent":
        kwargs["agent"] = WRITER
    elif case == "str_content":
        kwargs["content"] = "deck text"


MALFORMED = [
    "unhashable_input_id",
    "unhashable_input_version",
    "non_mapping_input",
    "non_mapping_artifact",
    "non_mapping_authz",
    "non_dict_event_data",
    "non_mapping_event",
    "non_mapping_source",
    "non_mapping_claim",
    "non_mapping_agent",
    "str_content",
]


@pytest.mark.parametrize("case", MALFORMED)
def test_FR_CON_10_malformed_caller_types_are_schema_refusals(tmp_path, case):
    kwargs, _refs, _records = _scenario(tmp_path)
    _malformed(kwargs, case)
    _refused("schema", **kwargs)
