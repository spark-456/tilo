from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from tilo_harness.skill_proposals import SkillProposals
from tilo_harness.skills import SkillRegistry
from tilo_harness.validator import repo_validator

REPO_ROOT = Path(__file__).resolve().parents[4]
SKILLS_ROOT = REPO_ROOT / "skills"
STREAMS_ROOT = REPO_ROOT / "contracts" / "fixtures" / "streams"
SKILL_DIR = SKILLS_ROOT / "automation" / "agent-self-report"

CITATION_PATTERN = re.compile(r"\[seq:\s*([0-9]+(?:\s*,\s*[0-9]+)*)\]")
FIRST_PERSON_PATTERN = re.compile(r"\b(i|my|we|our)\b", re.IGNORECASE)
ABSENT_PHRASE = "I have no record of that"


def load_agent_unit_events(
    stream_file: str,
    agent_id: str,
    unit_id: str | None = None,
    up_to_seq: int | None = None,
) -> list[dict[str, Any]]:
    """Load recorded events for a single agent unit from a stream fixture in contracts/fixtures/streams/."""
    path = STREAMS_ROOT / stream_file
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    filtered: list[dict[str, Any]] = []
    for ev in rows:
        if up_to_seq is not None and ev["seq"] > up_to_seq:
            continue
        actor_or_target = ev.get("actor") == agent_id or ev.get("target") == agent_id
        data = ev.get("data") or {}
        envelope = data.get("envelope") or {}
        in_envelope = envelope.get("from") == agent_id or envelope.get("to") == agent_id
        unit_match = unit_id is None or data.get("unit") in (None, unit_id)
        if (actor_or_target or in_envelope) and unit_match:
            filtered.append(ev)
    return filtered


def _split_sentences(text: str) -> list[str]:
    parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    return parts


def check_MEETROOM_SELF_REPORT_output(
    case_input: dict[str, Any],
    events: list[dict[str, Any]],
    output: dict[str, Any],
) -> list[str]:
    """Input-computable checker for ADR-0028 / MEETROOM_SELF_REPORT."""
    errors: list[str] = []
    valid_seqs = {int(ev["seq"]) for ev in events}
    if not valid_seqs:
        errors.append("unit event slice is empty")
        return errors

    answer = output.get("answer", "").strip()
    if not answer:
        errors.append("answer must not be empty")
        return errors

    if not FIRST_PERSON_PATTERN.search(answer):
        errors.append(f"answer must be in first person, got: {answer!r}")

    sentences = _split_sentences(answer)
    if not sentences:
        errors.append("answer has no sentences")

    all_inline_seqs: list[int] = []
    for idx, sentence in enumerate(sentences):
        matches = CITATION_PATTERN.findall(sentence)
        if not matches:
            errors.append(f"sentence[{idx}] is missing a [seq: N] citation: {sentence!r}")
            continue
        for grp in matches:
            for raw_num in grp.split(","):
                seq_num = int(raw_num.strip())
                all_inline_seqs.append(seq_num)
                if seq_num not in valid_seqs:
                    errors.append(
                        f"sentence[{idx}] cites seq {seq_num} which is not in unit events {sorted(valid_seqs)}"
                    )

    cited_seqs = output.get("cited_seqs", [])
    if not cited_seqs:
        errors.append("cited_seqs must be non-empty")
    for seq_num in cited_seqs:
        if seq_num not in valid_seqs:
            errors.append(f"cited_seqs contains {seq_num} not in unit events {sorted(valid_seqs)}")

    if set(cited_seqs) != set(all_inline_seqs):
        errors.append(f"cited_seqs {sorted(set(cited_seqs))} != inline cited seqs {sorted(set(all_inline_seqs))}")

    for section_key in ("what_i_did", "why", "what_is_left"):
        claims = output.get(section_key, [])
        for c_idx, claim in enumerate(claims):
            text = claim.get("claim", "")
            c_seqs = claim.get("seqs", [])
            if not c_seqs:
                errors.append(f"{section_key}[{c_idx}] has empty seqs")
            for s_num in c_seqs:
                if s_num not in valid_seqs:
                    errors.append(f"{section_key}[{c_idx}] cites seq {s_num} not in {sorted(valid_seqs)}")
            if not CITATION_PATTERN.search(text):
                errors.append(f"{section_key}[{c_idx}].claim is missing inline [seq: N]: {text!r}")

    question_kind = case_input.get("question_kind")
    if question_kind == "absent_fact":
        if ABSENT_PHRASE not in answer:
            errors.append(f"absent_fact answer must contain {ABSENT_PHRASE!r}")
        if output.get("has_record") is not False:
            errors.append("absent_fact output must set has_record=False")
    else:
        if output.get("has_record") is not True:
            errors.append(f"recorded fact question ({question_kind}) must set has_record=True")

    if question_kind == "why":
        if not output.get("why"):
            errors.append("why question must populate non-empty 'why' claims")

    return errors


