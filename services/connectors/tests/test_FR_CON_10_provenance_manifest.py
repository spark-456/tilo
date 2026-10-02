"""FR-CON-10: provenance manifest on every deliverable (PRD 12.4, 12.6, 13.2, 13.3, 16.1-16.2).

Acceptance test (PRD 12.6): "Each deliverable links to sources, skills, agents and approvals".
Contract: contracts/manifest.schema.json and rules MF-01 to MF-06 (contracts/manifest.rules.md),
BQ-59 for refs. Public API pinned in API_FR_CON_10.md. Every test fails today with
ModuleNotFoundError: tilo_connectors.provenance.

Inputs are what a run leaves behind: the raw archive's tool-call records (a real
tilo_archive.RunArchive in a temp dir), the run's events (contract fixtures re-pointed at this
run), and the deliverable's bytes. Nothing touches the network or a real account.
"""

from __future__ import annotations

import copy
import json

import pytest
from _provenance_lib import (
    AGENT,
    DECK,
    DECK_BYTES,
    DECK_V1,
    OTHER_AGENT,
    OTHER_RUN,
    OWNER,
    POLICY,
    RUN,
    TABLE,
    WRITER,
    all_strings,
    approval_resolved,
    artifact_created,
    artifact_reviewed,
    canonical,
    fake_redact,
    fake_token,
    fingerprint_of,
    make_archive,
    manifest_schema_errors,
    read_payload,
    sha256_hex,
    skill_loaded,
    transfer_out,
    ulid,
)
from hypothesis import given, settings
from hypothesis import strategies as st

WEB_URL = "https://example.com/quarterly-report"
DRIVE_REF = "google_drive:1AbcDEF_xyz-9"
CELL_REF = "art_research_table@1#Sheet1!B2"
WEB_TEXT = "Quarterly report: revenue grew 12% quarter over quarter."
DRIVE_TEXT = "Board notes: approve the Q3 hiring plan."
CELL_TEXT = "1200"
PERSON_AUTHZ = {"by": "person", "ref": OWNER, "at": "2026-09-29T09:40:00.000Z"}
POLICY_AUTHZ = {"by": "policy", "ref": POLICY, "at": "2026-09-29T09:40:00.000Z"}


def _provenance():
    # Imported per test so collection succeeds and each test fails on its own with the reason.
    from tilo_connectors import provenance

    return provenance


def _scenario(tmp_path, *, entries=None, events=None, sources=None, claims=None, **overrides):
    """A deck (v2 of art_quarterly_deck) written by A_writer1 from a web page, a Drive file and
    a research-table cell, verified, approved by the owner and saved to Drive by the outbox."""
    if entries is None:
        entries = [
            ("tool_call", read_payload("web", WEB_URL, WEB_TEXT, tool="web_fetch")),
            ("tool_call", read_payload("connector", DRIVE_REF, DRIVE_TEXT, tool="read_file")),
            ("tool_call", read_payload("cell", CELL_REF, CELL_TEXT, tool="read_cell")),
            ("model_call", {"role": "writer", "profile": "flash-37", "prompt": "Draft slide 3.", "response": "ok"}),
        ]
    refs, records = make_archive(tmp_path / "archive", entries)
    if events is None:
        events = [
            skill_loaded(10, WRITER, "deck-writing", "0.1.0"),
            skill_loaded(11, OTHER_AGENT, "web-research", "2.0.0"),
            artifact_created(20, DECK),
            artifact_reviewed(21, DECK),
            approval_resolved(30, PERSON_AUTHZ["at"]),
            transfer_out(31, DECK, PERSON_AUTHZ),
        ]
    if sources is None:
        sources = [
            {"id": "src_report", "archive_ref": refs[0]},
            {"id": "src_board", "archive_ref": refs[1]},
            {"id": "src_cell", "archive_ref": refs[2]},
        ]
    if claims is None:
        claims = [
            {
                "id": "cl_growth",
                "location": "slide3/cell:B2",
                "text": "Revenue grew 12% quarter over quarter.",
                "source_ids": ["src_report", "src_cell"],
                "verified": True,
            },
            {
                "id": "cl_board",
                "location": "slide4",
                "text": "The board approved the Q3 hiring plan.",
                "source_ids": ["src_board"],
                "verified": True,
            },
            {"id": "cl_outlook", "location": "slide5", "text": "Q4 looks steady.", "source_ids": [], "verified": False},
        ]
    kwargs = {
        "run_id": RUN,
        "artifact": dict(DECK),
        "content": DECK_BYTES,
        "parents": [dict(DECK_V1)],
        "agent": dict(AGENT),
        "inputs": [dict(TABLE)],
        "sources": sources,
        "claims": claims,
        "events": events,
        "archive": records,
        "redact": fake_redact,
    }
    kwargs.update(overrides)
    return kwargs, refs, records


