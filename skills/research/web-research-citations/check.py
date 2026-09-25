# research/web-research-citations checker (FR-AGT-04): invariants only, from
# inputs.sources and the output. safety_flags come from the SafetyProvider.
from skills._lib import guard


@guard.fail_closed
def check(inputs: dict, output: dict) -> list[dict]:
    sources = inputs.get("sources", [])
    source_ids = guard.str_ids(sources, "id")
    flagged_expected = guard.str_ids([s for s in sources if isinstance(s, dict) and s.get("safety_flags")], "id")

    claims = output.get("claims")
    findings: list[dict] = []
    for i, c in enumerate(claims):
        cited = c.get("source_ids") if isinstance(c, dict) else None
        if not isinstance(cited, list) or not cited:
            findings.append(guard.finding("claim-no-citation", f"claims[{i}] cites nothing"))
            continue
        unknown = [s for s in cited if s not in source_ids]
        findings += [guard.finding("citation-unknown-source", f"claims[{i}]: {unknown}")] if unknown else []

    flagged_actual = {s for s in output.get("flagged_sources", []) if isinstance(s, str)}
    mismatch = flagged_actual != flagged_expected
    detail = f"got {sorted(flagged_actual)} want {sorted(flagged_expected)}"
    findings += [guard.finding("flagged-sources-mismatch", detail)] if mismatch else []
    return findings
