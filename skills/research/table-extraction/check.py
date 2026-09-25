"""Deterministic quality-bar checker for research/table-extraction.

Pure standard library. Never raises: malformed output always yields at least
one finding (fail closed). See SKILL.md "Quality bar" for the check ids this
module can return.
"""

from __future__ import annotations


def check(inputs: dict, output: dict) -> list[dict]:
    if not isinstance(output, dict):
        return [{"check": "output-malformed", "detail": "output must be an object"}]

    records = output.get("records")
    if not isinstance(records, list):
        return [{"check": "output-malformed", "detail": "output.records must be an array"}]

    inputs = inputs if isinstance(inputs, dict) else {}
    table = inputs.get("table") if isinstance(inputs.get("table"), dict) else {}
    rows = table.get("rows") if isinstance(table.get("rows"), list) else []

    known_refs: set[str] = set()
    ref_to_text: dict[str, str] = {}
    row_count = 0
    for row in rows:
        if not isinstance(row, list):
            continue
        row_count += 1
        for cell in row:
            if isinstance(cell, dict) and isinstance(cell.get("ref"), str):
                known_refs.add(cell["ref"])
                ref_to_text[cell["ref"]] = cell.get("value")

    findings: list[dict] = []
    if len(records) > row_count:
        findings.append(
            {
                "check": "no-invented-rows",
                "detail": f"{len(records)} records were produced for only {row_count} input rows",
            }
        )

    for i, record in enumerate(records):
        if not isinstance(record, dict):
            findings.append({"check": "output-malformed", "detail": f"records[{i}] is not an object"})
            continue
        fields = record.get("fields")
        if not isinstance(fields, dict):
            findings.append({"check": "output-malformed", "detail": f"records[{i}].fields must be an object"})
            continue
        for name, field in fields.items():
            if not isinstance(field, dict) or "value" not in field or "source_ref" not in field:
                findings.append(
                    {
                        "check": "output-malformed",
                        "detail": f"records[{i}].fields[{name!r}] must have value and source_ref",
                    }
                )
                continue
            ref = field.get("source_ref")
            if ref not in known_refs:
                findings.append(
                    {"check": "source-ref-known", "detail": f"records[{i}].fields[{name!r}] cites unknown cell {ref!r}"}
                )
                continue
            raw = ref_to_text.get(ref)
            value = field.get("value")
            parsed = _parse_number(raw)
            if parsed is not None:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or value != parsed:
                    findings.append(
                        {
                            "check": "number-parses-exactly",
                            "detail": f"records[{i}].fields[{name!r}] value {value!r} does not exactly match {raw!r}",
                        }
                    )
    return findings


def _parse_number(raw: object) -> float | int | None:
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        if any(c in text for c in (".", "e", "E")):
            return float(text)
        return int(text)
    except ValueError:
        return None