def _build(**kwargs):
    return _provenance().build_manifest(**kwargs)


def _refused(rule: str | None = None, **kwargs):
    provenance = _provenance()
    with pytest.raises(provenance.ManifestRefused) as info:
        provenance.build_manifest(**kwargs)
    err = info.value
    assert isinstance(err, ValueError)
    if rule is not None:
        got = getattr(err, "rule", None)
        assert got == rule, f"refused for {got!r}, expected {rule!r}: {err}"
    return err


def _source(manifest, source_id):
    found = [s for s in manifest["sources"] if s["id"] == source_id]
    assert len(found) == 1, f"source {source_id!r} appears {len(found)} times in {manifest['sources']}"
    return found[0]


# ---------------------------------------------------------------------------
# The acceptance test: sources, skills, agents and approvals (PRD 12.6, 12.4, 13.3)


def test_FR_CON_10_deliverable_links_sources_skills_agents_and_approvals(tmp_path):
    kwargs, _refs, _records = _scenario(tmp_path)
    manifest = _build(**kwargs)

    assert manifest["artifact"] == DECK
    # agents: the producing agent and its role, model role and profile (never a model id, MF-05)
    produced_by = manifest["produced_by"]
    assert produced_by["agent_id"] == WRITER
    assert produced_by["role"] == "writer"
    assert produced_by["model_role"] == "writer"
    assert produced_by["profile"] == "flash-37"
    # skills: the version the run pinned for that agent (skill.loaded, MF-05, FR-AGT-03)
    assert produced_by["skill"] == {"id": "deck-writing", "version": "0.1.0"}
    # sources: every source the deliverable used
    assert {s["id"] for s in manifest["sources"]} == {"src_report", "src_board", "src_cell"}
    # approvals: the person who authorised the send (MF-04), and the approval and send events
    assert manifest["authz"] == PERSON_AUTHZ
    assert ulid(30) in manifest["events"], "the approval.resolved event is not linked"
    assert ulid(31) in manifest["events"], "the data.transfer that carried the deck out is not linked"
    assert manifest["parents"] == [DECK_V1]
    assert manifest["inputs"] == [TABLE]


def test_FR_CON_10_manifest_validates_against_contract(tmp_path):
    kwargs, _refs, _records = _scenario(tmp_path)
    manifest = _build(**kwargs)

    assert manifest_schema_errors(manifest) == []
    from tilo_contracts import Manifest

    assert Manifest.model_validate(manifest).model_dump(mode="json", exclude_none=False)["artifact"]["version"] == 2
    json.dumps(manifest, allow_nan=False)  # plain JSON, ready to store and export (PRD 13.3)


def test_FR_CON_10_content_sha256_is_hash_of_stored_bytes(tmp_path):
    kwargs, _refs, _records = _scenario(tmp_path)
    manifest = _build(**kwargs)
    assert manifest["content_sha256"] == sha256_hex(DECK_BYTES)  # MF-02, PRD 13.2


# ---------------------------------------------------------------------------
# Every cited source is in the manifest with a stable ref and a hash of the archived content


def test_FR_CON_10_every_cited_source_appears_with_stable_ref(tmp_path):
    kwargs, _refs, _records = _scenario(tmp_path)
    manifest = _build(**kwargs)

    source_ids = {s["id"] for s in manifest["sources"]}
    for claim in manifest["claims"]:
        assert set(claim["source_ids"]) <= source_ids, f"{claim['id']} cites a source the manifest lacks"
    assert _source(manifest, "src_report")["kind"] == "web"
    assert _source(manifest, "src_report")["ref"] == WEB_URL
    assert _source(manifest, "src_board")["kind"] == "connector"
    assert _source(manifest, "src_board")["ref"] == DRIVE_REF
    assert _source(manifest, "src_cell")["kind"] == "cell"
    assert _source(manifest, "src_cell")["ref"] == CELL_REF

    # Stable: a second run that read the same material gets the same refs and fingerprints.
    again, _r, _rec = _scenario(tmp_path / "second")
    second = _build(**again)
    assert [(s["id"], s["ref"], s["fingerprint"]) for s in second["sources"]] == [
        (s["id"], s["ref"], s["fingerprint"]) for s in manifest["sources"]
    ]


