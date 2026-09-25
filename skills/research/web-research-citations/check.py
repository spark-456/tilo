"""Deterministic quality-bar checker for research/web-research-citations.

Pure standard library. Never raises: malformed output always yields at least
one finding (fail closed). See SKILL.md "Quality bar" for the check ids this
module can return.
"""

from __future__ import annotations

from typing import Any


def check(inputs: dict, output: dict) -> list[dict]:
    if not isinstance(output, dict):
        return [{"check": "output-malformed", "detail": "output must be an object"}]

    findings_out = output.get("findings")
    if not isinstance(findings_out, list):
        return [{"check": "output-malformed", "detail": "output.findings must be an array"}]

    inputs = inputs if isinstance(inputs, dict) else {}
    sources = inputs.get("sources")
    known_ids: set[Any] = set()
    if isinstance(sources, list):
        for source in sources:
            if isinstance(source, dict) and isinstance(source.get("source_id"), str):
                known_ids.add(source["source_id"])

    findings: list[dict] = []
    for i, finding in enumerate(findings_out):
        if not isinstance(finding, dict):
            findings.append({"check": "output-malformed", "detail": f"findings[{i}] is not an object"})
            continue
        status = finding.get("status")
        source_ids = finding.get("source_ids")
        if not isinstance(source_ids, list):
            findings.append({"check": "output-malformed", "detail": f"findings[{i}].source_ids must be an array"})
            continue
        if status == "answered":
            if not source_ids:
                findings.append(
                    {"check": "citation-required", "detail": f"findings[{i}] is answered but cites no source"}
                )
            for source_id in source_ids:
                # source_id could be any JSON type (e.g. a list), which is
                # unhashable and would raise on `in` against a set.
                if not isinstance(source_id, str) or source_id not in known_ids:
                    findings.append(
                        {
                            "check": "citation-known-source",
                            "detail": f"findings[{i}] cites source {source_id!r} not present in the supplied sources",
                        }
                    )
        elif status == "unknown":
            if source_ids:
                findings.append(
                    {
                        "check": "unknown-has-no-citation",
                        "detail": f"findings[{i}] is marked unknown but still cites sources",
                    }
                )
        else:
            findings.append(
                {"check": "output-malformed", "detail": f"findings[{i}].status must be 'answered' or 'unknown'"}
            )
    return findings
