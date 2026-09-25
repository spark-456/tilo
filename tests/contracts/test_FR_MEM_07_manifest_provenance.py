"""FR-MEM-07 (PRD 13.2, 13.3, 13.5, 15.2; GitHub issue #5, `spark-456/tilo`, ticket CC-SH).

PRD 13.3: "A provenance graph links every artifact to the agent, skill version, model profile,
inputs and sources that produced it, the events that caused it, and the person or policy that
authorised it... Exports carry a provenance manifest (JSON) so the trail survives outside
Tilo." PRD 13.5 acceptance test: "Every number in an eval deck traces to a source cell."
PRD 15.2: `manifest.schema.json` describes the provenance manifest, frozen 1 Oct -- not in
`contracts/` yet.

Issue #5 lists the fields SH needs, verbatim:
    v: "1.0"
    artifact: artifact_ref (id and version)
    content_sha256: 64 hex characters
    parents: [artifact_ref] (version parents, FR-MEM-06)
    produced_by: {agent_id, role, skill: {id, version} | null, model_role | null, profile | null}
    inputs: [artifact_ref]
    sources: [{id, kind: web | file | connector | cell | artifact, ref, fingerprint, fetched_at}]
    claims: [{id, location (slide/page/cell/paragraph path), text (<= 280), source_ids: [id],
              verified: bool}]
    events: [ulid] (the events that caused it)
    authz: the authz shape or null

Test-writer split: `contracts/manifest.schema.json` does not exist yet on this branch, so every
test here must fail for that reason.
"""

from __future__ import annotations

import json
import re

import pytest
from _cc_sh_lib import list_cc_sh_fixtures, sample_manifest
from _lib import errors_for, load_json, load_schema
from test_FR_WLD_02_contracts_check_drift import _copy_runnable_repo, _run_contracts_check

CONTRACTS_PY_SRC = "packages/contracts-py/src"
CONTRACTS_TS_SRC = "packages/contracts-ts/src"


def test_FR_MEM_07_manifest_schema_exists(repo_root):
    schema = load_schema(repo_root, "manifest")
    assert schema.get("title") == "Manifest", (
        f"FR-MEM-07: contracts/manifest.schema.json title should be 'Manifest', got {schema.get('title')!r}"
    )


def test_FR_MEM_07_minimal_sample_manifest_is_valid(repo_root, registry):
    schema = load_schema(repo_root, "manifest")
    instance = sample_manifest()
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-MEM-07: a well-formed manifest should validate, got: {[e.message for e in errors][:5]}"


@pytest.mark.parametrize(
    "field",
    ["v", "artifact", "content_sha256", "parents", "produced_by", "inputs", "sources", "claims", "events", "authz"],
)
def test_FR_MEM_07_manifest_missing_required_field_is_invalid(repo_root, registry, field):
    schema = load_schema(repo_root, "manifest")
    instance = sample_manifest()
    del instance[field]
    errors = errors_for(schema, instance, registry)
    assert errors, f"FR-MEM-07: a manifest missing {field!r} must be invalid (issue #5)"