def test_FR_CON_10_fingerprints_match_archived_raw_content(tmp_path):
    kwargs, refs, records = _scenario(tmp_path)
    manifest = _build(**kwargs)

    # Re-read the archive from disk, independent of what the builder was handed.
    from tilo_archive import LocalDirStore, RunArchive

    stored = RunArchive(LocalDirStore(tmp_path / "archive"), org_id="org_acme", run_id=RUN, redactor=lambda p: p)
    by_seq = {r["seq"]: r for r in stored.records()}
    for source_id, ref in zip(["src_report", "src_board", "src_cell"], refs[:3], strict=True):
        record = by_seq[int(ref.split("/")[1])]
        source = _source(manifest, source_id)
        assert source["fingerprint"] == fingerprint_of(record["payload"]["content"])
        assert source["fetched_at"] == record["ts"]


def test_FR_CON_10_claim_citing_unlisted_source_is_refused(tmp_path):
    kwargs, _refs, _records = _scenario(tmp_path)
    kwargs["claims"][0]["source_ids"] = ["src_report", "src_ghost"]
    _refused("MF-01", **kwargs)


def test_FR_CON_10_duplicate_source_ids_are_refused(tmp_path):
    kwargs, refs, _records = _scenario(tmp_path)
    kwargs["sources"].append({"id": "src_report", "archive_ref": refs[1]})
    _refused("MF-01", **kwargs)


# ---------------------------------------------------------------------------
# No source the run never read


@pytest.mark.parametrize(
    "bad_ref",
    [
        f"{RUN}/99",  # no such record in this run's archive
        f"{RUN}/4",  # a model call, not a read
        f"{OTHER_RUN}/1",  # another run's record
    ],
    ids=["missing_record", "model_call_record", "other_run"],
)
def test_FR_CON_10_source_the_run_never_read_is_refused(tmp_path, bad_ref):
    kwargs, _refs, _records = _scenario(tmp_path)
    make_archive(tmp_path / "other", [("tool_call", read_payload("web", WEB_URL, WEB_TEXT))], run_id=OTHER_RUN)
    kwargs["sources"].append({"id": "src_invented", "archive_ref": bad_ref})
    _refused(**kwargs)


def test_FR_CON_10_another_runs_archive_records_are_refused(tmp_path):
    kwargs, _refs, records = _scenario(tmp_path)
    other_refs, other_records = make_archive(
        tmp_path / "other", [("tool_call", read_payload("web", WEB_URL, WEB_TEXT))], run_id=OTHER_RUN
    )
    kwargs["archive"] = records + other_records
    kwargs["sources"].append({"id": "src_foreign", "archive_ref": other_refs[0]})
    _refused(**kwargs)


def test_FR_CON_10_tampered_archive_record_is_refused(tmp_path):
    # PRD 13.2 / FR-MEM-04: an edited record breaks the chain, so no fingerprint can be trusted.
    kwargs, _refs, records = _scenario(tmp_path)
    tampered = copy.deepcopy(records)
    tampered[0]["payload"]["content"] = "Quarterly report: revenue grew 40% quarter over quarter."
    kwargs["archive"] = tampered
    _refused(**kwargs)


def test_FR_CON_10_cell_source_must_name_a_version_in_inputs(tmp_path):
    kwargs, _refs, _records = _scenario(tmp_path, inputs=[])
    _refused("MF-03", **kwargs)


def test_FR_CON_10_parent_must_be_an_earlier_version_of_the_same_artifact(tmp_path):
    kwargs, _refs, _records = _scenario(tmp_path, parents=[dict(TABLE)])
    _refused("MF-02", **kwargs)


# ---------------------------------------------------------------------------
# Events and approvals (MF-04, HR-7)