def test_ADR_0028_MEETROOM_SELF_REPORT_skill_loads_and_conforms_to_contract() -> None:
    registry = SkillRegistry(SKILLS_ROOT)
    assert registry.problems == {}
    loaded = registry.load("agent-self-report")
    assert loaded.version == "1.0.0"

    raw = yaml.safe_load((SKILL_DIR / "skill.yaml").read_text(encoding="utf-8"))
    assert raw["domain"] == "automation"
    assert raw["tools_allowed"] == []
    assert repo_validator().contract_problems("skill", raw) == []
    jsonschema.Draft202012Validator.check_schema(raw["inputs"])
    jsonschema.Draft202012Validator.check_schema(raw["outputs"])

    for section in ("When to use", "Steps", "Quality bar", "Checklist", "Pitfalls"):
        assert section in loaded.body, f"SKILL.md missing section {section}"

    proposals = SkillProposals(registry)
    decision = {
        "id": "01J9RP8V7X2K4M6N8P0Q2R4S6T",
        "org_id": "org_acme",
        "domain": "automation",
        "question": "How should an agent answer when asked about an unrecorded event?",
        "answer": "Always state 'I have no record of that' and cite the recorded unit event sequence numbers.",
        "option_id": None,
        "answered_by": {
            "by": "team_lead",
            "ref": "tl_automation",
            "user": "u_lead_auto",
            "at": "2026-10-08T12:00:00.000Z",
        },
        "source": {
            "world_id": "w_main",
            "run_id": "r_001",
            "card_id": "01J9RP8V7X2K4M6N8P0Q2R4S6V",
        },
        "scope": {"worlds": "all", "districts": "all"},
        "created_at": "2026-10-08T12:00:00.000Z",
        "expires_at": None,
    }
    proposal = proposals.propose(
        decision=decision,
        skill_id="agent-self-report",
        proposer="u_lead_auto",
    )
    assert proposal["to_version"] == "1.0.1"


def test_ADR_0028_MEETROOM_SELF_REPORT_golden_questions_across_two_recorded_streams() -> None:
    raw = yaml.safe_load((SKILL_DIR / "skill.yaml").read_text(encoding="utf-8"))
    in_validator = jsonschema.Draft202012Validator(raw["inputs"])
    out_validator = jsonschema.Draft202012Validator(raw["outputs"])

    golden = json.loads((SKILL_DIR / "examples" / "golden_cases.json").read_text(encoding="utf-8"))
    cases = golden["cases"]
    assert len(cases) >= 6

    streams_used = {c["stream_file"] for c in cases}
    assert {"village-basic.jsonl", "artifact-versions.jsonl"} <= streams_used

    question_kinds = {c["input"]["question_kind"] for c in cases}
    assert {"what_did_you_do", "why", "what_is_left", "absent_fact"} <= question_kinds

    for case in cases:
        events = load_agent_unit_events(
            stream_file=case["stream_file"],
            agent_id=case["input"]["agent_id"],
            unit_id=case["input"].get("unit_id"),
            up_to_seq=case["input"].get("up_to_seq"),
        )
        full_input = {**case["input"], "events": events}
        in_validator.validate(full_input)
        out_validator.validate(case["output"])

        errs = check_MEETROOM_SELF_REPORT_output(case["input"], events, case["output"])
        assert errs == [], f"Case {case['id']} failed checker: {errs}"


def test_ADR_0028_MEETROOM_SELF_REPORT_checker_rejects_uncited_sentences_and_missing_seq() -> None:
    golden = json.loads((SKILL_DIR / "examples" / "golden_cases.json").read_text(encoding="utf-8"))
    case = golden["cases"][0]
    events = load_agent_unit_events(
        stream_file=case["stream_file"],
        agent_id=case["input"]["agent_id"],
        unit_id=case["input"].get("unit_id"),
        up_to_seq=case["input"].get("up_to_seq"),
    )

    uncited = json.loads(json.dumps(case["output"]))
    uncited["answer"] = uncited["answer"] + " I also reorganised the archive folder."
    errs_uncited = check_MEETROOM_SELF_REPORT_output(case["input"], events, uncited)
    assert any("missing a [seq: N] citation" in e for e in errs_uncited)

    bad_seq = json.loads(json.dumps(case["output"]))
    bad_seq["answer"] = "I completed the task [seq: 999]."
    bad_seq["cited_seqs"] = [999]
    errs_bad_seq = check_MEETROOM_SELF_REPORT_output(case["input"], events, bad_seq)
    assert any("999" in e for e in errs_bad_seq)
