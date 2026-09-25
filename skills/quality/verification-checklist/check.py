"""Deterministic quality-bar checker for quality/verification-checklist.

Pure standard library. Never raises: malformed output always yields at least
one finding (fail closed). See SKILL.md "Quality bar" for the check ids this
module can return.
"""

from __future__ import annotations

_VALID_VERDICTS = {"verified", "unverified", "false"}


def check(inputs: dict, output: dict) -> list[dict]:
    if not isinstance(output, dict):
        return [{"check": "output-malformed", "detail": "output must be an object"}]
    verdicts = output.get("verdicts")
    if not isinstance(verdicts, list):
        return [{"check": "output-malformed", "detail": "output.verdicts must be an array"}]

    inputs = inputs if isinstance(inputs, dict) else {}
    claims = inputs.get("deliverable_claims") if isinstance(inputs.get("deliverable_claims"), list) else []
    evidence = inputs.get("evidence") if isinstance(inputs.get("evidence"), list) else []
    claim_ids = {c.get("claim_id") for c in claims if isinstance(c, dict)}
    evidence_ids = {e.get("source_id") for e in evidence if isinstance(e, dict)}

    findings: list[dict] = []
    seen: dict[object, int] = {}
    for i, verdict_row in enumerate(verdicts):
        if not isinstance(verdict_row, dict):
            findings.append({"check": "output-malformed", "detail": f"verdicts[{i}] is not an object"})
            continue
        raw_claim_id = verdict_row.get("claim_id")
        verdict = verdict_row.get("verdict")
        evidence_source_ids = verdict_row.get("evidence_source_ids")
        # claim_id and verdict could be any JSON type (e.g. a list), which is
        # unhashable and would raise on a dict key or `in` a set — check the
        # type before either use.
        claim_id = raw_claim_id if isinstance(raw_claim_id, str) else None
        if claim_id is None:
            findings.append({"check": "output-malformed", "detail": f"verdicts[{i}].claim_id must be a string"})
        if not isinstance(verdict, str) or verdict not in _VALID_VERDICTS:
            findings.append(
                {
                    "check": "verdict-invalid",
                    "detail": f"verdicts[{i}].verdict {verdict!r} must be verified/unverified/false",
                }
            )
        if not isinstance(evidence_source_ids, list):
            findings.append(
                {"check": "output-malformed", "detail": f"verdicts[{i}].evidence_source_ids must be an array"}
            )
            evidence_source_ids = []
        if claim_id is not None:
            seen[claim_id] = seen.get(claim_id, 0) + 1
        if verdict == "verified":
            unknown = [e for e in evidence_source_ids if not isinstance(e, str) or e not in evidence_ids]
            if not evidence_source_ids or unknown:
                findings.append(
                    {
                        "check": "verified-needs-known-evidence",
                        "detail": f"verdicts[{i}] is verified but cites {unknown or 'no'} evidence not in the inputs",
                    }
                )

    for claim_id in claim_ids:
        count = seen.get(claim_id, 0)
        if count == 0:
            findings.append({"check": "claim-not-covered", "detail": f"claim {claim_id!r} has no verdict"})
        elif count > 1:
            findings.append({"check": "claim-not-covered", "detail": f"claim {claim_id!r} has more than one verdict"})
    return findings