def test_FR_CON_10_event_from_another_run_is_refused(tmp_path):
    kwargs, _refs, _records = _scenario(tmp_path)
    kwargs["events"].append(artifact_reviewed(40, DECK) | {"run_id": OTHER_RUN})
    _refused("MF-04", **kwargs)


def test_FR_CON_10_events_listed_oldest_first(tmp_path):
    kwargs, _refs, _records = _scenario(tmp_path)
    kwargs["events"] = list(reversed(kwargs["events"]))
    manifest = _build(**kwargs)
    assert manifest["events"] == [ulid(n) for n in (10, 11, 20, 21, 30, 31)]


def test_FR_CON_10_policy_authorised_delivery_links_the_policy(tmp_path):
    # HR-7: a policy-authorised action is told apart from a person's approval, and links to it.
    events = [
        skill_loaded(10, WRITER, "deck-writing", "0.1.0"),
        artifact_created(20, DECK),
        transfer_out(31, DECK, POLICY_AUTHZ),
    ]
    kwargs, _refs, _records = _scenario(tmp_path, events=events)
    manifest = _build(**kwargs)
    assert manifest["authz"] == POLICY_AUTHZ
    assert manifest["authz"]["by"] == "policy"


def test_FR_CON_10_version_that_never_left_tilo_has_null_authz(tmp_path):
    events = [
        skill_loaded(10, WRITER, "deck-writing", "0.1.0"),
        artifact_created(20, DECK),
        artifact_reviewed(21, DECK),
    ]
    kwargs, _refs, _records = _scenario(tmp_path, events=events)
    assert _build(**kwargs)["authz"] is None  # MF-04


def test_FR_CON_10_send_of_another_version_does_not_authorise_this_one(tmp_path):
    events = [
        skill_loaded(10, WRITER, "deck-writing", "0.1.0"),
        artifact_created(20, DECK),
        transfer_out(31, DECK_V1, PERSON_AUTHZ),
    ]
    kwargs, _refs, _records = _scenario(tmp_path, events=events)
    assert _build(**kwargs)["authz"] is None


def test_FR_CON_10_skill_is_the_producing_agents_pinned_version(tmp_path):
    events = [skill_loaded(11, OTHER_AGENT, "web-research", "2.0.0"), artifact_created(20, DECK)]
    kwargs, _refs, _records = _scenario(tmp_path, events=events)
    # Only another agent loaded a skill: the writer had none, so skill is null (schema producer).
    assert _build(**kwargs)["produced_by"]["skill"] is None


@pytest.mark.parametrize(
    "agent_patch",
    # A model-id-shaped profile, assembled so the PL-01 lint never sees a model id in this file.
    [{"role": "intern"}, {"profile": "gem" + "ini-2.5-flash"}, {"agent_id": "writer1"}],
    ids=["unknown_role", "model_id_as_profile", "bad_agent_id"],
)
def test_FR_CON_10_manifest_that_breaks_the_contract_is_refused(tmp_path, agent_patch):
    kwargs, _refs, _records = _scenario(tmp_path, agent=AGENT | agent_patch)
    _refused("schema", **kwargs)


# ---------------------------------------------------------------------------
# Sensitive values never copied into the manifest (PRD 16.1 rule 4, 16.2; MF-03, MF-06)


def test_FR_CON_10_source_content_is_never_copied_into_the_manifest(tmp_path):
    token = fake_token()
    body = f"Hi Priya, the Drive export password reset link is below. Use key {token} for the API."
    entries = [
        ("tool_call", read_payload("web", WEB_URL, WEB_TEXT)),
        ("tool_call", read_payload("connector", DRIVE_REF, body, tool="read_file")),
        ("tool_call", read_payload("cell", CELL_REF, CELL_TEXT)),
    ]
    kwargs, _refs, _records = _scenario(tmp_path, entries=entries)
    manifest = _build(**kwargs)
    text = canonical(manifest)
    assert token not in text
    assert "Priya" not in text
    assert WEB_TEXT not in text
    assert _source(manifest, "src_board")["fingerprint"] == fingerprint_of(body)


