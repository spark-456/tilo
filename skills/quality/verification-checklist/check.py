# quality/verification-checklist checker (FR-AGT-04).
from skills._lib import guard

_VERDICTS = {"verified", "unverified", "false"}


@guard.fail_closed
def check(inputs: dict, output: dict) -> list[dict]:
    claims = inputs.get("deliverable_claims", [])
    claim_ids = [c.get("claim_id") for c in claims if isinstance(c, dict)]
    evidence_ids = guard.str_ids(inputs.get("evidence"), "source_id")

    verdicts = output.get("verdicts")
    findings = guard.ids_exactly_once(claim_ids, verdicts, "claim_id")

    for v in verdicts if isinstance(verdicts, list) else []:
        if not isinstance(v, dict):
            continue
        cid, verdict = v.get("claim_id"), v.get("verdict")
        cited = v.get("evidence_source_ids") if isinstance(v.get("evidence_source_ids"), list) else []
        bad_verdict = verdict not in _VERDICTS
        findings += [guard.finding("verdict-invalid", f"{cid}: {verdict!r} invalid")] if bad_verdict else []
        unknown = [e for e in cited if e not in evidence_ids]
        findings += [guard.finding("evidence-unknown", f"{cid}: {unknown} unknown")] if unknown else []
        needs_ev = verdict == "verified" and not cited
        findings += [guard.finding("verified-needs-evidence", f"{cid}: verified, no evidence")] if needs_ev else []
    return findings