def test_FR_MEM_07_v_is_const_1_0(repo_root, registry):
    schema = load_schema(repo_root, "manifest")
    instance = sample_manifest(v="1.1")
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-MEM-07: manifest.v must be the literal '1.0' (issue #5)"


def test_FR_MEM_07_content_sha256_must_be_64_hex_chars(repo_root, registry):
    schema = load_schema(repo_root, "manifest")
    for bad in ("a" * 63, "a" * 65, "g" * 64, "A" * 64):
        instance = sample_manifest(content_sha256=bad)
        errors = errors_for(schema, instance, registry)
        assert errors, f"FR-MEM-07: content_sha256={bad!r} must be invalid (issue #5: 64 hex characters)"
    instance = sample_manifest(content_sha256="0123456789abcdef" * 4)
    errors = errors_for(schema, instance, registry)
    assert not errors, (
        f"FR-MEM-07: a well-formed 64-hex content_sha256 should validate, got: {[e.message for e in errors][:5]}"
    )


def test_FR_MEM_07_artifact_ref_shape_requires_artifact_id_and_version(repo_root, registry):
    schema = load_schema(repo_root, "manifest")
    for field in ("artifact_id", "version"):
        instance = sample_manifest()
        del instance["artifact"][field]
        errors = errors_for(schema, instance, registry)
        assert errors, f"FR-MEM-07: manifest.artifact missing {field!r} must be invalid"


def test_FR_MEM_07_parents_and_inputs_are_arrays_of_artifact_refs(repo_root, registry):
    schema = load_schema(repo_root, "manifest")
    instance = sample_manifest(parents=[{"artifact_id": "not_an_id", "version": 1}])
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-MEM-07: manifest.parents entries must be well-formed artifact_refs"


def test_FR_MEM_07_parents_may_be_empty_for_a_first_version(repo_root, registry):
    """FR-MEM-06: a version-1 artifact has no version parents."""
    schema = load_schema(repo_root, "manifest")
    instance = sample_manifest(parents=[])
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-MEM-07: manifest.parents: [] should validate, got: {[e.message for e in errors][:5]}"


def test_FR_MEM_07_produced_by_requires_agent_id_and_role(repo_root, registry):
    schema = load_schema(repo_root, "manifest")
    for field in ("agent_id", "role"):
        instance = sample_manifest()
        del instance["produced_by"][field]
        errors = errors_for(schema, instance, registry)
        assert errors, f"FR-MEM-07: manifest.produced_by missing {field!r} must be invalid"


def test_FR_MEM_07_produced_by_role_uses_the_common_agent_role_enum(repo_root, registry):
    schema = load_schema(repo_root, "manifest")
    instance = sample_manifest()
    instance["produced_by"]["role"] = "intern"
    errors = errors_for(schema, instance, registry)
    msg = "FR-MEM-07: produced_by.role must be a PRD 8.1 agent role (director/lead/specialist/verifier/writer/narrator)"
    assert errors, msg


def test_FR_MEM_07_produced_by_skill_may_be_null(repo_root, registry):
    """Issue #5: produced_by.skill is '{id, version} | null' -- not every artifact comes from
    a skill-loaded agent."""
    schema = load_schema(repo_root, "manifest")
    instance = sample_manifest()
    instance["produced_by"]["skill"] = None
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-MEM-07: produced_by.skill: null should validate, got: {[e.message for e in errors][:5]}"


def test_FR_MEM_07_produced_by_model_role_and_profile_may_be_null(repo_root, registry):
    schema = load_schema(repo_root, "manifest")
    instance = sample_manifest()
    instance["produced_by"]["model_role"] = None
    instance["produced_by"]["profile"] = None
    errors = errors_for(schema, instance, registry)
    assert not errors, (
        f"FR-MEM-07: produced_by.model_role and .profile: null should validate, got: {[e.message for e in errors][:5]}"
    )


def test_FR_MEM_07_source_kind_is_closed_enum(repo_root, registry):
    """Issue #5: sources[].kind is 'web | file | connector | cell | artifact'."""
    schema = load_schema(repo_root, "manifest")
    for kind in ("web", "file", "connector", "cell", "artifact"):
        instance = sample_manifest()
        instance["sources"][0]["kind"] = kind
        errors = errors_for(schema, instance, registry)
        assert not errors, f"FR-MEM-07: source kind={kind!r} should validate, got: {[e.message for e in errors][:5]}"
    instance = sample_manifest()
    instance["sources"][0]["kind"] = "database"
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-MEM-07: source kind='database' is outside the closed set and must be invalid"


def test_FR_MEM_07_source_requires_every_field(repo_root, registry):
    schema = load_schema(repo_root, "manifest")
    for field in ("id", "kind", "ref", "fingerprint", "fetched_at"):
        instance = sample_manifest()
        del instance["sources"][0][field]
        errors = errors_for(schema, instance, registry)
        assert errors, f"FR-MEM-07: a source missing {field!r} must be invalid"


def test_FR_MEM_07_claim_text_max_280_chars(repo_root, registry):
    """PRD 13.3 'Why is this here?' resolves a claim to its sources -- the claim text itself is
    bounded (issue #5: text (<= 280))."""
    schema = load_schema(repo_root, "manifest")
    instance = sample_manifest()
    instance["claims"][0]["text"] = "x" * 281
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-MEM-07: claim text over 280 characters must be invalid"
    instance = sample_manifest()
    instance["claims"][0]["text"] = "x" * 280
    errors = errors_for(schema, instance, registry)
    assert not errors, (
        f"FR-MEM-07: claim text of exactly 280 characters should validate, got: {[e.message for e in errors][:5]}"
    )


def test_FR_MEM_07_claim_requires_source_ids_and_verified(repo_root, registry):
    schema = load_schema(repo_root, "manifest")
    for field in ("id", "location", "text", "source_ids", "verified"):
        instance = sample_manifest()
        del instance["claims"][0][field]
        errors = errors_for(schema, instance, registry)
        assert errors, f"FR-MEM-07: a claim missing {field!r} must be invalid"


def test_FR_MEM_07_claim_verified_must_be_boolean(repo_root, registry):
    schema = load_schema(repo_root, "manifest")
    instance = sample_manifest()
    instance["claims"][0]["verified"] = "yes"
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-MEM-07: claim.verified must be a boolean, not a string"


def test_FR_MEM_07_events_is_an_array_of_ulids(repo_root, registry):
    schema = load_schema(repo_root, "manifest")
    instance = sample_manifest(events=["not-a-ulid"])
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-MEM-07: manifest.events entries must be ULIDs (the events that caused this artifact)"


def test_FR_MEM_07_events_may_be_empty(repo_root, registry):
    schema = load_schema(repo_root, "manifest")
    instance = sample_manifest(events=[])
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-MEM-07: manifest.events: [] should validate, got: {[e.message for e in errors][:5]}"


def test_FR_MEM_07_authz_may_be_null(repo_root, registry):
    schema = load_schema(repo_root, "manifest")
    instance = sample_manifest(authz=None)
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-MEM-07: manifest.authz: null should validate, got: {[e.message for e in errors][:5]}"


def test_FR_MEM_07_authz_rejects_a_model_authoriser(repo_root, registry):
    schema = load_schema(repo_root, "manifest")
    instance = sample_manifest(authz={"by": "the_model_itself", "ref": "x", "at": "2026-09-29T09:30:00.000Z"})
    errors = errors_for(schema, instance, registry)
    assert errors, (
        "FR-MEM-07: manifest.authz must use the common authz shape (BQ-01), which never authorises via a model"
    )


def test_FR_MEM_07_manifest_additional_property_is_invalid(repo_root, registry):
    schema = load_schema(repo_root, "manifest")
    instance = sample_manifest()
    instance["extra"] = "nope"
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-MEM-07: manifest additionalProperties must be false (ADR-0002 decision 5)"


def test_FR_MEM_07_manifest_fixtures_directory_has_valid_and_invalid_files(repo_root):
    valid = list_cc_sh_fixtures(repo_root, "manifest", "valid")
    invalid = list_cc_sh_fixtures(repo_root, "manifest", "invalid")
    assert valid, "FR-MEM-07: contracts/fixtures/manifest/valid/ must contain at least one *.json fixture"
    assert invalid, "FR-MEM-07: contracts/fixtures/manifest/invalid/ must contain at least one *.json fixture"


def test_FR_MEM_07_manifest_valid_fixtures_pass_the_schema(repo_root, registry):
    fixtures = list_cc_sh_fixtures(repo_root, "manifest", "valid")
    assert fixtures, "FR-MEM-07: no valid manifest fixtures found -- see the fixtures-directory test"
    schema = load_schema(repo_root, "manifest")
    for path in fixtures:
        errors = errors_for(schema, load_json(path), registry)
        assert not errors, (
            f"FR-MEM-07: {path.name} must validate against manifest.schema.json, got: {[e.message for e in errors][:3]}"
        )


def test_FR_MEM_07_manifest_invalid_fixtures_fail_the_schema(repo_root, registry):
    fixtures = list_cc_sh_fixtures(repo_root, "manifest", "invalid")
    assert fixtures, "FR-MEM-07: no invalid manifest fixtures found -- see the fixtures-directory test"
    schema = load_schema(repo_root, "manifest")
    for path in fixtures:
        errors = errors_for(schema, load_json(path), registry)
        assert errors, (
            f"FR-MEM-07: {path.name} must fail validation against manifest.schema.json (name says which rule)"
        )


def test_FR_MEM_07_generated_python_type_exists(repo_root):
    src = repo_root / CONTRACTS_PY_SRC
    assert src.is_dir(), f"FR-MEM-07: {CONTRACTS_PY_SRC}/ must exist"
    pattern = re.compile(r"\bclass\s+Manifest\b")
    hit = any(pattern.search(p.read_text(encoding="utf-8", errors="ignore")) for p in src.rglob("*.py"))
    assert hit, f"FR-MEM-07: no generated Python class 'Manifest' found under {CONTRACTS_PY_SRC}/"


def test_FR_MEM_07_generated_typescript_type_exists(repo_root):
    src = repo_root / CONTRACTS_TS_SRC
    assert src.is_dir(), f"FR-MEM-07: {CONTRACTS_TS_SRC}/ must exist"
    pattern = re.compile(r"\b(?:interface|type)\s+Manifest\b")
    ts_files = list(src.rglob("*.ts")) + list(src.rglob("*.d.ts"))
    hit = any(pattern.search(p.read_text(encoding="utf-8", errors="ignore")) for p in ts_files)
    assert hit, f"FR-MEM-07: no generated TypeScript interface/type 'Manifest' found under {CONTRACTS_TS_SRC}/"


@pytest.mark.slow
def test_FR_MEM_07_contracts_check_fails_on_manifest_schema_drift(repo_root, tmp_path):
    schema_path = repo_root / "contracts" / "manifest.schema.json"
    assert schema_path.is_file(), "FR-MEM-07: contracts/manifest.schema.json must exist before this runs"

    work_dir = tmp_path / "manifest-drift"
    _copy_runnable_repo(repo_root, work_dir)

    rel = schema_path.relative_to(repo_root)
    mutated_path = work_dir / rel
    schema = json.loads(mutated_path.read_text(encoding="utf-8"))
    schema.setdefault("$defs", {})["drift_marker_field_not_in_generated_output"] = {"type": "string"}
    mutated_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    result = _run_contracts_check(work_dir, repo_root / ".venv")
    msg = f"FR-MEM-07: contracts-check must fail on drift.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.returncode != 0, msg