@pytest.mark.parametrize(
    "fetched",
    [
        "https://example.com/quarterly-report?access_token={t}",
        "https://example.com/quarterly-report#access_token={t}",
        "https://{t}:x@example.com/quarterly-report",
        "https://example.com/quarterly-report;access_token={t}",
    ],
    ids=["query", "fragment", "user_info", "path_parameter"],
)
def test_FR_CON_10_web_ref_is_recorded_without_credentials(tmp_path, fetched):
    # MF-03, BQ-59: the URL it was fetched from, without user info, query, fragment or path params.
    token = fake_token()
    url = fetched.format(t=token)
    entries = [
        ("tool_call", read_payload("web", url, WEB_TEXT)),
        ("tool_call", read_payload("connector", DRIVE_REF, DRIVE_TEXT)),
        ("tool_call", read_payload("cell", CELL_REF, CELL_TEXT)),
    ]
    kwargs, _refs, _records = _scenario(tmp_path, entries=entries)
    manifest = _build(**kwargs)
    assert _source(manifest, "src_report")["ref"] == WEB_URL
    assert token not in canonical(manifest)
    assert manifest_schema_errors(manifest) == []


def test_FR_CON_10_secret_in_a_claim_is_refused_without_echoing_it(tmp_path):
    token = fake_token()
    kwargs, _refs, _records = _scenario(tmp_path)
    kwargs["claims"][2]["text"] = f"Use {token} to reach the dashboard."
    err = _refused("MF-06", **kwargs)
    assert token not in str(err)
    assert token not in repr(err.args)


def test_FR_CON_10_bare_token_file_name_source_is_refused(tmp_path):
    # MF-06: a bare token passes the schema as a file name; the redactor must catch it.
    token = fake_token()
    entries = [
        ("tool_call", read_payload("web", WEB_URL, WEB_TEXT)),
        ("tool_call", read_payload("file", f"{token}.csv", "a,b\n1,2\n", tool="read_upload")),
        ("tool_call", read_payload("cell", CELL_REF, CELL_TEXT)),
    ]
    kwargs, _refs, _records = _scenario(tmp_path, entries=entries)
    err = _refused("MF-06", **kwargs)
    assert token not in str(err)


def test_FR_CON_10_redactor_checks_every_string_in_the_manifest(tmp_path):
    seen: list[str] = []

    def recording_redact(text: str) -> str:
        seen.append(text)
        return fake_redact(text)

    kwargs, _refs, _records = _scenario(tmp_path, redact=recording_redact)
    manifest = _build(**kwargs)
    for source in manifest["sources"]:
        assert source["ref"] in seen
    for claim in manifest["claims"]:
        assert claim["location"] in seen
        assert claim["text"] in seen


# ---------------------------------------------------------------------------
# Deterministic: same inputs, same manifest


def test_FR_CON_10_same_inputs_give_identical_manifest(tmp_path):
    kwargs, _refs, _records = _scenario(tmp_path / "a")
    snapshot = copy.deepcopy({k: v for k, v in kwargs.items() if k != "redact"})
    first = _build(**kwargs)
    assert {k: v for k, v in kwargs.items() if k != "redact"} == snapshot, "build_manifest mutated its inputs"
    second = _build(**copy.deepcopy(kwargs))
    other_dir, _r, _rec = _scenario(tmp_path / "b")
    third = _build(**other_dir)
    assert canonical(first) == canonical(second) == canonical(third)
    assert all(isinstance(s, str) for s in all_strings(first))


@pytest.fixture(scope="module")
def fixed_scenario(tmp_path_factory):
    kwargs, _refs, _records = _scenario(tmp_path_factory.mktemp("fr_con_10_property"))
    return kwargs


@settings(max_examples=40, deadline=None)
@given(data=st.data())
def test_FR_CON_10_input_order_never_changes_the_manifest(fixed_scenario, data):
    # Property: events, sources, claims and each claim's source_ids in any order give the same
    # manifest (sources and claims sorted by id, events by seq; see API_FR_CON_10.md).
    kwargs = fixed_scenario
    expected = canonical(_build(**copy.deepcopy(kwargs)))
    shuffled = copy.deepcopy(kwargs)
    shuffled["events"] = data.draw(st.permutations(shuffled["events"]))
    shuffled["sources"] = data.draw(st.permutations(shuffled["sources"]))
    claims = data.draw(st.permutations(shuffled["claims"]))
    shuffled["claims"] = [c | {"source_ids": data.draw(st.permutations(c["source_ids"]))} for c in claims]
    assert canonical(_build(**shuffled)) == expected
